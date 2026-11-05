# SQLite migrations

Numbered schemas are embedded in `src/deepseek_bridge/database.py` and applied in order inside one `BEGIN IMMEDIATE` transaction, including `PRAGMA user_version`. A failed migration rolls back all DDL; concurrent initializers serialize. A newer schema is rejected. The database uses WAL, foreign keys, and a busy timeout. Version 2 drops the unused `jobs.lease` column and the `api_usage`, `escalations`, and `telemetry` tables. Future releases must add numbered forward migrations rather than modifying a released schema.
