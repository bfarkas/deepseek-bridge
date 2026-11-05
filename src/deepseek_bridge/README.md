# Source layout

CLI and FastMCP adapters share `Service`; credentials are supplied only to the direct provider or explicitly configured host adapter.

| Module | Responsibility |
| --- | --- |
| `cli.py`, `server.py`, `service.py` | Local CLI, seven stdio tools, application facade |
| `settings.py`, `contracts.py`, `errors.py` | Typed owner configuration, versioned contracts, sanitized errors |
| `context.py`, `policy.py`, `research.py`, `hooks.py` | Explicit snapshots, private trusted scopes/tasks, owner approval and passive dispatch |
| `consultant.py`, `provider.py`, `accounting.py` | Consultation/review, direct SDK calls, nullable usage and versioned estimates |
| `database.py`, `runner.py`, `artifacts.py` | Atomic SQLite migrations/lifecycle/leases, separate runner, checksummed publication |
| `worktrees.py`, `opencode.py`, `processes.py`, `worker.py` | Dedicated Git worktrees, gated host adapter, process ownership, independent verification/handoff |
| `maintenance.py`, `services.py` | Retention/export/delete and explicit user service installation |

Provider boundaries are injectable. Tests use real fixture Git repositories and POSIX processes with fake provider/harness responses. Host execution is not a filesystem/network sandbox. Live integration evidence is tracked in docs/compatibility.md.
