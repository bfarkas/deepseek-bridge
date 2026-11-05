import json
import os
import time
from typing import Any

from .artifacts import Artifacts
from .consultant import Consultant
from .context import check_text, check_value
from .contracts import Ask, CodingRequest, Handoff
from .credentials import get_api_key
from .database import TERMINAL, Database
from .errors import BridgeError
from .provider import Provider
from .research import ResearchService
from .settings import Settings
from .worktrees import base_sha


def redact(value: Any, settings: Settings) -> Any:
    raw = json.dumps(value)
    keys = [get_api_key(settings), os.environ.get("DEEPSEEK_API_KEY")]
    for key in keys:
        if key:
            # Replace JSON-escaped key as well, preserving valid JSON.
            raw = raw.replace(json.dumps(key)[1:-1], "[REDACTED]")
    return json.loads(raw)


class Service:
    def __init__(self, settings: Settings, provider: Provider | None = None):
        self.settings = settings
        self.db = Database(settings)
        self.artifacts = Artifacts(self.db)
        self.consultant = Consultant(settings, self.db, provider)
        self.research = ResearchService(settings, self.db)

    def ask(self, request: Ask) -> dict[str, Any]:
        return redact(self.consultant.ask(request).model_dump(), self.settings)

    def review(self, request: Ask) -> dict[str, Any]:
        if not (request.context.files or request.context.diff or request.context.text):
            raise BridgeError("invalid_request", "Review requires explicitly selected context")
        return self.ask(request.model_copy(update={"mode": "review", "model": "review"}))

    def start_job(self, request: CodingRequest) -> dict[str, Any]:
        from .opencode import available

        available(self.settings)
        repo = self.settings.repository(request.repository)
        if request.verification_profile != repo.verification_profile:
            raise BridgeError(
                "permission_boundary", "Verification profile is not approved for repository"
            )
        if request.verification_profile not in self.settings.profiles:
            raise BridgeError("invalid_request", "Verification profile is missing")
        limits = request.limits
        if "limits" not in request.model_fields_set:
            limits = limits.model_copy(
                update={"timeout_seconds": self.settings.jobs.default_timeout_seconds}
            )
        if limits.timeout_seconds > self.settings.jobs.max_timeout_seconds:
            raise BridgeError("budget_exceeded", "Timeout exceeds deployment limit")
        check_value(self.settings, request.model_dump())
        check_text(request.model_dump_json(), self.settings.consultant.max_input_bytes)
        body = request.model_dump()
        body["limits"] = limits.model_dump()
        body["base_sha"] = base_sha(repo.path, request.base_ref)
        body["attempt"] = 1
        if request.retry_of:
            parent = self.db.get(request.retry_of)
            if (
                parent["role"] != "coding"
                or parent["state"] not in TERMINAL
                or parent["request"]["repository"] != request.repository
            ):
                raise BridgeError(
                    "invalid_request", "Retry requires a terminal coding job in this repository"
                )
            body["base_sha"] = parent["request"]["base_sha"]
            body["attempt"] = parent["request"].get("attempt", 1) + 1
        body["resources"] = ["repository:" + request.repository, *repo.shared_resources]
        # Repeated client IDs retain their immutable base even if HEAD advanced.
        if request.client_request_id:
            with self.db.connect() as db:
                old = db.execute(
                    "SELECT * FROM jobs WHERE client_key=?", (request.client_request_id,)
                ).fetchone()
            if old:
                previous = json.loads(old["request"])
                body["base_sha"] = previous["base_sha"]
        job = self.db.enqueue("coding", body, limits.timeout_seconds, request.client_request_id)
        return self.status(job["id"])

    def status(self, job_id: str, cursor: int = 0) -> dict[str, Any]:
        job = self.db.get(job_id)
        with self.db.connect() as db:
            events = [
                dict(row)
                for row in db.execute(
                    "SELECT seq,state,created FROM job_events "
                    "WHERE job_id=? AND seq>? ORDER BY seq LIMIT 100",
                    (job_id, max(cursor, 0)),
                )
            ]
        return {
            "schema_version": "1.0",
            "job_id": job_id,
            "role": job["role"],
            "state": job["state"],
            "created": job["created"],
            "updated": job["updated"],
            "deadline": job["deadline"],
            "error": job["error"],
            "events": events,
            "cursor": events[-1]["seq"] if events else cursor,
            "runner_alive": self.db.runner_alive(),
            "review": job["review"],
            "usage": job["result"].get("usage") if job["result"] else None,
        }

    def result(self, job_id: str) -> dict[str, Any]:
        job = self.db.get(job_id)
        return redact(
            {
                "schema_version": "1.0",
                "job_id": job_id,
                "state": job["state"],
                "report": job["result"],
                "error": job["error"],
                "artifacts": self.artifacts.list(job_id),
            },
            self.settings,
        )

    def cancel(self, job_id: str) -> dict[str, Any]:
        self.db.cancel(job_id)
        return self.status(job_id)

    def enqueue_research(self, handoff: Handoff, session_id: str) -> dict[str, Any]:
        job = self.research.enqueue(handoff, session_id)
        result = self.status(job["id"])
        result["request_hash"] = job["request_hash"]
        return result

    def doctor(self) -> dict[str, Any]:
        import platform
        import shutil
        from importlib.metadata import version

        from .provider import MODELS

        models = [
            self.settings.deepseek.consultant_model,
            self.settings.deepseek.review_model,
            self.settings.deepseek.research_model,
        ]
        checks = {
            "configuration": True,
            "database_schema": True,
            "credential_present": bool(get_api_key(self.settings)),
            "model_ids": all(model in MODELS for model in models),
            "runner_alive": self.db.runner_alive(),
            "git_present": bool(shutil.which("git")),
            "worker_enabled": self.settings.worker.enabled,
            "worker_compatibility_verified": self.settings.worker.compatibility_verified,
            "opencode_present": bool(shutil.which(self.settings.worker.executable)),
            "automatic_research_verified": self.settings.research.compatibility_verified,
        }
        with self.db.connect() as db:
            checks["database_schema"] = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        checks["worker_ready"] = False
        if self.settings.worker.enabled:
            try:
                from .opencode import available

                available(self.settings)
                checks["worker_ready"] = True
            except BridgeError:
                pass
        checks["trusted_registry"] = False
        if self.settings.research.mode == "automatic_with_approval":
            try:
                from .policy import load_registry

                load_registry(self.settings)
                checks["trusted_registry"] = True
            except BridgeError:
                pass
        required = [
            "configuration",
            "database_schema",
            "credential_present",
            "model_ids",
            "runner_alive",
        ]
        if self.settings.worker.enabled:
            required.append("worker_ready")
        if self.settings.research.mode == "automatic_with_approval":
            required.extend(["trusted_registry", "automatic_research_verified"])
        actions = []
        if not checks["credential_present"]:
            actions.append("Set DEEPSEEK_API_KEY in the private credential file or macOS Keychain")
        if not checks["runner_alive"]:
            actions.append("Start deepseek-bridge runner separately")
        return {
            "ok": all(checks[key] for key in required),
            "checks": checks,
            "versions": {
                "python": platform.python_version(),
                "anthropic": version("anthropic"),
                "fastmcp": version("fastmcp"),
                "platform": platform.system(),
            },
            "actions": actions,
            "paid_calls": 0,
            "timestamp": time.time(),
        }
