#!/usr/bin/env bash
# Proves that a database backup can be restored, without touching the live
# database: loads it into a scratch database, counts the users, drops it again.
# Usage: ./restore-test.sh backups/db-<stamp>.dump[.gpg]
set -euo pipefail
cd "$(dirname "$0")"
source ./_env.sh

file="${1:?Usage: $0 backups/db-<stamp>.dump[.gpg]}"
scratch=restore_check

read_dump() {
    if [[ "$file" == *.gpg ]]; then gpg --batch --decrypt "$file"; else cat "$file"; fi
}

psql() { docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$DJANGO_DB_USER" "$@"; }

psql -d postgres -q -c "DROP DATABASE IF EXISTS $scratch" -c "CREATE DATABASE $scratch"
trap 'psql -d postgres -q -c "DROP DATABASE IF EXISTS $scratch"' EXIT
read_dump | docker compose exec -T db pg_restore -U "$DJANGO_DB_USER" -d "$scratch" --no-owner --exit-on-error

users="$(psql -d "$scratch" -Atc 'SELECT count(*) FROM auth_user')"
teams="$(psql -d "$scratch" -Atc 'SELECT count(*) FROM teams_team')"
echo "Restore works: $users users and $teams teams in $file"
