# SQLite migrations

The initial version-1 schema is embedded in `src/deepseek_bridge/database.py` and applied inside one `BEGIN IMMEDIATE` transaction, including `PRAGMA user_version`. A failed migration rolls back all DDL; concurrent initializers serialize. A newer schema is rejected. The database uses WAL, foreign keys, and a busy timeout. Future releases must add numbered forward migrations rather than modifying an already-released version-1 schema.
