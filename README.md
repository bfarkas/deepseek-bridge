# DeepSeek Bridge

A local delegation bridge for Claude Code, with explicit DeepSeek consultation, durable coding jobs, and scoped passive security research. Claude keeps its subscription authentication; DeepSeek calls use a separate credential and billing.

The consultant CLI and seven stdio MCP tools are implemented. SQLite, a separate runner, reviewable artifacts, a gated host OpenCode adapter, and owner-bound research approvals are included. **OpenCode execution, service-manager installation, and paid DeepSeek calls have not been validated on this installation.** Coding defaults off until its compatibility gate passes. See [compatibility evidence](docs/compatibility.md) and [release status](docs/release-notes.md).

## Install and consult

Requires Python 3.12+ and Git on macOS/Linux. With [uv](https://docs.astral.sh/uv/):

```sh
uv sync --frozen
mkdir -p ~/.config/deepseek-bridge
cp config.example.toml ~/.config/deepseek-bridge/config.toml
chmod 600 ~/.config/deepseek-bridge/config.toml
# Fill the private credentials.json file; see docs/operations.md.
uv run deepseek-bridge ask "Explain the tradeoffs in this approach" --text "Selected context"
uv run deepseek-bridge --config ~/.config/deepseek-bridge/config.toml runner
```

Register repository aliases in the private configuration before selecting files:

```sh
deepseek-bridge review "Find correctness issues" --repository example-project --file src/parser.py
git diff --binary > /tmp/selected.patch
deepseek-bridge review "Review this selected diff" --diff-file /tmp/selected.patch
deepseek-bridge doctor
```

These consultation commands send the explicit task/context to DeepSeek and incur separate usage. No paid call is made by `doctor` or offline tests. Never set `ANTHROPIC_BASE_URL` or replace Claude credentials for this bridge.

## Claude Code

Use the absolute executable from `.venv/bin/deepseek-bridge` (or an installed tool):

```sh
claude mcp add --scope user --transport stdio deepseek-bridge -- /absolute/path/to/deepseek-bridge serve
```

Tools accepting domain contracts use a `request` object, for example `deepseek_review({"request":{"schema_version":"1.0","task":"Review","context":{"repository":"example-project","files":["src/parser.py"]}}})`. Approvals are available only through the local CLI. Results are recommendations; Claude owns review and integration.

## Development

```sh
uv sync --frozen
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src
uv run pytest -q
uv run python scripts/export_schemas.py
```

Offline tests use a fake provider, mock SDK HTTP transport, real fixture Git worktrees/processes, and in-process plus child-process stdio MCP. They do not call a paid API. [Opt-in smoke checks](docs/compatibility.md) are separate.

## Documentation

- [Implementation plan and progress](docs/implementation-plan.md)
- [Operations, installation, recovery, and rollback](docs/operations.md)
- [Compatibility matrix and outstanding live gates](docs/compatibility.md)
- [Architecture](docs/architecture.md), [contracts](docs/contracts.md), [security escalation](docs/security-escalation.md)
- [Claude Code integration](docs/claude-code-integration.md), [decisions](docs/adr/0001-local-delegation.md), [references](docs/sources.md)

Host coding uses account permissions and networking. Dedicated worktrees separate changes; they do not provide a security sandbox. No automatic merge, push, deployment, active scanning, exploit execution, remote hosting, or dashboard is provided.
