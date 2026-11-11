#!/usr/bin/env bash
# Dumps the database and the uploaded files into ./backups. Run it from cron.
set -euo pipefail
cd "$(dirname "$0")"
source ./_env.sh

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p backups
umask 077

store() {
    # Reads stdin, writes backups/$1, encrypted if a recipient is set
    if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
        gpg --batch --yes --encrypt --recipient "$BACKUP_GPG_RECIPIENT" --output "backups/$1.gpg"
        echo "backups/$1.gpg"
    else
        cat > "backups/$1"
        echo "backups/$1"
    fi
}

db_file="$(docker compose exec -T db pg_dump -U "$DJANGO_DB_USER" -Fc "$DJANGO_DB_DATABASE" \
    | store "db-$stamp.dump")"
media_file="$(docker compose exec -T web tar -czf - -C /home/wger media | store "media-$stamp.tar.gz")"

# An empty dump means the backup did not work
for file in "$db_file" "$media_file"; do
    if [[ ! -s "$file" ]]; then
        echo "Backup failed: $file is empty" >&2
        exit 1
    fi
done
echo "Wrote $db_file and $media_file"

find backups -type f -mtime "+${BACKUP_KEEP_DAYS:-14}" -delete

if [[ -n "${BACKUP_REMOTE:-}" ]]; then
    rsync -a backups/ "$BACKUP_REMOTE/"
    echo "Copied to $BACKUP_REMOTE"
fi
