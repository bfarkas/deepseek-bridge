import hashlib
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from deepseek_bridge.artifacts import Artifacts
from deepseek_bridge.database import Database
from deepseek_bridge.errors import BridgeError
from deepseek_bridge.runner import Runner
from deepseek_bridge.service import Service
from deepseek_bridge.settings import Settings


def test_claim_capacity_and_exactly_once(settings: Settings) -> None:
    db = Database(settings)
    for i in range(10):
        db.enqueue("research", {"task": i}, 100)
    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(lambda i: Database(settings).claim(str(i), 3), range(8)))
    claimed = [c for c in claims if c]
    assert len(claimed) == 3
    assert len({c["id"] for c in claimed}) == 3


def test_idempotency_persistence_and_cancel_race(settings: Settings) -> None:
    db = Database(settings)
    job = db.enqueue("coding", {"task": "x"}, 100, "same")
    assert Database(settings).enqueue("coding", {"task": "x"}, 100, "same")["id"] == job["id"]
    with pytest.raises(BridgeError):
        db.enqueue("coding", {"task": "y"}, 100, "same")
    db.claim("runner", 1)
    db.transition(job["id"], "running", owner="runner")
    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(db.cancel, job["id"])
        two = executor.submit(db.transition, job["id"], "completed", result={"ok": True})
        one.result()
        two.result()
    state = db.get(job["id"])["state"]
    assert state in {"completed", "cancelling"}
    if state == "cancelling":
        db.transition(job["id"], "cancelled")
    terminal = db.get(job["id"])["state"]
    assert not db.transition(job["id"], "failed")
    assert db.cancel(job["id"])["state"] == terminal


def test_restart_interrupted_without_reexecution(settings: Settings) -> None:
    service = Service(settings)
    job = service.db.enqueue("research", {"task": "not safe to repeat"}, 100)
    service.db.claim("previous", 1)
    runner = Runner(Service(settings))
    with runner.lock():
        runner.reconcile()
    assert service.db.get(job["id"])["state"] == "interrupted"
    assert service.db.claim("new", 1) is None


def test_runner_singleton_and_stopped_diagnostics(settings: Settings) -> None:
    service = Service(settings)
    one, two = Runner(service), Runner(Service(settings))
    with one.lock(), pytest.raises(BridgeError):
        with two.lock():
            pass
    service.db.enqueue("research", {"intent": "only queued"}, 100)
    assert service.db.list_jobs()[0]["state"] == "queued"
    assert not service.doctor()["ok"]
    actions = service.doctor()["actions"]
    assert any("Start" in action for action in actions)
    assert any("credential" in action for action in actions)


def test_deadlines_and_shared_resource_claims(settings: Settings) -> None:
    db = Database(settings)
    expired = db.enqueue("research", {}, -1)
    first = db.enqueue("coding", {"resources": ["cache:shared"]}, 100)
    second = db.enqueue("coding", {"resources": ["cache:shared"]}, 100)
    assert db.claim("a", 3)["id"] == first["id"]
    assert db.claim("b", 3) is None
    assert db.get(expired["id"])["state"] == "timed_out"
    assert db.get(second["id"])["state"] == "queued"


def test_transaction_rollback_and_schema_recovery(settings: Settings) -> None:
    db = Database(settings)
    with pytest.raises(RuntimeError), db.transaction() as connection:
        connection.execute("INSERT INTO consultations VALUES('rolled back','[]',0)")
        raise RuntimeError("fixture")
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM consultations").fetchone()[0] == 0
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(BridgeError):
        Database(settings)


def test_private_atomic_artifacts_and_missing_files(settings: Settings) -> None:
    db = Database(settings)
    job = db.enqueue("coding", {}, 100)
    store = Artifacts(db)
    artifact = store.publish(job["id"], "handoff.json", b"{}", "application/json")
    assert artifact["sha256"] == hashlib.sha256(b"{}").hexdigest()
    assert store.read(job["id"], artifact["id"]) == b"{}"
    assert store.directory(job["id"]).stat().st_mode & 0o077 == 0
    assert db.path.stat().st_mode & 0o077 == 0
    with pytest.raises(BridgeError):
        store.publish(job["id"], "../escape", b"x")
    with pytest.raises(BridgeError):
        store.publish(job["id"], "handoff.json", b"changed")
    (store.directory(job["id"]) / "handoff.json").unlink()
    with pytest.raises(BridgeError, match="missing"):
        store.read(job["id"], artifact["id"])
    orphan = store.directory(job["id"]) / ".tmp-orphan"
    orphan.write_bytes(b"unfinished")
    os.utime(orphan, (0, 0))
    assert store.remove_orphans() == 1


def test_events_paginate_and_history_retention(settings: Settings) -> None:
    service = Service(settings)
    job = service.db.enqueue("research", {}, 100)
    first = service.status(job["id"])
    assert service.status(job["id"], first["cursor"])["events"] == []
    service.db.save_history("fixture", [])
    with service.db.transaction() as db:
        db.execute("UPDATE consultations SET updated=?", (time.time() - 31 * 86400,))
    with pytest.raises(BridgeError):
        service.db.history("fixture", 30)


def test_cancel_races_with_queue_claim(settings: Settings) -> None:
    db = Database(settings)
    for _ in range(20):
        job = db.enqueue("coding", {}, 100)
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancelled = pool.submit(db.cancel, job["id"])
            claimed = pool.submit(db.claim, "runner", 1)
            cancelled.result()
            claimed.result()
        assert db.get(job["id"])["state"] in {"cancelled", "cancelling"}
        if db.get(job["id"])["state"] == "cancelling":
            db.transition(job["id"], "cancelled")


def test_initial_migration_failure_rolls_back(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deepseek_bridge.database as module

    schema = module.SCHEMA
    monkeypatch.setattr(module, "SCHEMA", schema + "; INVALID SQL;")
    with pytest.raises(sqlite3.OperationalError):
        Database(settings)
    with sqlite3.connect(
        settings.storage.state_dir / settings.storage.database_filename
    ) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[
                0
            ]
            == 0
        )
    monkeypatch.setattr(module, "SCHEMA", schema)
    assert Database(settings).list_jobs() == []


def test_v1_database_upgrades_in_place(settings: Settings) -> None:
    import deepseek_bridge.database as module

    path = settings.storage.state_dir / settings.storage.database_filename
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sqlite3.connect(path) as connection:
        connection.executescript(module.SCHEMA)
        connection.execute("PRAGMA user_version=1")
        connection.execute("INSERT INTO consultations VALUES('kept','[]',0)")
    db = Database(settings)
    with db.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
        kept = connection.execute("SELECT count(*) FROM consultations").fetchone()[0]
    assert not tables & {"api_usage", "escalations", "telemetry"}
    assert "lease" not in columns
    assert kept == 1


def test_simultaneous_initialization(settings: Settings) -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        databases = list(pool.map(lambda _: Database(settings), range(4)))
    assert all(db.list_jobs() == [] for db in databases)


def test_provider_reservations_share_worker_capacity(settings: Settings) -> None:
    service = Service(settings)
    job = service.db.enqueue("coding", {}, 100)
    with service.db.reserve_api(1, 1):
        assert service.db.claim("runner", 1) is None
        with pytest.raises(BridgeError):
            with service.db.reserve_api(1, 1):
                pass
    assert service.db.claim("runner", 1)["id"] == job["id"]
    with pytest.raises(BridgeError):
        with service.db.reserve_api(1, 1):
            pass
