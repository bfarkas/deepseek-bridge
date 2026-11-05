import os
import shutil
import time
from pathlib import Path
from typing import Any

from .database import TERMINAL
from .errors import BridgeError
from .service import Service
from .worktrees import cleanup


def delete_job(service: Service, job_id: str) -> None:
    job = service.db.get(job_id)
    if job["state"] not in TERMINAL:
        raise BridgeError("permission_boundary", "Cancel/finish job before deleting artifacts")
    if job["worktree"]:
        repo = service.settings.repository(job["request"]["repository"])
        root = service.settings.worker.worktree_root or service.db.path.parent / "worktrees"
        cleanup(repo.path, root, job_id)
    directory = service.artifacts.directory(job_id)
    # Only this validated UUID directory under the private artifact root is removable.
    shutil.rmtree(directory)
    with service.db.transaction() as db:
        db.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def prune(service: Service) -> dict[str, Any]:
    cutoff = time.time() - service.settings.storage.retention_days * 86400
    with service.db.transaction() as db:
        consultations = db.execute("DELETE FROM consultations WHERE updated<?", (cutoff,)).rowcount
        ids = [r[0] for r in db.execute("SELECT id FROM jobs WHERE updated<?", (cutoff,))]
    removed, retained = [], []
    for job_id in ids:
        try:
            delete_job(service, job_id)
            removed.append(job_id)
        except BridgeError:
            retained.append(job_id)
    return {
        "consultations_removed": consultations,
        "jobs_removed": removed,
        "jobs_retained_for_review": retained,
        "orphans_removed": service.artifacts.remove_orphans(),
    }


def export(service: Service, job_id: str, destination: Path) -> dict[str, Any]:
    service.db.get(job_id)
    if destination.exists():
        raise BridgeError("invalid_request", "Export destination must not already exist")
    destination.mkdir(mode=0o700, parents=True)
    for artifact in service.artifacts.list(job_id, limit=100):
        content = service.artifacts.read(job_id, artifact["id"])
        path = destination / artifact["name"]
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
    return {"exported_to": str(destination)}
