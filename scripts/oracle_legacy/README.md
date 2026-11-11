# Oracle-era scripts (not used by the app)

The app now runs on **PostgreSQL** (see `postgres/` and `core/db.py`).

Everything in this folder was written against the old Oracle database and is
kept only for history and reference:

- `Tables/` holds the original Oracle DDL and migration scripts. The PostgreSQL
  equivalent is `postgres/01_schema.sql` plus `postgres/02_seed.sql`.
- `*.py` are one-off diagnostic and fix scripts that used `oracledb`. They will
  not run against PostgreSQL as they are.
