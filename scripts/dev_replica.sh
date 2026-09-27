#!/usr/bin/env bash
# Cloud dev muhitda lokal PostgreSQL + 6 asosiy hujjat nusxasi (Supabase bilan bir xil ma'lumot).
# Ishlatish:  bash scripts/dev_replica.sh   → so'ng: export SUPABASE_DB_URL=postgresql://postgres@127.0.0.1:5433/soliq_replica
set -euo pipefail
cd "$(dirname "$0")/.."
PGBIN=$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)
PGDATA=/var/tmp/pgdata
id postgres >/dev/null 2>&1 || useradd -m postgres
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  mkdir -p "$PGDATA" && chown postgres "$PGDATA"
  su postgres -c "$PGBIN/initdb -D $PGDATA -A trust -U postgres >/dev/null"
fi
if ! "$PGBIN/pg_isready" -h 127.0.0.1 -p 5433 >/dev/null 2>&1; then
  rm -f "$PGDATA/postmaster.pid"
  su postgres -c "$PGBIN/pg_ctl -D $PGDATA -o '-k /var/tmp -p 5433 -h 127.0.0.1' -l $PGDATA/log start" >/dev/null
  sleep 2
fi
pip install -q -r requirements-dev.txt
psql -h 127.0.0.1 -p 5433 -U postgres -qc "DROP DATABASE IF EXISTS soliq_replica" -c "CREATE DATABASE soliq_replica"
export SUPABASE_DB_URL=postgresql://postgres@127.0.0.1:5433/soliq_replica
python -m app.database.migrate
for id in $(python -c "from app.collector.core_documents import approved_documents as a; print(' '.join(d.lex_id for d in a()))"); do
  LOG_LEVEL=WARNING python -m app.collector.initial_load --yes -- "$id" | grep '^Import:'
done
echo "Tayyor. export SUPABASE_DB_URL=$SUPABASE_DB_URL"
echo "Testlar: TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5433/postgres python -m pytest"
