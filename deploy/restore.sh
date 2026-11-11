#!/usr/bin/env bash
# Replaces the live database, and optionally the uploaded files, by a backup.
# Everything entered since that backup is lost.
# Usage: ./restore.sh backups/db-<stamp>.dump[.gpg] [backups/media-<stamp>.tar.gz[.gpg]]
set -euo pipefail
cd "$(dirname "$0")"
source ./_env.sh

db_file="${1:?Usage: $0 backups/db-<stamp>.dump[.gpg] [backups/media-<stamp>.tar.gz[.gpg]]}"
media_file="${2:-}"

read_file() {
    if [[ "$1" == *.gpg ]]; then gpg --batch --decrypt "$1"; else cat "$1"; fi
}

echo "This replaces the database of $SITE_DOMAIN by $db_file."
read -r -p "Type the domain to continue: " answer
[[ "$answer" == "$SITE_DOMAIN" ]] || { echo "Aborted."; exit 1; }

# A fresh backup first, so this step can be undone
./backup.sh

docker compose stop web celery_worker celery_beat
psql() { docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$DJANGO_DB_USER" "$@"; }
psql -d postgres -q -c "DROP DATABASE $DJANGO_DB_DATABASE" -c "CREATE DATABASE $DJANGO_DB_DATABASE"
read_file "$db_file" | docker compose exec -T db pg_restore -U "$DJANGO_DB_USER" \
    -d "$DJANGO_DB_DATABASE" --no-owner --exit-on-error

docker compose start web
if [[ -n "$media_file" ]]; then
    read_file "$media_file" | docker compose exec -T web tar -xzf - -C /home/wger
fi
docker compose exec -T cache redis-cli flushall >/dev/null
docker compose start celery_worker celery_beat
echo "Restored. The server applies newer migrations on its next start: docker compose restart web"
