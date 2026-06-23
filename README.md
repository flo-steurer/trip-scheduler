# Trip Scheduler

A small, self-hosted group trip availability tool. Create a trip, share its private URL over your VPN, and let each person mark dates as available, maybe, or unavailable. The app ranks windows by confirmed attendance, then possible attendance.

## Run with Docker

1. Create a local configuration file: `cp .env.example .env`.
2. Set a long `DJANGO_SECRET_KEY`. For VPN users, set `PUBLIC_BASE_URL` to the exact address they will open (for example `http://100.64.0.10:8000`) and add its hostname/IP to `DJANGO_ALLOWED_HOSTS`.
3. Start it: `docker compose up --build`.
4. Open `http://localhost:8000` (or the configured `PORT`). SQLite data is persisted in `./data`.

Docker Compose also runs a background worker that gives every current participant 10 Beer Chips once per UTC calendar day. Each daily grant is recorded, so restarting the worker cannot credit the same day twice.

For a reverse proxy using HTTPS, also set `DJANGO_SECURE_SSL_REDIRECT=true` and set `CSRF_TRUSTED_ORIGINS` to the public origin, for example `https://trips.internal.example`.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
.venv/bin/python manage.py test
```

This is intentionally access-free: anyone who has a trip URL can see the group’s responses and can submit under any display name. Use it only on your trusted private network.

If an outside user gets a 404 before any request appears in `docker compose logs`, their VPN/reverse-proxy route is not reaching this container. Confirm that `http://<server-vpn-address>:8000/` is reachable first; if a reverse proxy is in front, forward its site to `http://127.0.0.1:8000` and use that public origin as `PUBLIC_BASE_URL`.

Do not expose Gunicorn directly to the public internet. Place it behind a VPN or a reverse proxy (such as Caddy or Nginx) with HTTPS and request time limits. The container uses threaded Gunicorn workers so one slow/incomplete client connection does not block every availability update, but a reverse proxy remains the proper network boundary.

## Optional 2026 World Cup Beermarkets

Set `FOOTBALL_DATA_API_KEY` and `WORLD_CUP_SYNC_ENABLED=true` in `.env`, then restart Compose. The `world-cup-sync` service creates and settles markets for every World Cup fixture. It polls every 20 minutes by default and uses the football-data.org token only in the background container.

After the tournament, set `WORLD_CUP_SYNC_ENABLED=false`, remove the `world-cup-sync` service and the `world_cup` Django app in a cleanup change. Generated settled markets remain ordinary historical Beermarket records; manual markets are never modified by the integration.
