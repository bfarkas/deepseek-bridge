import subprocess
import sys
from pathlib import Path

import anthropic
import httpx
import pytest

from deepseek_bridge.accounting import account
from deepseek_bridge.errors import BridgeError
from deepseek_bridge.processes import environment, identity, owns, run, stop_group
from deepseek_bridge.provider import DeepSeekProvider
from deepseek_bridge.settings import Settings


def test_sdk_transport_offline_timeout_and_429(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-only")
    original = anthropic.Anthropic
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        assert request.headers["x-api-key"] == "fixture-only"
        assert request.url.host == "api.deepseek.com"
        if count < 3:
            return httpx.Response(
                429, json={"error": {"type": "rate_limit_error", "message": "fixture"}}
            )
        return httpx.Response(
            200,
            json={
                "id": "offline",
                "type": "message",
                "role": "assistant",
                "model": "deepseek-flash",
                "content": [{"type": "text", "text": "fixture"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        )

    monkeypatch.setattr(
        anthropic,
        "Anthropic",
        lambda **kwargs: original(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )
    monkeypatch.setattr("deepseek_bridge.provider.time.sleep", lambda _: None)
    provider = DeepSeekProvider(settings)
    result = provider.complete(
        model="deepseek-flash", messages=[], system="test", max_tokens=10, timeout=10
    )
    assert result["content"][0]["text"] == "fixture"
    assert count == 3

    def timeout(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("sensitive provider details", request=request)

    monkeypatch.setattr(
        anthropic,
        "Anthropic",
        lambda **kwargs: original(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(timeout))
        ),
    )
    with pytest.raises(BridgeError) as caught:
        provider.complete(
            model="deepseek-flash", messages=[], system="test", max_tokens=10, timeout=10
        )
    assert caught.value.code == "provider_timeout"
    assert "sensitive" not in str(caught.value)
    assert count == 4  # no retry of uncertain charge


def test_unsupported_effort_before_network(settings: Settings) -> None:
    with pytest.raises(BridgeError) as caught:
        DeepSeekProvider(settings).complete(
            model="deepseek-flash",
            messages=[],
            system="test",
            max_tokens=10,
            timeout=1,
            effort="max",
        )
    assert caught.value.code == "unsupported_capability"


def test_accounting_maps_provider_usage() -> None:
    usage = account(
        {
            "id": "request-1",
            "model": "deepseek-flash",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 0,
            },
        }
    )
    assert (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens) == (100, 50, 200)
    assert usage.provider_request_id == "request-1"
    assert account({}).input_tokens is None


def test_env_filter_and_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "never-forward")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/private/socket")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "never-forward")
    env = environment()
    assert not any(key in env for key in ["ANTHROPIC_API_KEY", "SSH_AUTH_SOCK", "DEEPSEEK_API_KEY"])
    result = run([sys.executable, "-c", "import os;print(os.getcwd())"], tmp_path, env, 5)
    assert result["exit_code"] == 0
    assert Path(result["output"].decode().strip()).resolve() == tmp_path.resolve()
    with pytest.raises(BridgeError):
        environment({"ANTHROPIC_API_KEY": "no"})


@pytest.mark.parametrize("mode", ["timeout", "cancel", "output"])
def test_process_limits(tmp_path: Path, mode: str) -> None:
    script = "import time;time.sleep(10)"
    if mode == "output":
        script = "import sys;sys.stdout.write('x'*1000000);sys.stdout.flush()"
    result = run(
        [sys.executable, "-c", script],
        tmp_path,
        environment(),
        0.1 if mode == "timeout" else 5,
        max_bytes=1000,
        cancelled=lambda: mode == "cancel",
    )
    assert (
        result["reason"]
        == {"timeout": "timed_out", "cancel": "cancelled", "output": "output_limit"}[mode]
    )
    assert len(result["output"]) <= 1000
    assert not owns(result["process"])


def test_pid_reuse_guard(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(10)"], start_new_session=True
    )
    try:
        record = identity(proc, tmp_path)
        record["created"] -= 100
        assert not owns(record)
        assert not stop_group(record)
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


def test_missing_executable(tmp_path: Path) -> None:
    with pytest.raises(BridgeError) as caught:
        run(["/does/not/exist"], tmp_path, environment(), 2)
    assert caught.value.code == "worker_unavailable"


def test_token_event_budget_stops_execution(tmp_path: Path) -> None:
    from deepseek_bridge.opencode import within_token_budget

    script = (
        'import time; print(\'{"type":"step_finish","part":{"type":"step-finish",'
        '"tokens":{"output":100}}}\', flush=True); time.sleep(10)'
    )
    result = run(
        [sys.executable, "-c", script],
        tmp_path,
        environment(),
        2,
        within_budget=lambda raw: within_token_budget(raw, 50),
    )
    assert result["reason"] == "token_limit"
    assert not owns(result["process"])
