import copy
from pathlib import Path
from typing import Any

import pytest

from deepseek_bridge.settings import Repository, Settings, Storage
from deepseek_bridge.worktrees import git


class FakeProvider:
    def __init__(self, text: str = "Analysis", blocks: list[dict[str, Any]] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.response: dict[str, Any] = {
            "id": "fixture-response",
            "model": "deepseek-flash",
            "stop_reason": "end_turn",
            "content": blocks or [{"type": "text", "text": text}],
            "usage": {
                "input_tokens": 12,
                "output_tokens": 7,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(copy.deepcopy(kwargs))
        return copy.deepcopy(self.response)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "user.email", "fixture@example.invalid")
    (path / "code.py").write_text("value = 1\n")
    (path / "delete.txt").write_text("to delete\n")
    git(path, "add", ".")
    git(path, "commit", "-m", "Fixture base")
    return path


@pytest.fixture
def settings(tmp_path: Path, repo: Path) -> Settings:
    return Settings(
        credentials_file=tmp_path / "credentials.json",
        storage=Storage(state_dir=tmp_path / "state"),
        repositories={
            "fixture": Repository(path=repo, verification_profile="tests"),
        },
    )


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture(autouse=True)
def no_host_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deepseek_bridge.credentials.keychain_key", lambda: None)
