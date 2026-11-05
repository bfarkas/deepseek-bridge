import concurrent.futures
import fcntl
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psutil

from .contracts import Envelope
from .errors import BridgeError
from .processes import owns, stop_group
from .service import Service, redact
from .worker import CodingWorker


class Runner:
    def __init__(self, service: Service):
        self.service, self.db = service, service.db
        self.owner = uuid.uuid4().hex
        self.stopping = threading.Event()

    @contextmanager
    def lock(self) -> Iterator[None]:
        path = self.db.path.parent / "runner.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BridgeError(
                    "worker_unavailable", "Another runner owns this state directory"
                ) from exc
            yield
        finally:
            os.close(fd)

    def reconcile(self) -> None:
        # Caller holds the exclusive runner lock: no live runner can own these jobs.
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE state IN "
                "('preparing','running','verifying','cancelling')"
            ).fetchall()
        for row in rows:
            job = self.db.get(row[0])
            proc = job["process"]
            if proc:
                if owns(proc):
                    stop_group(proc)
                    try:
                        psutil.Process(proc["pid"]).wait(timeout=5)
                    except psutil.NoSuchProcess:
                        pass
                    except psutil.TimeoutExpired as exc:
                        raise BridgeError(
                            "interrupted", "Owned process did not stop; manual recovery needed"
                        ) from exc
                elif psutil.pid_exists(proc["pid"]):
                    raise BridgeError(
                        "interrupted", "Process ownership uncertain; manual recovery required"
                    )
            self.db.transition(
                job["id"],
                "interrupted",
                error={
                    "code": "interrupted",
                    "message": "Runner restarted; explicit new attempt required",
                    "retryable": False,
                },
            )

    def execute(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            if self.db.get(job_id)["state"] == "cancelling":
                self.db.transition(job_id, "cancelled", owner=self.owner)
                return
            if job["role"] == "coding":
                report = CodingWorker(
                    self.service.settings, self.db, self.service.artifacts
                ).execute(job, self.owner)
            elif job["role"] == "research":
                prepared = self.service.research.revalidate(job)
                self.db.transition(job_id, "running", owner=self.owner)
                request = self.service.research.ask_request(prepared)
                # Scope deadline further bounds the provider deadline.
                settings = self.service.settings.model_copy(deep=True)
                settings.consultant.timeout_seconds = min(
                    prepared["timeout_seconds"], max(1, int(job["deadline"] - time.time()))
                )
                from .consultant import Consultant

                consultant = Consultant(settings, self.db, self.service.consultant.provider)
                response: Envelope = consultant.snapshot(
                    request, prepared["snapshot"], research=True, job_id=job_id
                )
                report = {
                    "schema_version": "1.0",
                    "job_id": job_id,
                    "role": "research",
                    "request_hash": job["request_hash"],
                    "model": response.usage.model,
                    "status": response.status,
                    **(response.data or {}),
                    "usage": response.usage.model_dump(),
                    "error": response.error,
                }
                if response.status != "completed":
                    self.db.transition(
                        job_id, "failed", result=report, error=response.error, owner=self.owner
                    )
                    return
            else:
                raise BridgeError("unsupported_capability", "Unknown job role")
            report = redact(report, self.service.settings)
            self.service.artifacts.publish(
                job_id,
                "summary.md",
                ("# DeepSeek Bridge result\n\n" + report.get("summary", "") + "\n").encode(),
                "text/markdown",
            )
            if "verification" in report:
                self.service.artifacts.publish(
                    job_id,
                    "test-results.json",
                    json.dumps(report["verification"]).encode(),
                    "application/json",
                )
            report["artifacts"] = self.service.artifacts.list(job_id, limit=100)
            self.service.artifacts.publish(
                job_id, "handoff.json", json.dumps(report).encode(), "application/json"
            )
            if self.db.get(job_id)["state"] == "cancelling":
                self.db.transition(job_id, "cancelled", owner=self.owner)
            elif time.time() >= job["deadline"]:
                self.db.transition(job_id, "timed_out", owner=self.owner)
            else:
                if not self.db.transition(job_id, "completed", result=report, owner=self.owner):
                    if self.db.get(job_id)["state"] == "cancelling":
                        self.db.transition(job_id, "cancelled", owner=self.owner)
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, BridgeError)
                else BridgeError(
                    "internal_error",
                    "Job failed; inspect local configuration and private artifacts",
                )
            )
            state = self.db.get(job_id)["state"]
            if state == "cancelling":
                self.db.transition(job_id, "cancelled", owner=self.owner)
            else:
                terminal = "timed_out" if error.code == "timed_out" else "failed"
                self.db.transition(job_id, terminal, error=error.as_dict(), owner=self.owner)

        finally:
            if self.db.get(job_id)["state"] == "cancelling":
                self.db.transition(job_id, "cancelled", owner=self.owner)

    def run(self, *, once: bool = False) -> None:
        with self.lock():
            self.reconcile()
            self.db.heartbeat(self.owner)
            capacity = self.service.settings.jobs.max_concurrent
            with concurrent.futures.ThreadPoolExecutor(max_workers=capacity) as pool:
                futures: set[concurrent.futures.Future[None]] = set()
                try:
                    while not self.stopping.is_set():
                        self.db.heartbeat(self.owner)
                        for future in futures:
                            if future.done():
                                future.result()
                        futures = {f for f in futures if not f.done()}
                        while len(futures) < capacity:
                            job = self.db.claim(self.owner, capacity)
                            if job is None:
                                break
                            futures.add(pool.submit(self.execute, job))
                        if once:
                            for future in futures:
                                while not future.done():
                                    self.db.heartbeat(self.owner)
                                    self.stopping.wait(0.1)
                                future.result()
                            break
                        self.stopping.wait(0.2)
                finally:
                    # Persist cancellation for all executing jobs before waiting for threads.
                    with self.db.connect() as db:
                        ids = [
                            r[0]
                            for r in db.execute(
                                "SELECT id FROM jobs WHERE owner=? AND state IN "
                                "('preparing','running','verifying')",
                                (self.owner,),
                            )
                        ]
                    for job_id in ids:
                        self.db.cancel(job_id)
                    concurrent.futures.wait(futures)
                    with self.db.transaction() as db:
                        db.execute("DELETE FROM runner WHERE owner=?", (self.owner,))
