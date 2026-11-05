# 0.1.0 implementation baseline

Note: hook-based automatic research, price estimates, leases, and the tables behind them were later removed as unused; see [operations](operations.md) for current behavior.

This release implements the local workflow and validates it offline. It does not claim completion of the plan's live release gates.

Implemented: typed settings/contracts and generated schemas; CLI and seven FastMCP stdio tools; direct DeepSeek Anthropic SDK adapter; selected-context/path/symlink/secret/byte checks; structured reviews and continuation blocks; private retained consultation history; nullable token/cache usage and versioned estimates; transactional SQLite v1 migration, durable jobs/events/approvals/artifacts; provider reservations, concurrency/resource scheduling, idempotency, deadlines/cancellation, runner singleton/heartbeat/leases and interruption recovery; atomic checksummed artifacts/export/prune/delete; gated host OpenCode execution and independent verification in generated worktrees; binary/new/deleted patches; trusted task/scope policy, interactive owner approvals and bounded local hooks; doctor, explicit user service installation commands, CI and recovery documentation.

The default is explicit consultation with manual research proposals. Coding and automatic research remain disabled until the owner records real compatibility evidence. Worktrees separate changes; processes retain host account filesystem/network authority. The model's shell permission is denied; host dependency preparation and verification use trusted configuration argv. Active research, autonomous browsing/scanning/exploit execution, automatic merge/push/deploy, remote hosting, dashboards, and model gateways are unsupported.

## Observed validation

**77 tests passed**, with Ruff lint/format, mypy, and source/wheel builds passing. On macOS arm64 with Python 3.14.7, Git 2.54.0, Anthropic SDK 0.72.0 and FastMCP 2.13.0, offline tests exercise provider mock transport, context and authorization failures, preserved continuation blocks, nullable usage/prices, competing claims, cancellation/completion and claim/cancel races, schema rollback/concurrent initialization, artifact integrity, ownership/PID reuse, hook dedup/approval changes, fixture host edits and tests, binary patches, and separate-runner survival after actual stdio MCP disconnection. See compatibility.md for the exact checked/unrun matrix. FastMCP's pinned dependency stack emits Authlib deprecation warnings; they do not fail the tests.

CI defines Python 3.12/3.14 on macOS/Linux, but these remote jobs were not run by this implementation session. Real DeepSeek, Claude Code, OpenCode, service-manager installation, and additional host toolchains remain untested. No paid call or real credential was used.

## Operational limits

Explicit effort settings are rejected until live-verified. The owner chooses the OpenCode version pin after a real compatibility spike; there is no invented supported version. Missing model IDs, token/cache counts, prices, and parsed test counts remain unknown. Verification can pass, fail, or be unknown when the workspace changed during the run. Reports retain actual argv/log/exit/hash evidence; the owner may configure separate tool-version commands. Verification executes potentially changed source/tests and still needs review.

The runner never automatically repeats a charge-ambiguous request or interrupted job. Process ownership uncertainty requires manual recovery, and a small process-start/persistence crash gap remains. Detached descendants are outside the process-group guarantee. Retention is explicit via `prune`, with dirty worktrees retained for review; it is not secure erasure. Escalation tombstones remain after artifact deletion. OS credential stores require an external private launcher. Request hashes bind research scope, content, model, and limits; software already executing as the owner is outside this authorization boundary.

Live benchmarks must still measure elapsed time, actual tokens/cost, Claude review effort, and accepted/rejected outcomes for analysis, coding, and passive research. The following are **offline fixture timings**, not performance or cost claims:

| Fixture | Measured call duration | Tokens / billing / review |
| --- | --- | --- |
| Explicit consultation analysis | 0.0022 s | Synthetic 12 input / 7 output; no bill; no owner review |
| Dedicated worktree implementation + independent pytest verification | 0.82 s | Synthetic 10 input / 5 output; no bill; automated assertions only |
| Passive hook research + durable runner | 0.12 s | Synthetic provider usage; no bill; no owner review |
| Separate runner finishing after stdio MCP disconnect | 1.34 s | Synthetic host harness; no bill; automated assertions only |

Worker/research/disconnect timings came from a local `pytest -q --durations=10` run; setup is excluded. Analysis was one fake-provider `Service.ask` timed with `time.perf_counter` after service initialization. Reproduce with the same tests instead of treating these as production benchmarks.
