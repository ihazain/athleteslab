# Deploying Athlete Lab Pro

One server, one command: the application (gunicorn), PostgreSQL, Redis, Celery
worker and beat, and Caddy, which gets the HTTPS certificate on its own and
serves the static and uploaded files. Everything is configured in `.env`.

## What you need

* A Linux server (2 GB RAM or more) with Docker Engine including the compose
  and buildx plugins (the packages from <https://docs.docker.com/engine/install/>
  have both). Check with `docker compose version` and `docker buildx version`.
* A domain whose DNS record points to the server, ports 80 and 443 open.
* This repository on the server: `git clone` it and check out the release.

## First start

```sh
cd deploy
./init-env.sh training.example.org    # writes .env with fresh secrets
docker compose up -d --build
docker compose logs -f web            # wait for "Using gunicorn on port 8000"
```

The first start creates the database and loads the exercises, this takes a few
minutes. Then open `https://training.example.org`.

**Change the admin password at once.** The first start creates the user
`admin` with the password `adminadmin`:

```sh
docker compose exec web python3 manage.py changepassword admin
```

Then look through `.env`:

* `ENABLE_EMAIL` and the `EMAIL_*` values. Without e-mail nobody can reset a
  forgotten password.
* `ALLOW_REGISTRATION`: athletes create their account themselves and the coach
  invites them. Set it to `False` when everybody is in, then
  `docker compose up -d`.
* `TIME_ZONE`.

`.env` holds the secrets (`SECRET_KEY`, the JWT keys, the database password).
It is not in git. Keep a copy in a password manager: without `SECRET_KEY` and
the JWT keys all sessions and app logins end after a restore.

## Backups

`./backup.sh` writes a database dump and an archive of the uploaded files to
`deploy/backups/` and deletes files older than `BACKUP_KEEP_DAYS`. Run it every
night as the user who owns the checkout:

```cron
30 2 * * * /srv/athleteslab/deploy/backup.sh >> /var/log/athleteslab-backup.log 2>&1
```

A backup on the same server is lost with the server. Set `BACKUP_REMOTE` to an
rsync target on another machine, and `BACKUP_GPG_RECIPIENT` to encrypt the
files for your GnuPG key before they leave the server.

Check regularly that a backup can be read back. This loads it into a scratch
database and does not touch the live one:

```sh
./restore-test.sh backups/db-<stamp>.dump
```

To go back to a backup (everything entered since then is lost, the script asks
for the domain first and takes a fresh backup before it starts):

```sh
./restore.sh backups/db-<stamp>.dump backups/media-<stamp>.tar.gz
```

## Updates

```sh
./backup.sh
git pull            # or: git checkout <tag>
docker compose up -d --build
```

The server applies the database migrations on start. To go back: check out the
previous version, `docker compose up -d --build`, and restore the backup taken
before the update if the newer version had changed the database.

## Useful commands

```sh
docker compose ps                         # state of the services
docker compose logs -f web                # application log
docker compose exec web python3 manage.py check --deploy
docker compose exec web python3 manage.py createsuperuser
docker compose down                       # stop, the data stays in the volumes
```

`check --deploy` reports one warning (security.W001): the security headers are
set by Caddy (`Caddyfile`), not by Django.

## Trying it on your own machine

`./init-env.sh localhost`, then set `HTTP_PORT` and `HTTPS_PORT` in `.env` to
free ports (e.g. 8081 and 8444) and `SITE_URL` and `CSRF_TRUSTED_ORIGINS` to
`https://localhost:8444`. Caddy uses a self-signed certificate for localhost,
the browser warns once.

## Not part of this setup

* PowerSync (offline sync of the mobile app). The web application does not
  need it.
* Monitoring. At least add an uptime check on `https://<domain>/` from outside.
* The legal side: imprint, privacy policy, processor agreement with the
  hoster, consent for athletes under 18. See PROJECTINSTRUCTION.md, phase E.
