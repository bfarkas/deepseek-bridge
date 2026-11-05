import time
from typing import Any, Protocol, cast

import anthropic
from anthropic.types import MessageParam

from .credentials import get_api_key
from .errors import BridgeError
from .settings import Settings

MODELS = {"deepseek-flash", "deepseek-v4-pro"}


class Provider(Protocol):
    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        system: str,
        max_tokens: int,
        timeout: float,
        effort: str | None = None,
    ) -> dict[str, Any]: ...


class DeepSeekProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        system: str,
        max_tokens: int,
        timeout: float,
        effort: str | None = None,
    ) -> dict[str, Any]:
        if model not in MODELS:
            raise BridgeError(
                "unsupported_capability", "Model ID has not been capability-validated"
            )
        # Exact effort semantics remain an M0 live gate; never silently drop the parameter.
        if effort is not None:
            raise BridgeError("unsupported_capability", "Effort mapping has not been live-verified")
        key = get_api_key(self.settings)
        if not key:
            raise BridgeError(
                "invalid_request",
                "DeepSeek credential missing; set an environment key, private file or Keychain",
            )
        deadline = time.monotonic() + timeout
        with anthropic.Anthropic(
            api_key=key, base_url=self.settings.deepseek.base_url, max_retries=0
        ) as client:
            for attempt in range(3):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BridgeError(
                        "provider_timeout", "Provider deadline exceeded; usage unknown"
                    )
                try:
                    response = client.messages.create(
                        model=model,
                        messages=cast(list[MessageParam], messages),
                        system=system,
                        max_tokens=max_tokens,
                        timeout=remaining,
                        thinking={"type": "disabled"},
                    )
                    return response.model_dump(mode="json")
                except anthropic.APITimeoutError as exc:
                    # A response may have been billed: do not blindly retry.
                    raise BridgeError(
                        "provider_timeout", "Provider timed out; usage unknown"
                    ) from exc
                except anthropic.APIConnectionError as exc:
                    raise BridgeError(
                        "provider_error", "Provider connection failed; usage unknown"
                    ) from exc
                except anthropic.APIStatusError as exc:
                    # Only an explicit rate-limit rejection is safe to retry automatically.
                    if exc.status_code != 429 or attempt == 2:
                        raise BridgeError(
                            "provider_error",
                            "Provider rejected request",
                            exc.status_code in {429, 500, 502, 503, 504},
                        ) from exc
                    delay = min(2**attempt, max(0, deadline - time.monotonic()))
                    time.sleep(delay)
        raise BridgeError("provider_error", "Provider retries exhausted", True)
