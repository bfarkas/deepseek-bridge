from typing import Any

from .contracts import Usage


def account(response: dict[str, Any]) -> Usage:
    raw = response.get("usage") or {}
    return Usage(
        model=response.get("model"),
        input_tokens=raw.get("input_tokens"),
        output_tokens=raw.get("output_tokens"),
        cached_input_tokens=raw.get("cache_read_input_tokens"),
        cache_creation_input_tokens=raw.get("cache_creation_input_tokens"),
        provider_request_id=response.get("id"),
    )
