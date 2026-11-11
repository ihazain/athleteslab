# Reads the settings the scripts need from .env. The file is not sourced as a
# whole: values may contain spaces, which the shell would run as commands.
env_value() {
    grep -E "^$1=" .env | tail -n 1 | cut -d= -f2-
}

if [[ ! -r .env ]]; then
    echo "No .env here, run ./init-env.sh first." >&2
    exit 1
fi

SITE_DOMAIN="$(env_value SITE_DOMAIN)"
DJANGO_DB_USER="$(env_value DJANGO_DB_USER)"
DJANGO_DB_DATABASE="$(env_value DJANGO_DB_DATABASE)"
BACKUP_KEEP_DAYS="$(env_value BACKUP_KEEP_DAYS)"
BACKUP_GPG_RECIPIENT="$(env_value BACKUP_GPG_RECIPIENT)"
BACKUP_REMOTE="$(env_value BACKUP_REMOTE)"
