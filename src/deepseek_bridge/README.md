# Planned source package

Scaffold only. Add executable modules in the implementation milestones rather than shipping empty functions that appear operational.

| Module | Responsibility |
| --- | --- |
| `cli.py`, `server.py` | CLI and FastMCP stdio adapters |
| `settings.py`, `contracts.py` | Typed config and versioned request/report models |
| `context.py`, `policy.py`, `approvals.py` | Context selection, trusted scopes, owner approval |
| `consultant.py`, `review.py`, `research.py` | Role-specific provider services |
| `provider.py` | Direct DeepSeek SDK adapter and capability mapping |
| `jobs.py`, `runner.py` | Durable lifecycle, leases, supervision, cancellation |
| `worktrees.py`, `sandbox.py`, `opencode.py` | Host Git management, containers, worker events |
| `relay.py`, `verification.py` | Narrow worker API access and independent tests |
| `hooks.py` | Event validation, policy evaluation, deduplication |
| `database.py`, `accounting.py`, `artifacts.py` | Persistence, usage, safe output publication |

Dependencies flow from adapters to services and domain contracts. Provider, subprocess, clock, and filesystem boundaries must be injectable for offline tests.
