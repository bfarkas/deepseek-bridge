"""Hooks persist local intent only. Never call a provider or read arbitrary transcripts."""

import json
from typing import Any

from pydantic import ValidationError

from .contracts import Handoff
from .database import Database
from .errors import BridgeError
from .research import ResearchService
from .settings import Settings

BEGIN, END = "DEEPSEEK_HANDOFF_BEGIN", "DEEPSEEK_HANDOFF_END"
MAX_EVENT_BYTES = 250000


def ingest(raw: bytes, settings: Settings, db: Database) -> dict[str, Any] | None:
    if len(raw) > MAX_EVENT_BYTES:
        raise BridgeError("invalid_request", "Hook payload exceeds size limit")
    try:
        event = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise BridgeError("invalid_request", "Malformed hook JSON") from exc
    if not isinstance(event, dict):
        raise BridgeError("invalid_request", "Hook event must be an object")
    name = event.get("hook_event_name")
    if name not in {"Stop", "SubagentStop"}:
        db.telemetry(
            str(name)
            if name in {"StopFailure", "PermissionDenied", "PostToolUseFailure"}
            else "unsupported_hook"
        )
        return None
    if event.get("stop_hook_active"):
        db.telemetry("recursive_stop_ignored")
        return None
    session = event.get("session_id")
    message = event.get("last_assistant_message", "")
    if not isinstance(message, str) or BEGIN not in message:
        return None
    if not isinstance(session, str) or not session or len(session) > 200:
        raise BridgeError("invalid_request", "Hook has no bounded session identity")
    if message.count(BEGIN) != 1 or message.count(END) != 1:
        raise BridgeError("invalid_request", "Expected exactly one handoff envelope")
    body = message.split(BEGIN, 1)[1].split(END, 1)[0].strip()
    try:
        handoff = Handoff.model_validate_json(body)
    except ValidationError as exc:
        raise BridgeError("invalid_request", "Malformed handoff envelope") from exc
    if handoff.task_status == "completed":
        return None
    if handoff.blocker_type in {"permission_denied", "safety_boundary"}:
        db.telemetry("research_boundary_no_dispatch")
        return None
    return ResearchService(settings, db).enqueue(handoff, session, automatic=True)
