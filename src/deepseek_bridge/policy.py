"""Authorization comes only from private owner records, never an agent envelope."""

import fnmatch
import json
import os
import stat
import time
from pathlib import Path

from pydantic import Field

from .contracts import Handoff, StrictModel
from .errors import BridgeError
from .settings import Settings


class Scope(StrictModel):
    repository: str
    version: str
    expires: float
    files: list[str] = Field(default_factory=list)
    allow_inline: bool = False
    sensitive: bool = False
    passive_activities: list[str] = Field(default_factory=lambda: ["passive_analysis"])
    max_output_tokens: int = Field(default=4000, ge=1, le=8000)
    timeout_seconds: int = Field(default=120, ge=1, le=300)


class TrustedTask(StrictModel):
    revision: int = Field(ge=1)
    scope_id: str
    session_id: str
    objective: str


class Registry(StrictModel):
    scopes: dict[str, Scope]
    tasks: dict[str, TrustedTask]


def load_registry(settings: Settings) -> Registry:
    path = settings.scope_registry
    if path is None:
        raise BridgeError("approval_required", "Trusted scope registry is not configured")
    path = path.expanduser().absolute()
    for repo in settings.repositories.values():
        if path.resolve().is_relative_to(repo.path.resolve()):
            raise BridgeError(
                "permission_boundary", "Trusted registry must live outside repositories"
            )
    roots = [settings.storage.state_dir / "worktrees", settings.worker.worktree_root]
    if any(root and path.resolve().is_relative_to(root.resolve()) for root in roots):
        raise BridgeError(
            "permission_boundary", "Trusted registry cannot live in a worker worktree"
        )
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            parent = path.parent.stat()
            if (
                info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
                or parent.st_uid != os.getuid()
                or stat.S_IMODE(parent.st_mode) & 0o022
            ):
                raise BridgeError("permission_boundary", "Trusted registry must be owner-private")
            raw = stream.read(200001)
            if len(raw) > 200000:
                raise BridgeError("invalid_request", "Trusted registry exceeds size limit")
        registry = Registry.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise BridgeError("approval_required", "Trusted registry missing or malformed") from exc
    for scope in registry.scopes.values():
        if any(
            rule in {"*", "**", "**/*"} or Path(rule).is_absolute() or ".." in Path(rule).parts
            for rule in scope.files
        ):
            raise BridgeError("permission_boundary", "Broad wildcard or invalid scope file rule")
        if scope.passive_activities != ["passive_analysis"]:
            raise BridgeError("unsupported_capability", "Active research is unsupported")
    return registry


def resolve(settings: Settings, handoff: Handoff, session: str) -> Scope:
    registry = load_registry(settings)
    task = registry.tasks.get(handoff.task_id)
    scope = registry.scopes.get(handoff.scope_id)
    if not task or (task.revision, task.scope_id, task.session_id, task.objective) != (
        handoff.revision,
        handoff.scope_id,
        session,
        handoff.objective,
    ):
        raise BridgeError(
            "permission_boundary", "Handoff does not match an owner-created task revision"
        )
    if not scope or scope.expires <= time.time():
        raise BridgeError("approval_required", "Trusted scope missing or expired")
    if scope.repository != handoff.context.repository:
        raise BridgeError("out_of_scope", "Research repository does not match trusted scope")
    settings.repository(scope.repository)
    for name in handoff.context.files:
        if not any(fnmatch.fnmatchcase(name, rule) for rule in scope.files):
            raise BridgeError("out_of_scope", "Selected research file is outside trusted scope")
    return scope


def scope_fingerprint(scope: Scope) -> str:
    from .context import digest

    return digest(json.loads(scope.model_dump_json()))
