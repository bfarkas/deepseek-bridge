import json
import os
from pathlib import Path

import pytest
from conftest import FakeProvider
from pydantic import ValidationError

from deepseek_bridge.context import collect
from deepseek_bridge.contracts import Ask, Context
from deepseek_bridge.errors import BridgeError
from deepseek_bridge.service import Service
from deepseek_bridge.settings import Settings


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/etc/passwd",
        ".env",
        "dir/.env.local",
        ".git/config",
        "id_rsa",
        ".aws/credentials",
        "private.key",
    ],
)
def test_forbidden_paths(settings: Settings, name: str, fake: FakeProvider) -> None:
    service = Service(settings, fake)
    with pytest.raises(BridgeError):
        service.ask(Ask(task="Read", context=Context(repository="fixture", files=[name])))
    assert not fake.calls


def test_symlink_directory_and_fifo(settings: Settings, tmp_path: Path) -> None:
    repo = settings.repository("fixture").path
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "code.py").write_text("private")
    (repo / "linked").symlink_to(outside, target_is_directory=True)
    (repo / "alias.py").symlink_to(repo / "code.py")
    os.mkfifo(repo / "pipe")
    for name in ["linked/code.py", "alias.py", "pipe"]:
        with pytest.raises(BridgeError):
            collect(settings, Context(repository="fixture", files=[name]))


@pytest.mark.parametrize(
    "text",
    ["api_key=abcdefgh12345678", "\0binary", "sk-" + "a" * 24, "-----BEGIN RSA PRIVATE KEY-----"],
)
def test_inline_secrets(settings: Settings, text: str) -> None:
    for context in [Context(text=text), Context(diff=text)]:
        with pytest.raises(BridgeError):
            collect(settings, context)


def test_inline_diff_path(settings: Settings) -> None:
    with pytest.raises(BridgeError):
        collect(settings, Context(diff="--- a/.env\n+++ b/.env\n+hello"))


def test_explicit_selection_limits_and_no_edits(settings: Settings, fake: FakeProvider) -> None:
    repo = settings.repository("fixture").path
    before = (repo / "code.py").read_bytes()
    service = Service(settings, fake)
    result = service.ask(
        Ask(task="Explain", context=Context(repository="fixture", files=["code.py"]))
    )
    assert result["status"] == "completed"
    assert result["usage"]["input_tokens"] == 12
    assert "to delete" not in json.dumps(fake.calls)
    assert (repo / "code.py").read_bytes() == before
    settings.consultant.max_input_bytes = 10
    with pytest.raises(BridgeError):
        service.ask(Ask(task="Explain", context=Context(text="a" * 20)))


def test_unknown_version_and_fields() -> None:
    for raw in [{"task": "x", "schema_version": "2.0"}, {"task": "x", "authorized": True}]:
        with pytest.raises(ValidationError):
            Ask.model_validate(raw)


def test_continuation_preserves_blocks_and_revalidates(settings: Settings) -> None:
    blocks = [
        {"type": "thinking", "thinking": "analysis", "signature": "fixture-signature"},
        {"type": "text", "text": "Analysis"},
    ]
    fake = FakeProvider(blocks=blocks)
    service = Service(settings, fake)
    first = service.ask(
        Ask(task="Explain", context=Context(repository="fixture", files=["code.py"]))
    )
    cid = first["data"]["consultation_id"]
    Service(settings, fake).ask(Ask(task="Continue", consultation_id=cid))
    assert fake.calls[-1]["messages"][1]["content"] == blocks
    settings.repositories.clear()
    with pytest.raises(BridgeError):
        service.ask(Ask(task="Again", consultation_id=cid))
    assert len(fake.calls) == 2


def test_malformed_review_and_unknown_usage(settings: Settings, fake: FakeProvider) -> None:
    fake.response["content"][0]["text"] = "not JSON"
    fake.response.pop("usage")
    service = Service(settings, fake)
    result = service.review(Ask(task="Review", context=Context(text="value = 2")))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "parse_error"
    assert result["data"]["text"] == "not JSON"
    assert result["usage"]["input_tokens"] is None
    assert result["usage"]["cost_usd_estimate"] is None


def test_model_cannot_claim_verification(settings: Settings) -> None:
    fake = FakeProvider(
        json.dumps(
            {
                "summary": "Review",
                "findings": [
                    {
                        "severity": "high",
                        "location": "code.py",
                        "rationale": "Potential issue",
                        "recommendation": "Inspect",
                        "evidence": "verified",
                    }
                ],
            }
        )
    )
    result = Service(settings, fake).review(Ask(task="Review", context=Context(text="code")))
    assert result["data"]["findings"][0]["evidence"] == "model_inference"


def test_credential_not_in_output_or_outbound(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.deepseek.api_key_env = "FIXTURE_PROVIDER_KEY"
    key = "fixture-provider-credential-value"
    monkeypatch.setenv(settings.deepseek.api_key_env, key)
    fake = FakeProvider(key)
    service = Service(settings, fake)
    with pytest.raises(BridgeError):
        service.ask(Ask(task=key))
    with pytest.raises(BridgeError):
        service.ask(Ask(task="Explain", context=Context(text=key)))
    assert not fake.calls
    assert key not in json.dumps(service.ask(Ask(task="Explain")))


def test_research_alias_requires_policy(settings: Settings, fake: FakeProvider) -> None:
    with pytest.raises(BridgeError):
        Service(settings, fake).ask(Ask(task="Research", model="research"))
    assert not fake.calls
