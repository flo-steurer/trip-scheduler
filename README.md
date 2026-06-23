# Trip Scheduler

A small, self-hosted group trip availability tool. Create a trip, share its private URL over your VPN, and let each person mark dates as available, maybe, or unavailable. The app ranks windows by confirmed attendance, then possible attendance.

## Run with Docker

1. Create a local configuration file: `cp .env.example .env`.
2. Set a long `DJANGO_SECRET_KEY` and add the hostname/IP people use to `DJANGO_ALLOWED_HOSTS`.
3. Start it: `docker compose up --build`.
4. Open `http://localhost:8000` (or the configured `PORT`). SQLite data is persisted in `./data`.

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

