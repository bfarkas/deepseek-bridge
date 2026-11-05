"""Bounded snapshots. No implicit repository or transcript collection."""

import fnmatch
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from .contracts import Context
from .credentials import get_api_key
from .errors import BridgeError
from .settings import Settings

SENSITIVE = (
    ".env*",
    "*.pem",
    "*.key",
    "*credentials*",
    "*secret*",
    "id_rsa*",
    "id_ed25519*",
    ".git",
    ".aws",
    ".ssh",
    ".npmrc",
    ".netrc",
    "*.p12",
    "*.pfx",
)
SECRET = re.compile(
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)|\b(?:sk-[A-Za-z0-9_-]{16,}|"
    r"AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{20,})|"
    r"(?i:(?:api[_-]?key|password|access[_-]?token)\s*[=:]\s*[\"']?[^\s\"']{8,})"
)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def check_text(text: str, limit: int = 200000, credential_env: str = "DEEPSEEK_API_KEY") -> None:
    if len(text.encode()) > limit:
        raise BridgeError("budget_exceeded", "Outbound context exceeds byte limit")
    if "\x00" in text or SECRET.search(text):
        raise BridgeError(
            "out_of_scope", "Outbound context contains binary data or a possible secret"
        )
    key = os.environ.get(credential_env)
    if key and key in text:
        raise BridgeError("out_of_scope", "Outbound context contains a credential")
    # Diff headers can expose a forbidden file even when provided inline.
    for line in text.splitlines():
        if line.startswith(("+++ ", "--- ", "diff --git ")):
            for token in line.split()[1:]:
                if token != "/dev/null" and forbidden(token):
                    raise BridgeError("out_of_scope", "Diff references a sensitive path")


def forbidden(name: str) -> bool:
    parts = Path(name).parts
    return any(
        p in {"..", "/"} or any(fnmatch.fnmatch(p.lower(), rule) for rule in SENSITIVE)
        for p in parts
    )


def read_selected(root: Path, name: str, limit: int) -> str:
    path = Path(name)
    if path.is_absolute() or not path.parts or forbidden(name):
        raise BridgeError("out_of_scope", "Forbidden context path")
    # Traverse by descriptors; O_NOFOLLOW rejects symlinks including parent components.
    fd = os.open(root.resolve(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise BridgeError("out_of_scope", "Context file is not regular or exceeds limit")
            raw = os.read(file_fd, limit + 1)
            after = os.fstat(file_fd)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise BridgeError("out_of_scope", "Context file changed while reading")
            text = raw.decode("utf-8")
            check_text(text, limit)
            return text
        finally:
            os.close(file_fd)
    except (OSError, UnicodeError) as exc:
        raise BridgeError("out_of_scope", "Cannot safely read selected context file") from exc
    finally:
        os.close(fd)


def collect(settings: Settings, context: Context) -> dict[str, Any]:
    if context.files and not context.repository:
        raise BridgeError("invalid_request", "Selected files require a repository alias")
    if len(context.files) > settings.consultant.max_files:
        raise BridgeError("budget_exceeded", "Too many selected files")
    check_text(context.text, settings.consultant.max_input_bytes, settings.deepseek.api_key_env)
    check_text(context.diff, settings.consultant.max_input_bytes, settings.deepseek.api_key_env)
    files: list[dict[str, str]] = []
    if context.repository:
        repo = settings.repository(context.repository)
        for name in context.files:
            content = read_selected(repo.path, name, settings.consultant.max_input_bytes)
            files.append(
                {
                    "path": name,
                    "text": content,
                    "sha256": hashlib.sha256(content.encode()).hexdigest(),
                }
            )
    result = {
        "repository": context.repository,
        "files": files,
        "text": context.text,
        "diff": context.diff,
    }
    check_value(settings, result)
    check_text(
        json.dumps(result), settings.consultant.max_input_bytes, settings.deepseek.api_key_env
    )
    check_text(context.diff, settings.consultant.max_input_bytes)
    return result


def check_value(settings: Settings, value: Any) -> None:
    """Inspect raw strings before JSON escaping can hide line headers or control bytes."""
    if isinstance(value, str):
        key = get_api_key(settings)
        if key and key in value:
            raise BridgeError("out_of_scope", "Outbound context contains a credential")
        check_text(value, settings.consultant.max_input_bytes, settings.deepseek.api_key_env)
    elif isinstance(value, list):
        for item in value:
            check_value(settings, item)
    elif isinstance(value, dict):
        for item in value.values():
            check_value(settings, item)
