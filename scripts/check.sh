#!/usr/bin/env bash
# Contrôles qualité obligatoires (constitution, section « Workflow et contrôles qualité »).
# Usage : scripts/check.sh   (nécessite PostgreSQL joignable via DATABASE_URL)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> ruff"
uv run ruff check .
uv run ruff format --check .

echo "==> migrations à jour"
uv run python manage.py makemigrations --check --dry-run

echo "==> réversibilité des migrations (aller-retour sur une base vide)"
CHECK_DB="itsm_migrations_check"
BASE_URL="${DATABASE_URL:-postgres://itsm:itsm@localhost:5432/itsm}"
CHECK_URL="${BASE_URL%/*}/${CHECK_DB}"
uv run python - "$BASE_URL" "$CHECK_DB" <<'PY'
import sys, psycopg
url, name = sys.argv[1], sys.argv[2]
with psycopg.connect(url, autocommit=True) as conn:
    conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    conn.execute(f'CREATE DATABASE "{name}"')
PY
DATABASE_URL="$CHECK_URL" uv run python manage.py migrate --noinput -v 0
for app in inventory helpdesk directory core; do
  DATABASE_URL="$CHECK_URL" uv run python manage.py migrate "$app" zero --noinput -v 0
done
DATABASE_URL="$CHECK_URL" uv run python manage.py migrate --noinput -v 0

echo "==> tests et couverture"
uv run pytest --cov=src --cov-report=term-missing:skip-covered -m "not e2e and not perf"

echo "==> vulnérabilités des dépendances"
uv export --frozen --no-hashes --format requirements-txt > /tmp/itsm-requirements.txt
uv run pip-audit --strict -r /tmp/itsm-requirements.txt --disable-pip

echo "OK : tous les contrôles passent."
