#!/usr/bin/env bash
# Writes .env from env.example with fresh secrets. Usage: ./init-env.sh <domain>
set -euo pipefail
cd "$(dirname "$0")"

domain="${1:-}"
if [[ -z "$domain" ]]; then
    echo "Usage: $0 <domain>   (e.g. $0 training.example.org, or localhost for a test)" >&2
    exit 1
fi
if [[ -e .env ]]; then
    echo ".env already exists, not overwriting it. Its secrets are in use by the running stack." >&2
    exit 1
fi

random() {
    python3 -c "import secrets; print(secrets.token_urlsafe($1))"
}

# The JWT keys are generated with the application image
if ! docker image inspect athleteslab/server:local >/dev/null 2>&1; then
    echo "Building the image (takes a few minutes the first time)..."
    DJANGO_DB_USER=x DJANGO_DB_PASSWORD=x DJANGO_DB_DATABASE=x SITE_DOMAIN=x \
        docker compose build web
fi
keys="$(docker run --rm -e DJANGO_SETTINGS_MODULE=settings.ci athleteslab/server:local \
    python3 manage.py generate-jwt-keys --kid athleteslab --no-color)"
private="$(grep '^JWT_PRIVATE_KEY=' <<<"$keys" | cut -d= -f2-)"
public="$(grep '^JWT_PUBLIC_KEY=' <<<"$keys" | cut -d= -f2-)"
if [[ -z "$private" || -z "$public" ]]; then
    echo "Could not generate the JWT keys." >&2
    exit 1
fi

umask 077
sed -e "s|__SITE_DOMAIN__|$domain|g" \
    -e "s|__SECRET_KEY__|$(random 50)|" \
    -e "s|__DB_PASSWORD__|$(random 24)|" \
    -e "s|__JWT_PRIVATE_KEY__|$private|" \
    -e "s|__JWT_PUBLIC_KEY__|$public|" \
    env.example > .env
echo "Wrote $(pwd)/.env (readable by you only). Next: docker compose up -d"
