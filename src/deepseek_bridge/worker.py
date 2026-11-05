import hashlib
import json
import time
from pathlib import Path
from typing import Any

from . import opencode, worktrees
from .artifacts import Artifacts
from .credentials import get_api_key
from .database import Database
from .errors import BridgeError
from .processes import environment, run
from .settings import Settings


class CodingWorker:
    def __init__(self, settings: Settings, db: Database, artifacts: Artifacts):
        self.settings, self.db, self.artifacts = settings, db, artifacts

    def execute(self, job: dict[str, Any], owner: str) -> dict[str, Any]:
        request, job_id = job["request"], job["id"]
        repo = self.settings.repository(request["repository"])
        executable = opencode.available(self.settings)
        original = worktrees.snapshot(repo.path)
        root = self.settings.worker.worktree_root or self.db.path.parent / "worktrees"
        target = worktrees.create(repo.path, root, job_id, request["base_sha"])
        self.db.execution(job_id, owner, worktree=str(target))
        private = self.artifacts.directory(job_id)
        env = opencode.worker_environment(self.settings, private, target)
        evidence: list[dict[str, Any]] = []
        artifacts = []

        def execute(
            argv: list[str], process_env: dict[str, str], *, worker: bool = False
        ) -> dict[str, Any]:
            result = run(
                argv,
                target,
                process_env,
                job["deadline"] - time.time(),
                self.settings.worker.max_output_bytes,
                cancelled=lambda: self.db.get(job_id)["state"] == "cancelling",
                record=lambda value: self.db.execution(job_id, owner, process=value),
                within_budget=(
                    lambda raw: opencode.within_token_budget(
                        raw, request["limits"]["max_output_tokens"]
                    )
                )
                if worker
                else lambda _: True,
            )
            output = result.pop("output")
            if worker:
                result["argv"] = [
                    *argv[:-1],
                    "[task hash: " + hashlib.sha256(argv[-1].encode()).hexdigest() + "]",
                ]
            key = get_api_key(self.settings)
            if key:
                output = output.replace(key.encode(), b"[REDACTED]")
            log = self.artifacts.publish(
                job_id, f"command-{len(evidence)}.log", output, "text/plain"
            )
            result.update(
                {
                    "log_artifact": log,
                    "output_sha256": hashlib.sha256(output).hexdigest(),
                    "environment_profile": "owner-configured, credential-filtered",
                    "test_count": None,
                    "output": output,
                }
            )
            evidence.append({k: v for k, v in result.items() if k != "output"})
            return result

        def require(result: dict[str, Any]) -> None:
            if result["reason"]:
                code = (
                    result["reason"]
                    if result["reason"] in {"cancelled", "timed_out"}
                    else "budget_exceeded"
                )
                raise BridgeError(code, "Host command stopped; partial logs retained")
            if result["exit_code"]:
                raise BridgeError("worker_error", "Host command failed; private logs retained")

        self.db.transition(job_id, "running", owner=owner)
        try:
            config = execute([str(executable), "debug", "config", "--standalone"], env)
            require(config)
            opencode.validate_effective(config["output"], Path(env["OPENCODE_CONFIG"]))
            if repo.preparation_profile:
                profile = self.settings.profiles.get(repo.preparation_profile)
                if not profile:
                    raise BridgeError("invalid_request", "Unknown preparation profile")
                for command in profile.commands:
                    require(execute(command, environment(profile.environment)))
            prompt = json.dumps(
                {
                    "task": request["task"],
                    "acceptance_criteria": request["acceptance_criteria"],
                    "constraints": request["constraints"],
                    "instructions": "Edit this worktree only. Never push, merge or deploy. "
                    "Trusted verification runs separately after you finish.",
                }
            )
            result = execute(
                [
                    str(executable),
                    "run",
                    "--standalone",
                    "--format",
                    "json",
                    "--model",
                    self.settings.worker.model,
                    "--",
                    prompt,
                ],
                env,
                worker=True,
            )
            # Saved before any stop is reported, so partial edits stay reviewable.
            patch, files = worktrees.patch(target, request["base_sha"], private)
            artifacts.append(self.artifacts.publish(job_id, "changes.patch", patch, "text/x-diff"))
            require(result)
            usage = opencode.parse_events(result["output"])
            artifacts.append(
                self.artifacts.publish(
                    job_id, "events.jsonl", result["output"], "application/x-ndjson"
                )
            )
            self.db.transition(job_id, "verifying", owner=owner)
            profile = self.settings.profiles[request["verification_profile"]]
            verification = []
            before_verification = worktrees.snapshot(target)
            tool_versions: list[dict[str, Any]] = []
            for command in profile.version_commands:
                version_result = execute(command, environment(profile.environment))
                require(version_result)
                tool_versions.append(
                    {
                        "argv": command,
                        "output": version_result["output"].decode(errors="replace")[:10000],
                    }
                )
            for command in profile.commands:
                checked = execute(command, environment(profile.environment))
                verification.append({k: v for k, v in checked.items() if k != "output"})
                if checked["reason"]:
                    require(checked)
            after_verification = worktrees.snapshot(target)
            unchanged = original == worktrees.snapshot(repo.path)
            return {
                "schema_version": "1.0",
                "job_id": job_id,
                "role": "coding",
                "status": "completed",
                "request_hash": job["request_hash"],
                "repository": request["repository"],
                "base_sha": request["base_sha"],
                "result_sha": None,
                "patch_sha256": hashlib.sha256(patch).hexdigest(),
                "changed_files": files,
                "summary": "Bridge-collected patch; integration requires review",
                "model": usage["model"],
                "requested_model": self.settings.worker.model,
                "usage": usage,
                "original_checkout_unchanged": unchanged,
                "verification": {
                    "status": "unknown"
                    if before_verification != after_verification
                    else "passed"
                    if all(v["exit_code"] == 0 for v in verification)
                    else "failed",
                    "runs": verification,
                    "workspace_before": before_verification,
                    "workspace_after": after_verification,
                },
                "tool_versions": {
                    "verification": tool_versions,
                    "opencode": self.settings.worker.expected_version,
                    "git": worktrees.git(target, "--version").decode().strip(),
                },
                "risks": [
                    "Host account permissions apply; worktrees do not provide containment",
                    "Tests may be modified in patch; inspect before integration",
                ],
                "unresolved_questions": [],
                "artifacts": artifacts,
            }
        finally:
            # These logs remain available even when execution or collection fails.
            self.artifacts.publish(
                job_id, "execution.json", json.dumps(evidence).encode(), "application/json"
            )
