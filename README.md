# DeepSeek Bridge

A local delegation bridge for Claude Code: DeepSeek consultation, isolated coding jobs, and passive cybersecurity research. Claude remains the orchestrator using its existing subscription login; delegated DeepSeek calls use a separate API key and billing.

**Status: implementation plan and directory scaffold only.** No server, hooks, worker runner, or executable package is implemented yet. Commands in the documentation describe the intended interface.

## Documentation

- [Implementation plan](docs/implementation-plan.md): ordered work packages, dependencies, acceptance criteria, and release gates.
- [Architecture](docs/architecture.md): components, trust boundaries, worktree execution, persistence, and lifecycle.
- [Contracts](docs/contracts.md): proposed MCP tools, CLI, job states, reports, and escalation envelope.
- [Security escalation](docs/security-escalation.md): automatic technical handoffs and approval policy.
- [Claude Code integration](docs/claude-code-integration.md): installation design and operational workflow.
- [Architecture decisions](docs/adr/0001-local-delegation.md): choices and alternatives.
- [Sources and uncertainties](docs/sources.md): public technical references and implementation uncertainties.
- [Example configuration](config.example.toml): proposed settings; not yet executable.

## Scope

Python 3.12+, FastMCP over stdio, direct DeepSeek API access, SQLite, and OpenCode coding workers running on the host in dedicated Git worktrees. The bridge runs locally and preserves the existing Claude Code authentication workflow. Remote hosting, general-purpose model gateways, and dashboards are outside the initial scope.

Start implementation with milestone M0, then the consultant MVP. The host worker uses the local toolchain and account permissions; worktrees separate job changes rather than restricting filesystem access. See [the source layout](src/deepseek_bridge/README.md) for module responsibilities.
