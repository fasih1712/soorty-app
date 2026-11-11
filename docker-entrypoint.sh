#!/bin/sh
# Runs on every container start. All steps are safe to repeat.
set -e

echo "[entrypoint] applying Django migrations..."
python manage.py migrate --noinput

echo "[entrypoint] syncing RBAC page registry + baseline roles..."
python manage.py sync_rbac_pages || echo "[entrypoint] WARNING: sync_rbac_pages failed (continuing)"
python manage.py seed_baseline_roles || echo "[entrypoint] WARNING: seed_baseline_roles failed (continuing)"

exec "$@"
