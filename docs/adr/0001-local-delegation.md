# ADR 0001: Local explicit delegation with separate authority

Status: proposed implementation baseline.

## Decision

Run a Python 3.12+ bridge locally, expose typed FastMCP stdio tools to Claude Code, and call DeepSeek directly using a separate key. Use OpenCode for coding, SQLite for durable state, and a separate runner for asynchronous execution. Keep consultant, coding, and passive research roles distinct. Preserve Claude subscription login and Claude's responsibility for review/integration.

Use host-managed Git worktrees plus disposable sandbox snapshots rather than exposing shared Git metadata to workers. Require enforced container isolation and egress controls before worker execution. Introduce trusted research scopes and owner-only approval for sensitive cases; never use model self-classification as the only authorization signal.

## Alternatives

- **Direct curl/scripts from Claude:** useful for a spike, but weak typed contracts, shared lifecycle management, and consistent policy. A thin CLI remains for debugging and hooks.
- **Replace Claude's backend with DeepSeek:** changes the existing authentication/billing workflow; excluded.
- **Native Claude subagent with a DeepSeek model name:** does not by itself establish independent provider routing. Use a Claude coordinator calling MCP if desired.
- **Remote hosting, general-purpose model gateways, and dashboards:** add deployment and integration complexity beyond the initial local bridge scope.
- **DeepSeek Harness:** potential replacement adapter after evaluation; OpenCode is the initial candidate, not an assertion of superior performance.
- **Host-only Git worktree isolation:** handles checkout separation but cannot contain untrusted execution; rejected.
- **Natural-language refusal detection:** unreliable and cannot establish authorization; explicit typed handoffs are required.
- **Detached worker processes spawned by hooks:** fragile ownership and restart behavior; use a persisted queue and supervised runner.

## Consequences

Explicit delegation adds local packaging, runtime, and policy work but preserves the existing orchestration workflow. DeepSeek charges remain separate. The minimal researcher analyzes supplied text; active tooling and autonomous scanning are outside v1. Isolation, approvals, and recovery are prerequisites to automation, not assumed properties of Git or prompts. Version/capability details remain subject to the M0 verification gate.
