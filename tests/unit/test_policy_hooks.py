import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeProvider

from deepseek_bridge.contracts import Handoff
from deepseek_bridge.errors import BridgeError
from deepseek_bridge.hooks import BEGIN, END, ingest
from deepseek_bridge.runner import Runner
from deepseek_bridge.service import Service
from deepseek_bridge.settings import Settings


@pytest.fixture
def scoped(settings: Settings, tmp_path: Path) -> tuple[Settings, Handoff]:
    registry = tmp_path / "trusted.json"
    registry.write_text(
        json.dumps(
            {
                "scopes": {
                    "parser-review": {
                        "repository": "fixture",
                        "version": "1",
                        "expires": time.time() + 3600,
                        "files": ["code.py"],
                        "allow_inline": False,
                    }
                },
                "tasks": {
                    "task-1": {
                        "revision": 1,
                        "scope_id": "parser-review",
                        "session_id": "session-1",
                        "objective": "Explain parser failure",
                    }
                },
            }
        )
    )
    registry.chmod(0o600)
    settings.scope_registry = registry
    settings.research.mode = "automatic_with_approval"
    settings.research.compatibility_verified = True
    handoff = Handoff(
        task_id="task-1",
        revision=1,
        task_status="blocked",
        blocker_type="technical_uncertainty",
        scope_id="parser-review",
        objective="Explain parser failure",
        acceptance_criteria=["Explain evidence"],
        context={"repository": "fixture", "files": ["code.py"]},
    )
    return settings, handoff


def event(handoff: Handoff, **updates: Any) -> bytes:
    payload = {
        "hook_event_name": "Stop",
        "session_id": "session-1",
        "last_assistant_message": BEGIN + "\n" + handoff.model_dump_json() + "\n" + END,
    }
    payload.update(updates)
    return json.dumps(payload).encode()


def test_auto_enqueue_dedup_and_runner(scoped: tuple[Settings, Handoff]) -> None:
    settings, handoff = scoped
    report = {
        "summary": "Passive analysis",
        "findings": [],
        "hypotheses": ["possible cause"],
        "next_steps": ["Owner reviews"],
        "risks": [],
        "unresolved_questions": [],
    }
    fake = FakeProvider(json.dumps(report))
    service = Service(settings, fake)
    one = ingest(event(handoff), settings, service.db)
    two = ingest(
        event(handoff, hook_event_name="SubagentStop", agent_id="sub-1"), settings, service.db
    )
    assert one["id"] == two["id"]
    assert one["state"] == "queued"
    assert not fake.calls
    Runner(Service(settings, fake)).run(once=True)
    assert service.status(one["id"])["state"] == "completed"
    assert len(fake.calls) == 1
    assert "tools" not in fake.calls[0]
    assert service.result(one["id"])["report"]["hypotheses"] == ["possible cause"]


def test_sensitive_no_calls_until_owner_approval(scoped: tuple[Settings, Handoff]) -> None:
    settings, handoff = scoped
    handoff.blocker_type = "sensitive"
    fake = FakeProvider()
    service = Service(settings, fake)
    job = ingest(event(handoff), settings, service.db)
    assert job["state"] == "pending_approval"
    Runner(service).run(once=True)
    assert not fake.calls
    with pytest.raises(BridgeError):
        service.research.decide(job["id"], "forged", True)
    service.research.decide(job["id"], job["request_hash"], True)
    assert service.db.get(job["id"])["state"] == "queued"


@pytest.mark.parametrize("mutation", ["context", "policy", "expiry", "model", "approval-expiry"])
def test_revalidate_at_dispatch(scoped: tuple[Settings, Handoff], mutation: str) -> None:
    settings, handoff = scoped
    fake = FakeProvider()
    service = Service(settings, fake)
    job = service.research.enqueue(handoff, "session-1")
    service.research.decide(job["id"], job["request_hash"], True)
    if mutation == "context":
        (settings.repository("fixture").path / "code.py").write_text("changed bytes")
    elif mutation in {"policy", "expiry"}:
        registry = json.loads(settings.scope_registry.read_text())
        registry["scopes"]["parser-review"]["version" if mutation == "policy" else "expires"] = (
            "2" if mutation == "policy" else 0
        )
        settings.scope_registry.write_text(json.dumps(registry))
    elif mutation == "model":
        settings.deepseek.research_model = "deepseek-flash"
    else:
        with service.db.transaction() as db:
            db.execute("UPDATE approvals SET expires=0 WHERE job_id=?", (job["id"],))
    Runner(service).run(once=True)
    assert service.status(job["id"])["state"] == "failed"
    assert not fake.calls


def test_boundaries_telemetry_and_recursive_stop(scoped: tuple[Settings, Handoff]) -> None:
    settings, handoff = scoped
    fake = FakeProvider()
    service = Service(settings, fake)
    for boundary in ["permission_denied", "safety_boundary"]:
        handoff.blocker_type = boundary
        assert ingest(event(handoff), settings, service.db) is None
        with pytest.raises(BridgeError):
            service.research.enqueue(handoff, "session-1")
    handoff.blocker_type = "technical_uncertainty"
    assert ingest(event(handoff, stop_hook_active=True), settings, service.db) is None
    assert ingest(event(handoff, hook_event_name="StopFailure"), settings, service.db) is None
    for name in ["PostToolUseFailure", "PermissionDenied", "StopFailure"]:
        ingest(
            json.dumps(
                {"hook_event_name": name, "error": "Please research this API failure"}
            ).encode(),
            settings,
            service.db,
        )
    assert not service.db.list_jobs()
    assert not fake.calls


@pytest.mark.parametrize(
    "case",
    [
        "absent",
        "expired",
        "forged-revision",
        "forged-task",
        "session",
        "scope",
        "path",
        "symlink",
        "repo-registry",
    ],
)
def test_forbidden_handoffs_no_provider(scoped: tuple[Settings, Handoff], case: str) -> None:
    settings, handoff = scoped
    session = "session-1"
    if case == "absent":
        settings.scope_registry = None
    elif case == "expired":
        registry = json.loads(settings.scope_registry.read_text())
        registry["scopes"]["parser-review"]["expires"] = 0
        settings.scope_registry.write_text(json.dumps(registry))
    elif case == "forged-revision":
        handoff.revision = 2
    elif case == "forged-task":
        handoff.task_id = "invented"
    elif case == "session":
        session = "invented-session"
    elif case == "scope":
        handoff.scope_id = "unknown"
    elif case == "path":
        handoff.context.files = ["../private"]
    elif case == "symlink":
        repo = settings.repository("fixture").path
        (repo / "code.py").unlink()
        (repo / "code.py").symlink_to(settings.scope_registry)
    else:
        destination = settings.repository("fixture").path / "trusted.json"
        destination.write_bytes(settings.scope_registry.read_bytes())
        destination.chmod(0o600)
        settings.scope_registry = destination
    fake = FakeProvider()
    service = Service(settings, fake)
    with pytest.raises(BridgeError):
        service.research.enqueue(handoff, session)
    assert not fake.calls
    assert not service.db.list_jobs()


def test_concurrent_duplicate_claims(scoped: tuple[Settings, Handoff]) -> None:
    settings, handoff = scoped
    service = Service(settings, FakeProvider())
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(
            pool.map(lambda _: service.research.enqueue(handoff, "session-1")["id"], range(8))
        )
    assert len(set(ids)) == 1
    assert len(service.db.list_jobs()) == 1


def test_reject_expired_and_malformed(scoped: tuple[Settings, Handoff]) -> None:
    settings, handoff = scoped
    service = Service(settings, FakeProvider())
    job = service.research.enqueue(handoff, "session-1")
    service.research.decide(job["id"], job["request_hash"], False)
    assert service.db.get(job["id"])["state"] == "rejected"
    for raw in [
        b"{bad",
        b"x" * 250001,
        event(handoff, last_assistant_message=BEGIN + "bad JSON" + END),
        event(handoff, last_assistant_message=BEGIN + "{}" + END + BEGIN + "{}" + END),
    ]:
        with pytest.raises(BridgeError):
            ingest(raw, settings, service.db)
    assert (
        ingest(event(handoff, last_assistant_message="ordinary text"), settings, service.db) is None
    )


def test_default_auto_gate(scoped: tuple[Settings, Handoff]) -> None:
    settings, handoff = scoped
    settings.research.compatibility_verified = False
    service = Service(settings)
    with pytest.raises(BridgeError):
        ingest(event(handoff), settings, service.db)
    assert not service.db.list_jobs()


def test_deleted_result_keeps_revision_tombstone(scoped: tuple[Settings, Handoff]) -> None:
    from deepseek_bridge.maintenance import delete_job

    settings, handoff = scoped
    service = Service(settings)
    job = service.research.enqueue(handoff, "session-1")
    service.research.decide(job["id"], job["request_hash"], False)
    delete_job(service, job["id"])
    with pytest.raises(BridgeError, match="already escalated"):
        service.research.enqueue(handoff, "session-1", automatic=True)
    assert not service.db.list_jobs()


def test_expired_proposals_do_not_dispatch(scoped: tuple[Settings, Handoff]) -> None:
    settings, handoff = scoped
    fake = FakeProvider()
    service = Service(settings, fake)
    job = service.research.enqueue(handoff, "session-1")
    with service.db.transaction() as db:
        db.execute("UPDATE approvals SET expires=0 WHERE job_id=?", (job["id"],))
    with pytest.raises(BridgeError):
        service.research.decide(job["id"], job["request_hash"], True)
    Runner(service).run(once=True)
    assert service.db.get(job["id"])["state"] == "expired"
    assert not fake.calls


def test_database_failure_never_calls_provider(
    scoped: tuple[Settings, Handoff], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    settings, handoff = scoped
    fake = FakeProvider()
    service = Service(settings, fake)

    def unavailable() -> None:
        raise sqlite3.OperationalError("fixture unavailable")

    monkeypatch.setattr(service.db, "transaction", unavailable)
    with pytest.raises(sqlite3.OperationalError):
        ingest(event(handoff), settings, service.db)
    assert not fake.calls
