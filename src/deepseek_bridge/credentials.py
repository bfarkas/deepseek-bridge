"""Private local credentials. No shell evaluation or credential-bearing command arguments."""

import json
import os
import platform
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import BridgeError

if TYPE_CHECKING:
    from .settings import Settings


KEYCHAIN_SERVICE = "deepseek-bridge"


def file_key(path: Path) -> str | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BridgeError(
            "permission_boundary", "Cannot safely open private credential file"
        ) from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_size > 16384
        ):
            raise BridgeError(
                "permission_boundary", "Credential file must be an owner-only regular file"
            )
        raw = os.read(fd, 16385)
    finally:
        os.close(fd)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise BridgeError("invalid_request", "Private credential file is not valid JSON") from exc
    if not isinstance(data, dict) or set(data) != {"DEEPSEEK_API_KEY"}:
        raise BridgeError("invalid_request", "Credential file must contain only DEEPSEEK_API_KEY")
    key = data["DEEPSEEK_API_KEY"]
    if not isinstance(key, str) or any(c in key for c in "\r\n\x00"):
        raise BridgeError("invalid_request", "Invalid private credential value")
    return key.strip() or None


def keychain_key() -> str | None:
    if platform.system() != "Darwin":
        return None
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                "DEEPSEEK_API_KEY",
                "-w",
            ],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    value = result.stdout.decode().strip()
    if any(c in value for c in "\r\n\x00"):
        raise BridgeError("invalid_request", "Invalid DeepSeek Keychain credential")
    return value or None


def get_api_key(settings: "Settings") -> str | None:
    # Read at request time: filling the private file does not require restarting the runner.
    return (
        os.environ.get(settings.deepseek.api_key_env)
        or file_key(settings.credentials_file.expanduser())
        or keychain_key()
    )
