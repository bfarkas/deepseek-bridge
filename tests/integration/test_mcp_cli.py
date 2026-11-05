import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import FakeProvider
from fastmcp import Client

from deepseek_bridge.server import create_server
from deepseek_bridge.service import Service
from deepseek_bridge.settings import Settings


def test_mcp_surface_and_no_approval_tool(settings: Settings, fake: FakeProvider) -> None:
    async def exercise() -> None:
        async with Client(create_server(Service(settings, fake))) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools} == {
                "deepseek_ask",
                "deepseek_review",
                "deepseek_start_job",
                "deepseek_job_status",
                "deepseek_job_result",
                "deepseek_cancel_job",
                "deepseek_research",
            }
            response = await client.call_tool("deepseek_ask", {"request": {"task": "Explain"}})
            assert response.structured_content["status"] == "completed"
            response = await client.call_tool("deepseek_job_status", {"job_id": "unknown"})
            assert response.structured_content["error"]["code"] == "invalid_request"

    asyncio.run(exercise())


def test_stdio_process_cli_and_disconnect(settings: Settings, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[storage]\nstate_dir=" + json.dumps(str(settings.storage.state_dir)) + "\n")
    service = Service(settings)
    job = service.db.enqueue("research", {"persisted": True}, 100)
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    command = [sys.executable, "-m", "deepseek_bridge", "--config", str(config)]
    status = subprocess.run(
        command + ["jobs", "status", job["id"]], capture_output=True, env=env, check=True
    )
    assert json.loads(status.stdout)["state"] == "queued"
    doctor = subprocess.run(command + ["doctor"], capture_output=True, env=env)
    assert doctor.returncode == 1
    assert json.loads(doctor.stdout)["paid_calls"] == 0

    # A real stdio MCP child starts and exits independently of the already-persisted queue.
    async def exercise() -> None:
        from fastmcp.client.transports import StdioTransport

        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "deepseek_bridge", "--config", str(config), "serve"],
            env=env,
        )
        async with Client(transport) as client:
            assert len(await client.list_tools()) == 7

    asyncio.run(exercise())
    assert Service(settings).db.get(job["id"])["state"] == "queued"
