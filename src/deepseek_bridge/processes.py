"""POSIX process groups; start-time checks guard against reused process IDs."""

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil

from .errors import BridgeError


def identity(process: subprocess.Popen[bytes], cwd: Path) -> dict[str, Any]:
    return {
        "pid": process.pid,
        "created": psutil.Process(process.pid).create_time(),
        "pgid": os.getpgid(process.pid),
        "cwd": str(cwd),
        "uid": os.getuid(),
    }


def owns(record: dict[str, Any]) -> bool:
    try:
        proc = psutil.Process(record["pid"])
        return (
            abs(proc.create_time() - record["created"]) < 0.001
            and proc.uids().real == record["uid"] == os.getuid()
            and os.getpgid(proc.pid) == record["pgid"] == proc.pid
        )
    except (psutil.Error, ProcessLookupError, KeyError):
        return False


def stop_group(record: dict[str, Any], grace: float = 2) -> bool:
    if not owns(record):
        return False
    try:
        os.killpg(record["pgid"], signal.SIGTERM)
        deadline = time.monotonic() + grace
        while (
            owns(record)
            and time.monotonic() < deadline
            and psutil.Process(record["pid"]).status() != psutil.STATUS_ZOMBIE
        ):
            time.sleep(0.05)
        # pgid was verified before TERM; do not signal again if leader identity changed.
        if owns(record):
            os.killpg(record["pgid"], signal.SIGKILL)
        return True
    except (ProcessLookupError, psutil.NoSuchProcess):
        return True


def run(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    max_bytes: int = 2000000,
    cancelled: Callable[[], bool] = lambda: False,
    record: Callable[[dict[str, Any] | None], None] = lambda _: None,
    within_budget: Callable[[bytes], bool] = lambda _: True,
) -> dict[str, Any]:
    if timeout <= 0:
        raise BridgeError("timed_out", "Execution deadline exceeded")
    start = time.time()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        raise BridgeError("worker_unavailable", "Cannot start configured executable") from exc
    assert proc.stdout is not None
    ident = identity(proc, cwd)
    output = bytearray()
    reason = None
    exited = None
    try:
        record(ident)
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            os.set_blocking(proc.stdout.fileno(), False)
            while True:
                if cancelled():
                    reason = "cancelled"
                    break
                if time.time() - start > timeout:
                    reason = "timed_out"
                    break
                for key, _ in selector.select(timeout=0.05):
                    chunk = os.read(key.fd, 65536)
                    if chunk:
                        output.extend(chunk[: max_bytes + 1 - len(output)])
                    else:
                        selector.unregister(key.fd)
                if not within_budget(bytes(output)):
                    reason = "token_limit"
                    break
                if len(output) > max_bytes:
                    reason = "output_limit"
                    del output[max_bytes:]
                    break
                if psutil.Process(proc.pid).status() == psutil.STATUS_ZOMBIE:
                    exited = exited or time.time()
                    # A background child can hold the pipe open long after the command is done.
                    if not selector.get_map() or time.time() - exited > 1:
                        break
        if reason:
            stop_group(ident)
        # Terminate any remaining members of the verified, just-created process group.
        # This group cannot be reused while our unreaped leader exists.
        try:
            if owns(ident):
                os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)
    finally:
        if proc.returncode is None:
            stop_group(ident, grace=0)
            proc.wait(timeout=5)
        proc.stdout.close()
        record(None)
    return {
        "argv": argv,
        "cwd": str(cwd),
        "started": start,
        "ended": time.time(),
        "exit_code": proc.returncode,
        "reason": reason,
        "output": bytes(output),
        "process": ident,
    }


def environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    result = {
        key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR") if key in os.environ
    }
    result.setdefault("PATH", os.defpath)
    # Host profiles are trusted owner configuration, but cannot inject agent credentials/sockets.
    for key, value in (extra or {}).items():
        if key.startswith(("ANTHROPIC_", "OPENAI_", "DEEPSEEK_", "OPENCODE_", "GIT_")) or key in {
            "SSH_AUTH_SOCK",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
        }:
            raise BridgeError(
                "permission_boundary", "Credential/agent variables forbidden in profiles"
            )
        result[key] = value
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["GIT_TERMINAL_PROMPT"] = "0"
    result["GIT_CONFIG_NOSYSTEM"] = "1"
    result["GIT_CONFIG_GLOBAL"] = os.devnull
    return result
