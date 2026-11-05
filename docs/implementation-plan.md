# Implementation plan

Note: hook-based automatic research, price estimates, leases, and the tables behind them were later removed as unused; see [operations](operations.md) for current behavior.

Status: implementation baseline delivered with offline validation; this document retains the original release acceptance backlog. Milestones are ordered by dependency, not calendar estimates. Real integration acceptance is **not** implied by implementing an adapter.

| Milestone | Current evidence | Remaining release gate |
| --- | --- | --- |
| M0 | Pinned libraries/lock; Claude 2.1.309 MCP connection; OpenCode 2.2.5 real config/events with mock provider | Real hook payload; live API capability smoke |
| M1 | Typed config/contracts, outbound snapshots, consultant/review CLI + stdio MCP, bounded SDK adapter, private history | Opt-in paid consultation; effort settings intentionally unsupported |
| M2 | SQLite v1 migration, durable queue/events/artifacts/accounting, shared concurrency, runner lock/leases/heartbeat, idempotency, cancellation, restart interruption, retention | Broader host crash/process ownership exercise; no blind retry |
| M3 | Dedicated worktrees, scoped config, patch/verification evidence; local OpenCode 2.2.5 native edit and process stop checked | Live provider worker; other supported hosts; adapter disabled by default, enabled for verified local pin |
| M4 | Trusted task/scope registry, hash/expiry-bound interactive approvals, local hooks/dedup, passive report validation | Real installed hook fixture and opt-in live research; auto mode remains disabled by default |
| M5 | Doctor, service commands, export/delete/prune, operations/rollback, CI definition; local launchd install/heartbeat | Service removal, Linux install and CI matrix on real hosts; live benchmarks and owner review outcomes |

See [release notes](release-notes.md), [compatibility](compatibility.md), and [operations](operations.md).

## Requirements and release sequence

Preserve Claude Code subscription authentication. Provide three distinct roles with separate permissions, direct DeepSeek billing, explicit context selection, durable jobs, cost visibility, and reviewable results. Keep remote hosting, dashboards, and general-purpose model gateways outside the initial scope. Ship explicit consultation first; enable autonomous coding and automatic research only after their enforcement gates pass.

Dependency chain: M0 → M1 → M2 → M3 → M4 → M5. Research policy/schema work may be developed after M2 independently of the worker adapter, but automatic dispatch still requires the M4 policy tests.

## M0 — Verify integration assumptions

- Record Python, Claude Code, Git, OpenCode, SDK, host toolchains, and FastMCP versions in a compatibility matrix. Pin dependencies and the OpenCode executable version after a small compatibility spike.
- Confirm DeepSeek endpoint/model/effort capabilities, response block preservation, token/cache reporting, and OpenCode headless event format. Use fake responses by default; make a minimal live call only during an explicitly enabled smoke test.
- Verify local stdio MCP registration and actual hook payloads for installed Claude Code. Test persistence of the separate runner after an MCP disconnect.
- Verify host OpenCode execution in a dedicated worktree, local toolchain/dependency access, effective permission configuration, and process-group cancellation. Record that execution uses account permissions and has no bridge-enforced filesystem or network sandbox.

Deliver `docs/compatibility.md`, sanitized event fixtures, and decisions for any failed assumptions. Acceptance: reproducible evidence exists for the chosen versions; live checks are clearly distinguished from mocks.

## M1 — Consultant foundation and MCP MVP

- Add `pyproject.toml`, lockfile, src package, typed settings, CLI, Pydantic contracts, and FastMCP entry point. Add Ruff/type checking and focused pytest coverage.
- Implement provider adapter with explicit timeouts, bounded transient retries, capability validation, continuation, structured review parsing, and usage accounting.
- Implement repository allowlist and outbound context collector with path, symlink, secret-file, size, and inline-content checks. Persist private consultation history and apply retention.
- Expose `deepseek_ask`/`deepseek_review`; document direct orchestrator use and optional native Claude coordinator.

Acceptance: Claude reviews an explicitly selected diff and receives structured findings and usage. No source files change, no Claude authentication settings change, and no API key appears in config, output, or logs. Fake-provider tests cover malformed output, timeout/429, missing usage, continuation block preservation, and forbidden context paths. Live smoke is separate and opt-in.

## M2 — Durable control plane

- Implement SQLite migrations, jobs/events/artifact tables, local runner, leases/heartbeat, bounded queue claims, idempotency, cancellation, deadlines, and restart reconciliation.
- Add status/result/cancel tools, job CLI, private artifact storage, atomic result publication, retention, and safe resource cleanup.
- Add accounting with actual model IDs, token/cache usage, versioned prices, nullable estimates, concurrency/time/token limits, and accepted/rejected review metadata.

Acceptance: a fake job survives MCP restart; runner restart marks interrupted work without blind reexecution. Two competing clients cannot claim the same job or exceed capacity. Test cancellation/completion races, migration rollback/recovery, missing artifacts, unknown prices, and orphan cleanup. A stopped runner produces queued jobs and an actionable `doctor` failure rather than spawning untracked processes.

## M3 — Host coding worker MVP

- Implement repository/base-SHA validation, generated branches/dedicated worktrees, explicit dependency preparation, and deterministic patch artifacts including new, deleted, and binary files.
- Implement a pinned host OpenCode subprocess adapter with JSON events, per-job configuration, environment allowlisting, scoped application permissions, deadlines, and bounded output. Use local files/toolchains directly; identify shared caches and local-service dependencies explicitly.
- Add independently executed host verification and bridge-generated handoffs. Record tool versions, commands, exit status, partial output, and usage. Track worker and verification process groups with ownership information for cancellation and restart reconciliation.

Acceptance: a fixture task edits code and adds tests in its dedicated worktree using the host toolchain; the original checkout and its uncommitted changes remain unchanged in the test. Claude receives the patch and independently observed verification evidence. Test working-directory selection, environment filtering, unexpected configuration, missing executable, local-file/dependency access, shared-resource contention, timeouts, cancellation and PID reuse, stale refs, name collisions, oversized output, new/binary files, and modified tests. No automatic merge, push, or deployment occurs. These checks validate intended behavior; they do not prove containment of a malicious host process.

## M4 — Passive security researcher and escalation

- Implement the researcher prompt/result contract, trusted scope registry, explicit handoff envelope, policy engine, approvals CLI, and hash/expiry binding.
- Implement bounded hook ingestion for installed/supported events. Persist technical handoffs and pending approvals before returning; use the existing runner for API work.
- Add project research-state support as untrusted context. Deduplicate Stop/SubagentStop, enforce one automatic escalation per trusted task revision, and keep API failures telemetry-only initially.

Acceptance: eligible technical blockers automatically enqueue passive research; sensitive/ambiguous cases make zero provider calls until owner approval. Permission/safety boundaries never reroute. An API failure never invents a task. All scenarios in [security escalation](security-escalation.md) pass offline; capture a real hook payload and an opt-in live research response before claiming end-to-end compatibility.

## M5 — Operational release

- Implement `doctor`, service-manager runner installation/removal, safe hook/settings merge instructions, redacted diagnostics, artifact export/delete, and recovery/runbooks.
- Add CI for lint/types, contract and unit tests, fixture Git integration, and fake provider/harness tests. Add host-worker smoke checks for each supported operating system; CI does not establish compatibility with every local toolchain or permission configuration.
- Document budgets, data transmission, supported versions, review/integration workflow, and how to disable hooks/stop the runner while preserving artifacts.
- Benchmark a small analysis task, isolated implementation, and passive investigation. Measure elapsed time, actual tokens/cost estimate, Claude review effort, and acceptance outcome.

Acceptance: another local installation can reproduce setup and rollback from documentation. No secrets or runtime artifacts enter Git. Offline CI uses no paid API. Release notes explicitly list unrun live checks and unsupported active research capabilities.

## Initial implementation slices

1. M0 compatibility report and fixtures.
2. M1 settings/contracts/context collector and mocked provider CLI.
3. M1 MCP tools and one opt-in consultation smoke test.
4. M2 persistence, runner, lifecycle and recovery.
5. M3 host/worktree execution, process lifecycle, verification, and handoff.
6. M4 trusted scopes/approval tests, then hooks and researcher.
7. M5 installation, runbooks, compatibility evidence and benchmark.

Each slice should be independently reviewable. Introduce tests alongside behavior; the CLI/server/runner now exist, while live compatibility gates above remain explicit.

## Unresolved decisions

Choose exact dependency versions and effort mappings at M0. Validate host process management and the selected OpenCode permission/configuration behavior. Decide initial repositories, trusted research scopes, sensitive-data rules, and which operating-system credential-store integrations should complement environment variables. Select verification profiles and permitted dependency preparation per repository. Dollar thresholds and retention need deployment-specific tuning; defaults are proposals rather than measured requirements. Automatic quota-based handoff is outside the first release.
