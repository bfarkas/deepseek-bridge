import json
import time
from pathlib import Path

import pytest
from conftest import FakeProvider

from deepseek_bridge.contracts import Handoff
from deepseek_bridge.errors import BridgeError
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


def test_approved_research_runs(scoped: tuple[Settings, Handoff]) -> None:
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
    job = service.research.enqueue(handoff, "session-1")
    assert job["state"] == "pending_approval"
    assert not fake.calls
    service.research.decide(job["id"], job["request_hash"], True)
    Runner(Service(settings, fake)).run(once=True)
    assert service.status(job["id"])["state"] == "completed"
    assert len(fake.calls) == 1
    assert "tools" not in fake.calls[0]
    assert service.result(job["id"])["report"]["hypotheses"] == ["possible cause"]


def test_no_calls_until_owner_approval(scoped: tuple[Settings, Handoff]) -> None:
    settings, handoff = scoped
    fake = FakeProvider()
    service = Service(settings, fake)
    job = service.research.enqueue(handoff, "session-1")
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


def test_boundaries_never_enqueue(scoped: tuple[Settings, Handoff]) -> None:
    settings, handoff = scoped
    fake = FakeProvider()
    service = Service(settings, fake)
    for boundary in ["permission_denied", "safety_boundary"]:
        handoff.blocker_type = boundary
        with pytest.raises(BridgeError):
            service.research.enqueue(handoff, "session-1")
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


def test_rejected_proposal(scoped: tuple[Settings, Handoff]) -> None:
    settings, handoff = scoped
    service = Service(settings, FakeProvider())
    job = service.research.enqueue(handoff, "session-1")
    service.research.decide(job["id"], job["request_hash"], False)
    assert service.db.get(job["id"])["state"] == "rejected"


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
        service.research.enqueue(handoff, "session-1")
    assert not fake.calls
