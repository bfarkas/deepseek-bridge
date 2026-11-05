"""Explicit user service installation; never changes Claude authentication or settings."""

import os
import platform
import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import BridgeError

NAME = "local.deepseek-bridge.runner"


def configure(config: Path, *, remove: bool = False) -> dict[str, Any]:
    executable = shutil.which("deepseek-bridge")
    if not executable:
        raise BridgeError(
            "worker_unavailable", "Install deepseek-bridge before installing its service"
        )
    argv = [executable, "--config", str(config.resolve()), "runner"]
    if platform.system() == "Darwin":
        target = Path.home() / "Library/LaunchAgents" / (NAME + ".plist")
        domain = f"gui/{os.getuid()}"
        if remove:
            subprocess.run(
                ["launchctl", "bootout", domain + "/" + NAME],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise BridgeError(
                    "invalid_request", "Runner service already exists; remove it first"
                )
            with target.open("xb") as stream:
                os.chmod(target, 0o600)
                plistlib.dump(
                    {
                        "Label": NAME,
                        "ProgramArguments": argv,
                        "RunAtLoad": True,
                        "KeepAlive": True,
                        "Umask": 0o077,
                    },
                    stream,
                )
            subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
    elif platform.system() == "Linux":
        target = Path.home() / ".config/systemd/user" / (NAME + ".service")
        if remove:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", NAME],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise BridgeError(
                    "invalid_request", "Runner service already exists; remove it first"
                )
            # systemd uses its own quoting, not shell escaping. Reject control chars/specifiers.
            if any(any(c in arg for c in '\n\r%$"\\') for arg in argv):
                raise BridgeError("invalid_request", "Unsupported character in service path")
            command = " ".join('"' + arg + '"' for arg in argv)
            with target.open("x") as stream:
                os.chmod(target, 0o600)
                stream.write(
                    "[Unit]\nDescription=DeepSeek Bridge runner\n[Service]\nType=simple\n"
                    f"ExecStart={command}\nRestart=on-failure\nUMask=0077\n"
                    "[Install]\nWantedBy=default.target\n"
                )
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        if not remove:
            subprocess.run(["systemctl", "--user", "enable", "--now", NAME], check=True)
    else:
        raise BridgeError("unsupported_capability", "Only POSIX macOS/Linux services are supported")
    return {
        "service_file": str(target),
        "removed": remove,
        "credential_note": "Provision credential privately in the service manager environment",
    }
