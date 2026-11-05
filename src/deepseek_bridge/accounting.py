from typing import Any

from .contracts import Usage
from .settings import Settings


def account(response: dict[str, Any], settings: Settings) -> Usage:
    raw = response.get("usage") or {}
    usage = Usage(
        model=response.get("model"),
        input_tokens=raw.get("input_tokens"),
        output_tokens=raw.get("output_tokens"),
        cached_input_tokens=raw.get("cache_read_input_tokens"),
        cache_creation_input_tokens=raw.get("cache_creation_input_tokens"),
        provider_request_id=response.get("id"),
    )
    price = settings.prices.get(usage.model or "")
    if price and usage.input_tokens is not None and usage.output_tokens is not None:
        # Anthropic input_tokens excludes cache reads/creation. Missing counts stay unknown.
        if usage.cached_input_tokens is not None and usage.cache_creation_input_tokens == 0:
            usage.cost_usd_estimate = (
                usage.input_tokens * price.input_per_million
                + usage.output_tokens * price.output_per_million
                + usage.cached_input_tokens * price.cached_per_million
            ) / 1_000_000
            usage.pricing_version = price.version
    return usage


def preflight(settings: Settings, model: str, input_bytes: int, output_tokens: int) -> None:
    from .errors import BridgeError

    price = settings.prices.get(model)
    if price is None:
        return  # Unknown prices remain unknown; byte/time/token limits still apply.
    estimate = (
        (input_bytes + 256) * max(price.input_per_million, price.cached_per_million)
        + output_tokens * price.output_per_million
    ) / 1_000_000
    if estimate > settings.jobs.estimated_cost_limit_usd:
        raise BridgeError(
            "budget_exceeded", "Conservative request estimate exceeds configured dollar limit"
        )
