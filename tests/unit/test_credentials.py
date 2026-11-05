import json
import subprocess
from pathlib import Path

import pytest

from deepseek_bridge.credentials import file_key, get_api_key, keychain_key
from deepseek_bridge.errors import BridgeError
from deepseek_bridge.settings import Settings


def test_private_file_reload_and_environment_precedence(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = settings.credentials_file
    path.write_text(json.dumps({"DEEPSEEK_API_KEY": ""}))
    path.chmod(0o600)
    assert get_api_key(settings) is None
    path.write_text(json.dumps({"DEEPSEEK_API_KEY": "fixture-private-key"}))
    assert get_api_key(settings) == "fixture-private-key"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-env-key")
    assert get_api_key(settings) == "fixture-env-key"


@pytest.mark.parametrize("case", ["permissions", "symlink", "malformed", "extra", "directory"])
def test_unsafe_credentials_rejected(settings: Settings, tmp_path: Path, case: str) -> None:
    path = settings.credentials_file
    path.write_text(json.dumps({"DEEPSEEK_API_KEY": "fixture-private-key"}))
    path.chmod(0o600)
    if case == "permissions":
        path.chmod(0o644)
    elif case == "symlink":
        target = tmp_path / "actual-credentials.json"
        path.rename(target)
        path.symlink_to(target)
    elif case == "malformed":
        path.write_text("bad JSON")
    elif case == "extra":
        path.write_text('{"DEEPSEEK_API_KEY":"fixture", "shell":"do not execute"}')
    else:
        path.unlink()
        path.mkdir()
    with pytest.raises(BridgeError):
        file_key(path)


def test_keychain_never_passes_secret_in_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr("deepseek_bridge.credentials.platform.system", lambda: "Darwin")

    def response(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"fixture-keychain-secret\n", b"")

    monkeypatch.setattr("deepseek_bridge.credentials.subprocess.run", response)
    assert keychain_key() == "fixture-keychain-secret"
    assert calls == [
        [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            "deepseek-bridge",
            "-a",
            "DEEPSEEK_API_KEY",
            "-w",
        ]
    ]


def test_file_secret_blocked_from_outbound_and_redacted(settings: Settings) -> None:
    from conftest import FakeProvider

    from deepseek_bridge.contracts import Ask, Context
    from deepseek_bridge.service import Service

    key = "fixture-private-credential-without-standard-prefix"
    settings.credentials_file.write_text(json.dumps({"DEEPSEEK_API_KEY": key}))
    settings.credentials_file.chmod(0o600)
    service = Service(settings, FakeProvider(key))
    with pytest.raises(BridgeError):
        service.ask(Ask(task="Explain", context=Context(text=key)))
    assert key not in json.dumps(service.ask(Ask(task="Explain")))
