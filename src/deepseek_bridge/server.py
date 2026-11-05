from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from pydantic import ValidationError

from .contracts import Ask, CodingRequest, Handoff
from .errors import BridgeError
from .service import Service


def create_server(service: Service) -> FastMCP:
    mcp = FastMCP(
        "deepseek-bridge",
        instructions=(
            "Use explicitly selected context. Claude owns review/integration. "
            "Coding executes with host account permissions. Approvals are local-owner CLI only."
        ),
    )

    def safe(call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return call()
        except BridgeError as exc:
            return {"schema_version": "1.0", "status": "failed", "error": exc.as_dict()}
        except ValidationError:
            return {
                "schema_version": "1.0",
                "status": "failed",
                "error": {
                    "code": "invalid_request",
                    "message": "Request validation failed",
                    "retryable": False,
                },
            }
        except Exception:
            return {
                "schema_version": "1.0",
                "status": "failed",
                "error": {
                    "code": "internal_error",
                    "message": "Local operation failed",
                    "retryable": False,
                },
            }

    @mcp.tool
    def deepseek_ask(request: Ask) -> dict[str, Any]:
        """Consult DeepSeek using explicitly selected text/files; never edits source."""
        return safe(lambda: service.ask(request))

    @mcp.tool
    def deepseek_review(request: Ask) -> dict[str, Any]:
        """Review selected context; return validated findings and nullable usage."""
        return safe(lambda: service.review(request))

    @mcp.tool
    def deepseek_start_job(request: CodingRequest) -> dict[str, Any]:
        """Queue a dedicated host worktree job; never merges, pushes or deploys."""
        return safe(lambda: service.start_job(request))

    @mcp.tool
    def deepseek_job_status(job_id: str, cursor: int = 0) -> dict[str, Any]:
        """Read status and at most 100 events after the supplied cursor."""
        return safe(lambda: service.status(job_id, cursor))

    @mcp.tool
    def deepseek_job_result(job_id: str) -> dict[str, Any]:
        """Read the bridge report and bounded artifact descriptors."""
        return safe(lambda: service.result(job_id))

    @mcp.tool
    def deepseek_cancel_job(job_id: str) -> dict[str, Any]:
        """Persist idempotent cancellation; the runner stops owned execution."""
        return safe(lambda: service.cancel(job_id))

    @mcp.tool
    def deepseek_research(request: Handoff, session_id: str) -> dict[str, Any]:
        """Propose passive research within an owner-created scope; CLI approval required."""
        return safe(lambda: service.enqueue_research(request, session_id))

    return mcp
