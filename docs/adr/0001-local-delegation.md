# ADR 0001: Local explicit delegation with separate authority

Status: accepted implementation baseline; host-worker and research release gates remain unverified on real installed tools.

## Decision

Run a Python 3.12+ bridge locally, expose typed FastMCP stdio tools to Claude Code, and call DeepSeek directly using a separate key. Use OpenCode for coding, SQLite for durable state, and a separate runner for asynchronous execution. Keep consultant, coding, and passive research roles distinct. Preserve Claude subscription login and Claude's responsibility for review/integration.

Run OpenCode directly on the host in a dedicated Git worktree per job. Use local tools and explicitly configured local dependencies, files, caches, and services without source snapshot export, container setup, or a credential relay. Apply scoped OpenCode permissions and a controlled environment, and track worker/verification process groups. Introduce trusted research scopes and owner-only approval for sensitive cases; never use model self-classification as the only authorization signal.

## Alternatives

- **Direct curl/scripts from Claude:** useful for a spike, but weak typed contracts, shared lifecycle management, and consistent policy. A thin CLI remains for debugging and hooks.
- **Replace Claude's backend with DeepSeek:** changes the existing authentication/billing workflow; excluded.
- **Native Claude subagent with a DeepSeek model name:** does not by itself establish independent provider routing. Use a Claude coordinator calling MCP if desired.
- **Remote hosting, general-purpose model gateways, and dashboards:** add deployment and integration complexity beyond the initial local bridge scope.
- **DeepSeek Harness:** potential replacement adapter after evaluation; OpenCode is the initial candidate, not an assertion of superior performance.
- **Containerized OpenCode:** provides a stronger execution boundary but adds file-access, dependency, networking, and artifact-collection complexity. Not included in the initial host backend; reconsider separately if stronger containment is required.
- **Natural-language refusal detection:** unreliable and cannot establish authorization; explicit typed handoffs are required.
- **Detached worker processes:** fragile ownership and restart behavior; use a persisted queue and supervised runner.

## Consequences

Explicit delegation adds local packaging, runtime, and policy work but preserves the existing orchestration workflow. DeepSeek charges remain separate. The minimal researcher analyzes supplied text; active tooling and autonomous scanning are outside v1. The host backend uses account permissions: worktrees separate changes but do not contain arbitrary code or restrict access to account-readable files, shared Git metadata, or host networking. Controlled configuration, review, approvals, and recovery support the workflow without promising a security sandbox. Version/capability details remain subject to the M0 verification gate.
