import hashlib
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .database import Database
from .errors import BridgeError
from .settings import private_dir


class Artifacts:
    def __init__(self, db: Database, max_bytes: int = 10000000):
        self.db = db
        self.root = private_dir(db.path.parent / "artifacts")
        self.max_bytes = max_bytes

    def directory(self, job_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise BridgeError("invalid_request", "Invalid job ID")
        return private_dir(self.root / job_id)

    def publish(
        self, job_id: str, name: str, content: bytes, media_type: str = "application/octet-stream"
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", name) or name.startswith("."):
            raise BridgeError("invalid_request", "Invalid artifact name")
        if len(content) > self.max_bytes:
            raise BridgeError("budget_exceeded", "Artifact exceeds byte limit")
        directory = self.directory(job_id)
        temporary = directory / (".tmp-" + uuid.uuid4().hex)
        try:
            with temporary.open("xb") as stream:
                os.chmod(temporary, 0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            checksum = hashlib.sha256(content).hexdigest()
            artifact_id = uuid.uuid4().hex
            with self.db.transaction() as db:
                if db.execute(
                    "SELECT 1 FROM artifacts WHERE job_id=? AND name=?", (job_id, name)
                ).fetchone():
                    raise BridgeError("invalid_request", "Published artifacts are immutable")
                os.replace(temporary, directory / name)
                db.execute(
                    "INSERT INTO artifacts VALUES(?,?,?,?,?,?)",
                    (artifact_id, job_id, name, len(content), checksum, media_type),
                )
            return {
                "id": artifact_id,
                "name": name,
                "size": len(content),
                "sha256": checksum,
                "media_type": media_type,
            }
        finally:
            temporary.unlink(missing_ok=True)

    def list(self, job_id: str, offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.connect() as db:
            rows = db.execute(
                "SELECT * FROM artifacts WHERE job_id=? ORDER BY name LIMIT ? OFFSET ?",
                (job_id, min(max(limit, 1), 100), max(offset, 0)),
            ).fetchall()
        return [dict(row) for row in rows]

    def read(self, job_id: str, artifact_id: str) -> bytes:
        with self.db.connect() as db:
            row = db.execute(
                "SELECT * FROM artifacts WHERE id=? AND job_id=?", (artifact_id, job_id)
            ).fetchone()
        if row is None:
            raise BridgeError("invalid_request", "Unknown artifact")
        path = self.directory(job_id) / row["name"]
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                content = stream.read(self.max_bytes + 1)
        except OSError as exc:
            raise BridgeError("artifact_missing", "Artifact is missing or inaccessible") from exc
        if len(content) != row["size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise BridgeError("artifact_missing", "Artifact integrity check failed")
        return content

    def remove_orphans(self, older_than_seconds: int = 3600) -> int:
        count = 0
        with self.db.connect() as db:
            known = {(r[0], r[1]) for r in db.execute("SELECT job_id,name FROM artifacts")}
        for directory in self.root.iterdir():
            if directory.is_symlink() or not directory.is_dir():
                continue
            for path in directory.iterdir():
                if (
                    not path.is_symlink()
                    and path.is_file()
                    and (directory.name, path.name) not in known
                    and path.stat().st_mtime < time.time() - older_than_seconds
                ):
                    path.unlink()
                    count += 1
        return count
