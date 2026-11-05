import fcntl
import json
import os
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .context import digest
from .errors import BridgeError
from .settings import Settings, private_dir

TERMINAL = {"completed", "failed", "timed_out", "interrupted", "cancelled", "rejected", "expired"}
ACTIVE = {"preparing", "running", "verifying", "cancelling"}
TRANSITIONS = {
    "pending_approval": {"queued", "rejected", "expired", "cancelled"},
    "queued": {"preparing", "cancelled", "timed_out"},
    "preparing": {"running", "cancelling", "failed", "timed_out", "interrupted"},
    "running": {"verifying", "completed", "cancelling", "failed", "timed_out", "interrupted"},
    "verifying": {"completed", "cancelling", "failed", "timed_out", "interrupted"},
    "cancelling": {"cancelled", "interrupted"},
}
SCHEMA = """
CREATE TABLE jobs (
 id TEXT PRIMARY KEY, role TEXT NOT NULL, request TEXT NOT NULL, request_hash TEXT NOT NULL,
 state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, deadline REAL NOT NULL,
 client_key TEXT UNIQUE, owner TEXT, lease REAL, result TEXT, error TEXT,
 process TEXT, worktree TEXT, review TEXT CHECK(review IN ('accepted','rejected') OR review IS NULL)
);
CREATE TABLE job_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
 state TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE consultations (id TEXT PRIMARY KEY, messages TEXT NOT NULL, updated REAL NOT NULL);
CREATE TABLE api_usage (
 id INTEGER PRIMARY KEY, job_id TEXT, consultation_id TEXT, payload TEXT NOT NULL, created REAL
);
CREATE TABLE api_reservations (
 id TEXT PRIMARY KEY, job_id TEXT, expires REAL NOT NULL
);
CREATE TABLE artifacts (
 id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
 name TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, media_type TEXT NOT NULL,
 UNIQUE(job_id,name)
);
CREATE TABLE approvals (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
 request_hash TEXT NOT NULL, scope_version TEXT NOT NULL, expires REAL NOT NULL,
 decision TEXT, actor TEXT, decided REAL
);
CREATE TABLE escalations (
 session TEXT NOT NULL, task TEXT NOT NULL, revision INTEGER NOT NULL, role TEXT NOT NULL,
 job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL, UNIQUE(task,revision,role)
);
CREATE TABLE runner (
 id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, heartbeat REAL NOT NULL
);
CREATE TABLE telemetry (id INTEGER PRIMARY KEY, event TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX jobs_queue ON jobs(state,created);
CREATE INDEX events_job ON job_events(job_id,seq);
"""


class Database:
    def __init__(self, settings: Settings):
        root = private_dir(settings.storage.state_dir)
        self.path = root / settings.storage.database_filename
        if self.path.is_symlink():
            raise BridgeError("permission_boundary", "Database cannot be a symlink")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.migration_lock(), self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            try:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version > 1:
                    raise BridgeError(
                        "invalid_request", "Database schema is newer than this package"
                    )
                if version == 0:
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            db.execute(statement)
                    db.execute("PRAGMA user_version=1")
                db.commit()
            except Exception:
                db.rollback()
                raise

    @contextmanager
    def migration_lock(self) -> Iterator[None]:
        # journal_mode switching itself can return SQLITE_BUSY before BEGIN waits.
        fd = os.open(
            self.path.parent / "schema.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        deadline = time.monotonic() + 5
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise BridgeError(
                            "worker_unavailable", "Database initialization is busy", True
                        ) from None
                    time.sleep(0.01)
            yield
        finally:
            os.close(fd)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def enqueue(
        self,
        role: str,
        request: dict[str, Any],
        timeout: int,
        client_key: str | None = None,
        state: str = "queued",
    ) -> dict[str, Any]:
        with self.transaction() as db:
            return self.insert_job(db, role, request, timeout, client_key, state)

    def insert_job(
        self,
        db: sqlite3.Connection,
        role: str,
        request: dict[str, Any],
        timeout: int,
        client_key: str | None = None,
        state: str = "queued",
    ) -> dict[str, Any]:
        hashed = digest(request)
        if client_key:
            row = db.execute("SELECT * FROM jobs WHERE client_key=?", (client_key,)).fetchone()
            if row:
                if row["request_hash"] != hashed:
                    raise BridgeError(
                        "invalid_request", "Idempotency key belongs to a different request"
                    )
                return self.decode(row)
        now = time.time()
        job_id = uuid.uuid4().hex
        db.execute(
            "INSERT INTO jobs(id,role,request,request_hash,state,created,updated,deadline,"
            "client_key) VALUES(?,?,?,?,?,?,?,?,?)",
            (job_id, role, json.dumps(request), hashed, state, now, now, now + timeout, client_key),
        )
        db.execute(
            "INSERT INTO job_events(job_id,state,created) VALUES(?,?,?)", (job_id, state, now)
        )
        return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    @staticmethod
    def decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for key in ("request", "result", "error", "process"):
            item[key] = json.loads(item[key]) if item[key] else None
        return item

    def get(self, job_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise BridgeError("invalid_request", "Unknown job")
            return self.decode(row)

    def list_jobs(self, limit: int = 50, before: float | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE created < ? ORDER BY created DESC LIMIT ?",
                (before or float("inf"), min(max(limit, 1), 100)),
            ).fetchall()
        return [self.decode(row) for row in rows]

    def transition(
        self,
        job_id: str,
        state: str,
        *,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        owner: str | None = None,
    ) -> bool:
        with self.transaction() as db:
            row = db.execute("SELECT state,owner FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise BridgeError("invalid_request", "Unknown job")
            if row["state"] in TERMINAL or state not in TRANSITIONS[row["state"]]:
                return False
            if owner and row["owner"] != owner:
                return False
            now = time.time()
            db.execute(
                "UPDATE jobs SET state=?,updated=?,result=?,error=? WHERE id=?",
                (
                    state,
                    now,
                    json.dumps(result) if result is not None else None,
                    json.dumps(error) if error else None,
                    job_id,
                ),
            )
            db.execute(
                "INSERT INTO job_events(job_id,state,created) VALUES(?,?,?)", (job_id, state, now)
            )
            return True

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.transaction() as db:
            row = db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise BridgeError("invalid_request", "Unknown job")
            current = row[0]
            if current not in TERMINAL and current != "cancelling":
                state = "cancelled" if current in {"queued", "pending_approval"} else "cancelling"
                now = time.time()
                db.execute("UPDATE jobs SET state=?,updated=? WHERE id=?", (state, now, job_id))
                db.execute(
                    "INSERT INTO job_events(job_id,state,created) VALUES(?,?,?)",
                    (job_id, state, now),
                )
        return self.get(job_id)

    def claim(self, owner: str, capacity: int, lease_seconds: int = 30) -> dict[str, Any] | None:
        now = time.time()
        with self.transaction() as db:
            expired = db.execute(
                "SELECT job_id FROM approvals WHERE expires<=? "
                "AND job_id IN (SELECT id FROM jobs WHERE state='pending_approval')",
                (now,),
            ).fetchall()
            for approval in expired:
                db.execute(
                    "UPDATE jobs SET state='expired',updated=? WHERE id=?", (now, approval[0])
                )
                db.execute(
                    "INSERT INTO job_events(job_id,state,created) VALUES(?,?,?)",
                    (approval[0], "expired", now),
                )
            db.execute("DELETE FROM api_reservations WHERE expires<=?", (now,))
            reserved = db.execute(
                "SELECT count(*) FROM api_reservations WHERE job_id IS NULL"
            ).fetchone()[0]
            active = db.execute(
                "SELECT count(*) FROM jobs WHERE state IN "
                "('preparing','running','verifying','cancelling')"
            ).fetchone()[0]
            if active + reserved >= capacity:
                return None
            rows = db.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 100"
            ).fetchall()
            for row in rows:
                if row["deadline"] <= now:
                    db.execute(
                        "UPDATE jobs SET state='timed_out',updated=? WHERE id=?", (now, row["id"])
                    )
                    db.execute(
                        "INSERT INTO job_events(job_id,state,created) VALUES(?,?,?)",
                        (row["id"], "timed_out", now),
                    )
                    continue
                # Repository alias and explicitly declared shared resources are serialized.
                req = json.loads(row["request"])
                resources = set(req.get("resources", []))
                running = db.execute(
                    "SELECT request FROM jobs WHERE state IN "
                    "('preparing','running','verifying','cancelling')"
                ).fetchall()
                if any(
                    resources.intersection(json.loads(r[0]).get("resources", [])) for r in running
                ):
                    continue
                db.execute(
                    "UPDATE jobs SET state='preparing',owner=?,lease=?,updated=? WHERE id=?",
                    (owner, now + lease_seconds, now, row["id"]),
                )
                db.execute(
                    "INSERT INTO job_events(job_id,state,created) VALUES(?,?,?)",
                    (row["id"], "preparing", now),
                )
                return self.decode(
                    db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
                )
            return None

    def heartbeat(self, owner: str) -> None:
        now = time.time()
        with self.transaction() as db:
            db.execute(
                "INSERT INTO runner VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET "
                "owner=excluded.owner,heartbeat=excluded.heartbeat",
                (owner, now),
            )
            db.execute(
                "UPDATE jobs SET lease=? WHERE owner=? AND state IN "
                "('preparing','running','verifying','cancelling')",
                (now + 30, owner),
            )

    def runner_alive(self) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT heartbeat FROM runner WHERE id=1").fetchone()
        return row is not None and row[0] > time.time() - 30

    def execution(
        self,
        job_id: str,
        owner: str,
        *,
        process: dict[str, Any] | None = None,
        worktree: str | None = None,
    ) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT owner,state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["owner"] != owner or row["state"] in TERMINAL:
                raise BridgeError("interrupted", "Execution ownership changed")
            if worktree is not None:
                db.execute("UPDATE jobs SET worktree=? WHERE id=?", (worktree, job_id))
            db.execute(
                "UPDATE jobs SET process=? WHERE id=?",
                (json.dumps(process) if process else None, job_id),
            )

    def history(self, consultation_id: str, retention_days: int) -> list[dict[str, Any]]:
        with self.connect() as db:
            row = db.execute(
                "SELECT messages,updated FROM consultations WHERE id=?", (consultation_id,)
            ).fetchone()
        if not row or row["updated"] < time.time() - retention_days * 86400:
            raise BridgeError("invalid_request", "Consultation is missing or expired")
        return json.loads(row[0])

    def save_history(
        self, consultation_id: str, messages: list[dict[str, Any]], usage: dict[str, Any]
    ) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO consultations VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "messages=excluded.messages,updated=excluded.updated",
                (consultation_id, json.dumps(messages), time.time()),
            )
            db.execute(
                "INSERT INTO api_usage(consultation_id,payload,created) VALUES(?,?,?)",
                (consultation_id, json.dumps(usage), time.time()),
            )

    def telemetry(self, event: str) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO telemetry(event,created) VALUES(?,?)", (event[:100], time.time())
            )

    @contextmanager
    def reserve_api(
        self, capacity: int, timeout: float, job_id: str | None = None
    ) -> Iterator[None]:
        reservation_id = uuid.uuid4().hex
        with self.transaction() as db:
            db.execute("DELETE FROM api_reservations WHERE expires<=?", (time.time(),))
            active = db.execute(
                "SELECT count(*) FROM jobs WHERE state IN "
                "('preparing','running','verifying','cancelling')"
            ).fetchone()[0]
            reserved = db.execute(
                "SELECT count(*) FROM api_reservations WHERE job_id IS NULL"
            ).fetchone()[0]
            if job_id is None and active + reserved >= capacity:
                raise BridgeError(
                    "budget_exceeded", "Provider/worker concurrency limit reached", True
                )
            if job_id is not None:
                state = db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not state or state[0] != "running":
                    raise BridgeError("cancelled", "Research job is no longer running")
            db.execute(
                "INSERT INTO api_reservations VALUES(?,?,?)",
                (reservation_id, job_id, time.time() + timeout + 5),
            )
        try:
            yield
        finally:
            with self.transaction() as db:
                db.execute("DELETE FROM api_reservations WHERE id=?", (reservation_id,))
