import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .credentials import get_api_key
from .errors import BridgeError
from .processes import environment, run
from .settings import Settings, private_dir


def available(settings: Settings) -> Path:
    worker = settings.worker
    if not worker.enabled or not worker.compatibility_verified or not worker.expected_version:
        raise BridgeError(
            "worker_unavailable", "Enable worker only after recording pinned compatibility"
        )
    resolved = shutil.which(worker.executable)
    if not resolved or not Path(resolved).is_absolute():
        raise BridgeError("worker_unavailable", "Configured OpenCode executable is unavailable")
    result = run([resolved, "--version"], Path.cwd(), environment(), 10, 10000)
    if result["exit_code"] or result["output"].decode().strip() != worker.expected_version:
        raise BridgeError("worker_unavailable", "OpenCode version differs from configured pin")
    return Path(resolved)


def worker_environment(settings: Settings, private: Path, worktree: Path) -> dict[str, str]:
    # Reject executable extensions rather than trying to merge repository-controlled config.
    for root in (worktree, *worktree.parents):
        if any((root / name).exists() for name in (".opencode", "opencode.json", "opencode.jsonc")):
            raise BridgeError("permission_boundary", "Unapproved OpenCode project configuration")
    home = private_dir(private / "home")
    env = environment()
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(private_dir(private / "config")),
            "XDG_DATA_HOME": str(private_dir(private / "data")),
            "XDG_CACHE_HOME": str(private_dir(private / "cache")),
            "XDG_STATE_HOME": str(private_dir(private / "state")),
        }
    )
    key = get_api_key(settings)
    if not key:
        raise BridgeError("invalid_request", "DeepSeek credential is missing")
    env["DEEPSEEK_API_KEY"] = key
    permission = {
        "*": "deny",
        "read": "allow",
        "edit": "allow",
        "glob": "allow",
        "grep": "allow",
        "bash": {"*": "deny"},
        "external_directory": "deny",
    }
    # Trusted profiles run shell commands; workers edit through native tools.
    config = {
        "model": settings.worker.model,
        "autoupdate": False,
        "share": "disabled",
        "snapshot": False,
        "plugin": [],
        "mcp": {},
        "permission": permission,
        "enabled_providers": ["deepseek"],
        "lsp": False,
        "formatter": False,
    }
    path = private / "opencode.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    env["OPENCODE_CONFIG"] = str(path)
    return env


def validate_effective(raw: bytes, config_path: Path | None = None) -> None:
    try:
        config: dict[str, Any] = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise BridgeError(
            "worker_unavailable", "Cannot parse effective OpenCode configuration"
        ) from exc
    if isinstance(config, list):
        validate_sources(config, config_path)
        return
    if not isinstance(config, dict):
        raise BridgeError("permission_boundary", "Unexpected OpenCode configuration shape")
    if (
        config.get("plugin")
        or config.get("mcp")
        or config.get("instructions")
        or config.get("command")
        or config.get("agent")
    ):
        raise BridgeError("permission_boundary", "Unexpected effective configuration extensions")
    expected = {
        "*": "deny",
        "read": "allow",
        "edit": "allow",
        "glob": "allow",
        "grep": "allow",
        "bash": {"*": "deny"},
        "external_directory": "deny",
    }
    if config.get("permission") != expected:
        raise BridgeError("permission_boundary", "Effective worker permissions are not scoped")
    required = {
        "autoupdate": False,
        "share": "disabled",
        "snapshot": False,
        "enabled_providers": ["deepseek"],
        "lsp": False,
        "formatter": False,
    }
    if any(config.get(key) != value for key, value in required.items()):
        raise BridgeError("permission_boundary", "Unexpected effective runtime options")


def parse_events(raw: bytes) -> dict[str, Any]:
    events = []
    model = None
    tokens: dict[str, int | None] = {
        "input_tokens": None,
        "output_tokens": None,
        "cached_input_tokens": None,
    }
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise BridgeError("parse_error", "Malformed OpenCode JSON event") from exc
        if not isinstance(event, dict) or "type" not in event:
            raise BridgeError("parse_error", "Invalid OpenCode event")
        if event["type"] == "error":
            raise BridgeError(
                "provider_error", "OpenCode reported an error; inspect private events"
            )
        part = event.get("part", {})
        model = event.get("modelID", model)
        if part.get("type") == "step-finish":
            raw_tokens = part.get("tokens", {})
            for target, source in (("input_tokens", "input"), ("output_tokens", "output")):
                if source in raw_tokens:
                    tokens[target] = (tokens[target] or 0) + raw_tokens[source]
            cache = raw_tokens.get("cache", {})
            if "read" in cache:
                tokens["cached_input_tokens"] = (tokens["cached_input_tokens"] or 0) + cache["read"]
        events.append(event)
    if not events:
        raise BridgeError("parse_error", "OpenCode returned no events")
    return {
        "model": model,
        **tokens,
        "cost_usd_estimate": None,
        "event_count": len(events),
        "events_sha256": hashlib.sha256(raw).hexdigest(),
    }


def within_token_budget(raw: bytes, output_limit: int) -> bool:
    total = 0
    for line in raw.split(b"\n")[:-1]:
        try:
            event = json.loads(line)
            part = event.get("part", {})
            if part.get("type") == "step-finish":
                total += part.get("tokens", {}).get("output", 0)
        except (ValueError, AttributeError, TypeError):
            continue  # Final parse_events reports malformed complete output separately.
    return total <= output_limit


def validate_sources(sources: list[Any], config_path: Path | None) -> None:
    """OpenCode v2 returns normalized source documents instead of a merged v1 object."""
    if config_path is None:
        raise BridgeError("permission_boundary", "Expected configuration path is required")
    document = None
    expected_directory = config_path.parent / "config/opencode"
    for source in sources:
        if not isinstance(source, dict):
            raise BridgeError("permission_boundary", "Invalid configuration source")
        kind, path = source.get("type"), source.get("path")
        if kind == "directory" and path == str(expected_directory):
            continue
        if kind != "document" or path != str(config_path) or document is not None:
            raise BridgeError("permission_boundary", "Unexpected configuration source")
        document = source.get("info")
    permissions = [
        {"action": action, "resource": "*", "effect": effect}
        for action, effect in [
            ("*", "deny"),
            ("read", "allow"),
            ("edit", "allow"),
            ("glob", "allow"),
            ("grep", "allow"),
            ("shell", "deny"),
            ("external_directory", "deny"),
        ]
    ]
    required = {
        "update": "disable",
        "share": "disabled",
        "permissions": permissions,
        "policies": [
            {"action": "provider.use", "resource": "*", "effect": "deny"},
            {"action": "provider.use", "resource": "deepseek", "effect": "allow"},
        ],
        "snapshots": False,
        "formatter": False,
        "lsp": False,
        "mcp": {},
        "plugins": [],
    }
    if not isinstance(document, dict) or set(document) != {*required, "model"}:
        raise BridgeError("permission_boundary", "Unexpected effective configuration extensions")
    if any(document.get(key) != value for key, value in required.items()):
        raise BridgeError("permission_boundary", "Effective v2 worker configuration is not scoped")
    model = document.get("model", {})
    if model.get("providerID") != "deepseek":
        raise BridgeError("permission_boundary", "Unexpected model provider")
