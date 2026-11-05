import argparse
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import __version__
from .contracts import Ask, CodingRequest, Context, Handoff
from .errors import BridgeError
from .service import Service, redact
from .settings import load_settings


def read_request(path: str) -> Any:
    if path == "-":
        raw = sys.stdin.buffer.read(250001)
    else:
        with Path(path).open("rb") as stream:
            raw = stream.read(250001)
    if len(raw) > 250000:
        raise BridgeError("invalid_request", "Input exceeds size limit")
    return json.loads(raw)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="deepseek-bridge")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--config", type=Path)
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    runner = sub.add_parser("runner")
    runner.add_argument("--once", action="store_true")
    sub.add_parser("doctor")
    for name in ("ask", "review"):
        command = sub.add_parser(name)
        command.add_argument("task", nargs="?")
        command.add_argument("--request")
        command.add_argument("--repository")
        command.add_argument("--file", action="append", default=[])
        command.add_argument("--text", default="")
        command.add_argument("--diff-file", type=Path)
        command.add_argument("--consultation-id")
    research = sub.add_parser("research")
    research.add_argument("--request", required=True)
    research.add_argument("--session-id", required=True)
    jobs = sub.add_parser("jobs").add_subparsers(dest="action", required=True)
    start = jobs.add_parser("start")
    start.add_argument("--request", required=True)
    listing = jobs.add_parser("list")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--before", type=float)
    for name in ("status", "result", "cancel", "delete", "export", "review", "retry"):
        command = jobs.add_parser(name)
        command.add_argument("job_id")
        if name == "export":
            command.add_argument("destination", type=Path)
        if name == "review":
            command.add_argument("outcome", choices=["accepted", "rejected"])
    approvals = sub.add_parser("approvals").add_subparsers(dest="action", required=True)
    for name in ("show", "approve", "reject"):
        command = approvals.add_parser(name)
        command.add_argument("job_id")
        if name != "show":
            command.add_argument("--request-hash", required=True)
    sub.add_parser("prune")
    service = sub.add_parser("service")
    service.add_argument("action", choices=["install", "remove"])
    return root


def dispatch(args: argparse.Namespace, service: Service) -> Any:
    match args.command:
        case "serve":
            from .server import create_server

            create_server(service).run(transport="stdio", show_banner=False)
            return None
        case "runner":
            from .runner import Runner

            runner = Runner(service)
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: runner.stopping.set())
            runner.run(once=args.once)
            return None
        case "doctor":
            return service.doctor()
        case "ask" | "review":
            if args.request:
                request = Ask.model_validate(read_request(args.request))
            else:
                if not args.task:
                    raise BridgeError("invalid_request", "Supply task or --request")
                diff = ""
                if args.diff_file:
                    with args.diff_file.open("rb") as stream:
                        raw = stream.read(service.settings.consultant.max_input_bytes + 1)
                    diff = raw.decode("utf-8")
                request = Ask(
                    task=args.task,
                    context=Context(
                        repository=args.repository, files=args.file, text=args.text, diff=diff
                    ),
                    consultation_id=args.consultation_id,
                )
            return service.review(request) if args.command == "review" else service.ask(request)
        case "research":
            return service.enqueue_research(
                Handoff.model_validate(read_request(args.request)), args.session_id
            )
        case "jobs":
            return job_command(args, service)
        case "approvals":
            job = service.research.proposal(args.job_id)
            if args.action == "show":
                return job
            if args.action == "approve":
                if not sys.stdin.isatty():
                    raise BridgeError(
                        "approval_required", "Approval requires interactive owner terminal"
                    )
                print(json.dumps(redact(job, service.settings), indent=2), file=sys.stderr)
                print(
                    "Approve exact passive request above? Type approve: ", file=sys.stderr, end=""
                )
                if input().strip() != "approve":
                    raise BridgeError("approval_required", "Owner did not confirm")
            service.research.decide(args.job_id, args.request_hash, args.action == "approve")
            return service.status(args.job_id)
        case "prune":
            from .maintenance import prune

            return prune(service)
        case "service":
            from .services import configure

            if args.config is None:
                raise BridgeError(
                    "invalid_request", "Service installation requires explicit --config path"
                )
            return configure(args.config, remove=args.action == "remove")
    raise BridgeError("invalid_request", "Unknown command")


def job_command(args: argparse.Namespace, service: Service) -> Any:
    match args.action:
        case "start":
            return service.start_job(CodingRequest.model_validate(read_request(args.request)))
        case "list":
            return [
                service.status(job["id"]) for job in service.db.list_jobs(args.limit, args.before)
            ]
        case "retry":
            job = service.db.get(args.job_id)
            if job["role"] != "coding":
                raise BridgeError(
                    "invalid_request", "Research retries need a new owner-created task revision"
                )
            fields = CodingRequest.model_fields
            raw = {key: value for key, value in job["request"].items() if key in fields}
            raw.update({"retry_of": args.job_id, "client_request_id": None})
            return service.start_job(CodingRequest.model_validate(raw))
        case "status":
            return service.status(args.job_id)
        case "result":
            return service.result(args.job_id)
        case "cancel":
            return service.cancel(args.job_id)
        case "review":
            from .database import TERMINAL

            if service.db.get(args.job_id)["state"] not in TERMINAL:
                raise BridgeError("invalid_request", "Job has not finished")
            with service.db.transaction() as db:
                db.execute("UPDATE jobs SET review=? WHERE id=?", (args.outcome, args.job_id))
            return service.status(args.job_id)
        case "export":
            from .maintenance import export

            return export(service, args.job_id, args.destination)
        case "delete":
            from .maintenance import delete_job

            delete_job(service, args.job_id)
            return {"deleted": args.job_id}
    raise BridgeError("invalid_request", "Unknown jobs command")


def main() -> None:
    os.umask(0o077)
    args = parser().parse_args()
    try:
        settings = load_settings(args.config)
        result = dispatch(args, Service(settings))
        if result is not None:
            print(json.dumps(redact(result, settings), indent=2))
            if isinstance(result, dict) and (
                result.get("ok") is False or result.get("status") == "failed"
            ):
                raise SystemExit(1)
    except (BridgeError, ValidationError, OSError, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, BridgeError)
            else BridgeError(
                "invalid_request", "Invalid configuration/input or unavailable local resource"
            )
        )
        print(json.dumps({"error": error.as_dict()}), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Local operation failed; check configuration and runner health",
                        "retryable": False,
                    }
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
