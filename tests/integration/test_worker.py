import json
import os
import sys
from pathlib import Path

import pytest

from deepseek_bridge.contracts import CodingRequest
from deepseek_bridge.errors import BridgeError
from deepseek_bridge.opencode import parse_events, validate_effective
from deepseek_bridge.runner import Runner
from deepseek_bridge.service import Service
from deepseek_bridge.settings import Profile, Settings
from deepseek_bridge.worktrees import base_sha, create, git, patch, snapshot

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def worker_settings(settings: Settings, tmp_path: Path) -> Settings:
    executable = tmp_path / "fixture-opencode"
    # This is an offline harness, not compatibility evidence for the real OpenCode binary.
    executable.write_text(
        "#!"
        + sys.executable
        + f"\nFIXTURE = {str(FIXTURES / 'opencode-v2.2.5-config.json')!r}\n"
        + """
import json, os, pathlib, sys
if sys.argv[1:] == ["--version"]:
    print("fixture-1")
elif sys.argv[1:3] == ["debug", "config"]:
    config = pathlib.Path(os.environ["OPENCODE_CONFIG"])
    print(pathlib.Path(FIXTURE).read_text().replace("/fixture/private", str(config.parent)))
else:
    assert not os.environ.get("ANTHROPIC_API_KEY")
    assert not os.environ.get("SSH_AUTH_SOCK")
    assert os.environ["DEEPSEEK_API_KEY"] == "fixture-worker-key"
    pathlib.Path("code.py").write_text("value = 2\\n")
    pathlib.Path("test_new.py").write_text(
        "import runpy\\ndef test_value():\\n"
        "    assert runpy.run_path('code.py')['value'] == 2\\n")
    pathlib.Path("binary.bin").write_bytes(bytes([0,1,2,3,255]))
    pathlib.Path("delete.txt").unlink()
    print(json.dumps({"type":"text","modelID":"fixture-model","part":{"type":"text","text":"done"}}))
    print(json.dumps({"type":"step_finish","part":{"type":"step-finish","tokens":{"input":10,"output":5,"cache":{"read":0}}}}))
"""
    )
    executable.chmod(0o700)
    settings.worker.enabled = True
    settings.worker.compatibility_verified = True
    settings.worker.executable = str(executable)
    settings.worker.expected_version = "fixture-1"
    settings.worker.worktree_root = tmp_path / "trees"
    settings.profiles["tests"] = Profile(
        commands=[[sys.executable, "-I", "-B", "-m", "pytest", "-q"]]
    )
    return settings


def test_complete_worker_patch_and_verification(
    worker_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = worker_settings
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-worker-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-forward")
    monkeypatch.setenv("SSH_AUTH_SOCK", "do-not-forward")
    repo = settings.repository("fixture").path
    (repo / "code.py").write_text("uncommitted user changes\n")
    (repo / "notes.txt").write_text("untracked user file\n")
    before = snapshot(repo)
    service = Service(settings)
    request = CodingRequest(
        repository="fixture",
        task="Change value and add tests",
        acceptance_criteria=["Value is 2 and tests pass"],
        verification_profile="tests",
        client_request_id="test-job",
    )
    started = service.start_job(request)
    assert service.start_job(request)["job_id"] == started["job_id"]
    assert started["state"] == "queued"
    Runner(service).run(once=True)
    result = service.result(started["job_id"])
    assert result["state"] == "completed", result
    report = result["report"]
    assert report["verification"]["status"] == "passed"
    assert report["original_checkout_unchanged"]
    assert snapshot(repo) == before
    assert set(report["changed_files"]) == {"code.py", "test_new.py", "binary.bin", "delete.txt"}
    assert report["usage"]["output_tokens"] == 5
    assert report["model"] == "fixture-model"
    artifact = next(a for a in result["artifacts"] if a["name"] == "changes.patch")
    raw = service.artifacts.read(started["job_id"], artifact["id"])
    assert b"GIT binary patch" in raw
    assert b"new file mode" in raw and b"deleted file mode" in raw
    # Git can apply the produced binary/new/deleted patch to another clean worktree.
    clean = create(repo, settings.worker.worktree_root, "a" * 32, report["base_sha"])
    path = service.artifacts.directory(started["job_id"]) / "changes.patch"
    git(clean, "apply", "--check", str(path))
    assert report["verification"]["runs"][0]["test_count"] is None
    assert report["verification"]["runs"][0]["exit_code"] == 0
    assert "test_new.py" in report["changed_files"]  # modified tests are visible, not hidden


def test_failed_verification_still_delivers_patch(
    worker_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-worker-key")
    worker_settings.profiles["tests"] = Profile(
        commands=[[sys.executable, "-c", "raise SystemExit(7)"]]
    )
    service = Service(worker_settings)
    job = service.start_job(
        CodingRequest(
            repository="fixture",
            task="Fixture",
            acceptance_criteria=["test"],
            verification_profile="tests",
        )
    )
    Runner(service).run(once=True)
    result = service.result(job["job_id"])
    assert result["state"] == "completed", result
    assert result["report"]["verification"]["status"] == "failed"
    assert result["report"]["verification"]["runs"][0]["exit_code"] == 7
    assert any(a["name"] == "changes.patch" for a in result["artifacts"])


def test_config_gate_and_unapproved_extensions(
    worker_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-worker-key")
    settings = worker_settings
    (settings.repository("fixture").path / "opencode.json").write_text('{"plugin":["bad"]}')
    git(settings.repository("fixture").path, "add", "opencode.json")
    git(settings.repository("fixture").path, "commit", "-m", "Unapproved config fixture")
    service = Service(settings)
    job = service.start_job(
        CodingRequest(
            repository="fixture",
            task="Fixture",
            acceptance_criteria=["test"],
            verification_profile="tests",
        )
    )
    Runner(service).run(once=True)
    result = service.result(job["job_id"])
    assert result["state"] == "failed"
    assert result["error"]["code"] == "permission_boundary"
    assert not (Path(service.db.get(job["job_id"])["worktree"]) / "test_new.py").exists()


def test_pinned_version_and_base_collisions(worker_settings: Settings) -> None:
    settings = worker_settings
    settings.worker.expected_version = "wrong"
    service = Service(settings)
    with pytest.raises(BridgeError):
        service.start_job(
            CodingRequest(
                repository="fixture",
                task="Fixture",
                acceptance_criteria=["test"],
                verification_profile="tests",
            )
        )
    repo = settings.repository("fixture").path
    sha = base_sha(repo, "HEAD")
    create(repo, settings.worker.worktree_root, "b" * 32, sha)
    with pytest.raises(BridgeError):
        create(repo, settings.worker.worktree_root, "b" * 32, sha)
    with pytest.raises(BridgeError):
        base_sha(repo, "does-not-exist")


def test_symlink_patch_rejected(worker_settings: Settings) -> None:
    settings = worker_settings
    repo = settings.repository("fixture").path
    sha = base_sha(repo, "HEAD")
    tree = create(repo, settings.worker.worktree_root, "c" * 32, sha)
    (tree / "escape").symlink_to("/tmp")
    private = tree.parent / "private"
    private.mkdir()
    with pytest.raises(BridgeError):
        patch(tree, sha, private)


def test_effective_config_and_event_fixtures() -> None:
    raw = (FIXTURES / "opencode-events.jsonl").read_bytes()
    assert parse_events(raw)["output_tokens"] == 5
    for raw in [b"not-json", b"{}", b'{"type":"error"}', b""]:
        with pytest.raises(BridgeError):
            parse_events(raw)
    for raw in [b"bad", b'{"plugin":["unapproved"]}', b"[]"]:
        with pytest.raises(BridgeError):
            validate_effective(raw, Path("/fixture/private/opencode.json"))


def test_runner_survives_stdio_mcp_disconnect(
    worker_settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio
    import subprocess

    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    settings = worker_settings
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-worker-key")
    service = Service(settings)
    job = service.start_job(
        CodingRequest(
            repository="fixture",
            task="Fixture",
            acceptance_criteria=["tests pass"],
            verification_profile="tests",
        )
    )
    config = tmp_path / "runner.toml"
    config.write_text(
        "[storage]\nstate_dir=" + json.dumps(str(settings.storage.state_dir)) + "\n"
        '[worker]\nenabled=true\ncompatibility_verified=true\nexpected_version="fixture-1"\n'
        "executable=" + json.dumps(settings.worker.executable) + "\n"
        "worktree_root=" + json.dumps(str(settings.worker.worktree_root)) + "\n"
        '[repositories.fixture]\nverification_profile="tests"\npath='
        + json.dumps(str(settings.repository("fixture").path))
        + "\n"
        "[profiles.tests]\ncommands=" + json.dumps(settings.profiles["tests"].commands) + "\n"
    )
    config.chmod(0o600)
    command = [sys.executable, "-m", "deepseek_bridge", "--config", str(config)]
    processes = []

    async def exercise() -> None:
        transport = StdioTransport(
            command=sys.executable, args=command[1:] + ["serve"], env=os.environ.copy()
        )
        async with Client(transport) as client:
            assert len(await client.list_tools()) == 7
            processes.append(
                subprocess.Popen(
                    command + ["runner", "--once"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
            )
        # Exiting the client closes its MCP process while the separate runner owns the queue.

    asyncio.run(exercise())
    try:
        stdout, stderr = processes[0].communicate(timeout=15)
        assert processes[0].returncode == 0, stderr
        assert stdout == b""
        assert service.status(job["job_id"])["state"] == "completed", service.result(job["job_id"])
    finally:
        if processes[0].poll() is None:
            processes[0].kill()
            processes[0].wait()


def test_explicit_retry_links_attempt_and_keeps_base(worker_settings: Settings) -> None:
    from deepseek_bridge.cli import dispatch, parser

    service = Service(worker_settings)
    original = service.start_job(
        CodingRequest(
            repository="fixture",
            task="Fixture",
            acceptance_criteria=["tests"],
            verification_profile="tests",
            client_request_id="original",
        )
    )
    service.db.cancel(original["job_id"])
    # Retry is a new attempt; advancing HEAD does not replace the original base.
    repo = worker_settings.repository("fixture").path
    (repo / "advanced.txt").write_text("new head")
    git(repo, "add", "advanced.txt")
    git(repo, "commit", "-m", "Advance main")
    args = parser().parse_args(["jobs", "retry", original["job_id"]])
    retried = dispatch(args, service)
    old, new = service.db.get(original["job_id"]), service.db.get(retried["job_id"])
    assert new["id"] != old["id"]
    assert new["request"]["retry_of"] == old["id"]
    assert new["request"]["attempt"] == 2
    assert new["request"]["base_sha"] == old["request"]["base_sha"]


def test_real_v2_configuration_fixture() -> None:
    raw = (FIXTURES / "opencode-v2.2.5-config.json").read_bytes()
    path = Path("/fixture/private/opencode.json")
    validate_effective(raw, path)
    data = json.loads(raw)
    data[1]["info"]["permissions"][0]["effect"] = "allow"
    with pytest.raises(BridgeError):
        validate_effective(json.dumps(data).encode(), path)
    with pytest.raises(BridgeError):
        validate_effective(raw, Path("/another/config.json"))


def test_real_v2_native_edit_events() -> None:
    raw = (FIXTURES / "opencode-v2.2.5-events.jsonl").read_bytes()
    usage = parse_events(raw)
    assert usage["model"] is None  # Installed v2 does not report a model ID in these events.
    assert usage["input_tokens"] == 20
    assert usage["output_tokens"] == 10
    assert usage["cached_input_tokens"] == 0
    events = [json.loads(line) for line in raw.splitlines()]
    edit = next(event for event in events if event["type"] == "tool_use")
    assert edit["part"]["tool"] == "write"
    assert edit["part"]["state"]["status"] == "completed"
