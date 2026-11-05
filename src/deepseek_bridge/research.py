import getpass
import json
import time
from typing import Any

from . import policy
from .context import check_text, check_value, collect, digest
from .contracts import Ask, Handoff
from .database import Database
from .errors import BridgeError
from .settings import Settings


class ResearchService:
    def __init__(self, settings: Settings, db: Database):
        self.settings, self.db = settings, db

    def prepare(self, handoff: Handoff, session: str) -> dict[str, Any]:
        if handoff.blocker_type in {"permission_denied", "safety_boundary"}:
            raise BridgeError(
                "permission_boundary", "Permission/safety boundaries cannot be rerouted"
            )
        if handoff.task_status == "completed":
            raise BridgeError("invalid_request", "Completed tasks do not escalate")
        scope = policy.resolve(self.settings, handoff, session)
        snapshot = collect(self.settings, handoff.context)
        check_value(self.settings, handoff.model_dump())
        check_text(handoff.model_dump_json(), self.settings.consultant.max_input_bytes)
        return {
            "handoff": handoff.model_dump(),
            "session": session,
            "snapshot": snapshot,
            "scope_fingerprint": policy.scope_fingerprint(scope),
            "scope_version": scope.version,
            "model": self.settings.deepseek.research_model,
            "max_output_tokens": scope.max_output_tokens,
            "timeout_seconds": scope.timeout_seconds,
        }

    def enqueue(self, handoff: Handoff, session: str) -> dict[str, Any]:
        prepared = self.prepare(handoff, session)
        scope = policy.resolve(self.settings, handoff, session)
        with self.db.transaction() as db:
            job = self.db.insert_job(db, "research", prepared, 3600, state="pending_approval")
            db.execute(
                "INSERT INTO approvals(job_id,request_hash,scope_version,expires) VALUES(?,?,?,?)",
                (
                    job["id"],
                    job["request_hash"],
                    scope.version,
                    min(time.time() + 3600, scope.expires),
                ),
            )
            return job

    def revalidate(self, job: dict[str, Any], *, approval: bool = True) -> dict[str, Any]:
        request = job["request"]
        current = self.prepare(Handoff.model_validate(request["handoff"]), request["session"])
        if digest(current) != job["request_hash"]:
            raise BridgeError(
                "approval_required", "Request/context/policy changed; create a new owner revision"
            )
        if approval:
            with self.db.connect() as db:
                row = db.execute("SELECT * FROM approvals WHERE job_id=?", (job["id"],)).fetchone()
            if row and (
                row["decision"] != "approved"
                or row["expires"] <= time.time()
                or row["request_hash"] != job["request_hash"]
            ):
                raise BridgeError("approval_required", "Approval is missing, expired or stale")
        return current

    def proposal(self, job_id: str) -> dict[str, Any]:
        job = self.db.get(job_id)
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM approvals WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise BridgeError("invalid_request", "Job has no approval proposal")
        job["approval"] = dict(row)
        return job

    def decide(self, job_id: str, request_hash: str, approve: bool) -> dict[str, Any]:
        job = self.db.get(job_id)
        if job["state"] != "pending_approval":
            raise BridgeError("invalid_request", "Job is not awaiting approval")
        if request_hash != job["request_hash"]:
            raise BridgeError("approval_required", "Approval hash mismatch")
        if approve:
            self.revalidate(job, approval=False)
        with self.db.transaction() as db:
            row = db.execute("SELECT * FROM approvals WHERE job_id=?", (job_id,)).fetchone()
            state = db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
            if state != "pending_approval" or not row or row["expires"] <= time.time():
                raise BridgeError("approval_required", "Approval is expired or no longer pending")
            decision = "approved" if approve else "rejected"
            db.execute(
                "UPDATE approvals SET decision=?,actor=?,decided=? WHERE job_id=?",
                (decision, getpass.getuser(), time.time(), job_id),
            )
            new_state = "queued" if approve else "rejected"
            db.execute(
                "UPDATE jobs SET state=?,updated=? WHERE id=?", (new_state, time.time(), job_id)
            )
            db.execute(
                "INSERT INTO job_events(job_id,state,created) VALUES(?,?,?)",
                (job_id, new_state, time.time()),
            )
        return self.db.get(job_id)

    def ask_request(self, prepared: dict[str, Any]) -> Ask:
        handoff = Handoff.model_validate(prepared["handoff"])
        return Ask(
            task=json.dumps(
                {
                    "objective": handoff.objective,
                    "attempted_approaches": handoff.attempted_approaches,
                    "claimed_findings_untrusted": handoff.verified_findings,
                    "hypotheses": handoff.open_hypotheses,
                    "acceptance_criteria": handoff.acceptance_criteria,
                }
            ),
            model="research",
            context=handoff.context,
            max_output_tokens=prepared["max_output_tokens"],
        )
