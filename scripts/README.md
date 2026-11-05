# Developer scripts

- `export_schemas.py`: regenerate JSON schemas from versioned Pydantic models.
- `live_smoke.py`: tiny paid consultation; requires both `DEEPSEEK_BRIDGE_LIVE=1` and `--allow-paid-call`. Never part of offline CI.

Use the CLI for runner supervision, doctor, hooks, owner approvals, retention, export, deletion, and user service management. See docs/operations.md.
