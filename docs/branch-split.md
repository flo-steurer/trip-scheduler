# Clean and experimental versions

- `main`: trip creation and sharing, availability calendars, personal minimum attendance, ranked date windows, villa capacity and costs, proposals, votes, and booking interest.
- `crazy`: the full experimental app, including Beermarkets, Beer-clicker, chips, karma leaderboards, World Cup synchronization, daily rewards, and the current Beermarket refactor. The preservation commit is `6be20ea`.

Continue ordinary trip-planning development on `main`; continue game experiments on `crazy`. Bring shared fixes across with individual cherry-picks so game features do not return to `main` through a whole-branch merge.

## Database separation

Git branches preserve code, not SQLite data. The clean schema removes the game tables and the participant chip/karma columns. Applying its migrations preserves trip IDs and share URLs, participants, availability, proposals, votes, and booking interest, but deletes game data. Reversing the migrations cannot recover deleted game records.

Keep an untouched database for `crazy` and migrate a separate copy for `main`. Local development can select a file explicitly:

```sh
SQLITE_PATH="$PWD/data/clean.sqlite3" .venv/bin/python manage.py migrate
SQLITE_PATH="$PWD/data/clean.sqlite3" .venv/bin/python manage.py runserver
```

Those commands create an empty database unless you first copy an existing one to `data/clean.sqlite3`. When switching to `crazy`, select its separate original or backup database with `SQLITE_PATH`. Never point `crazy` at the cleaned database.

For Docker, use separate checkouts, each with its own `data/` directory and `.env`. The container database is always `./data/trip-scheduler.sqlite3` within that checkout; shell `SQLITE_PATH` overrides apply only to local Python commands. Use distinct Compose project names and ports if running both versions simultaneously.

## Upgrading an existing Docker installation

1. Stop the existing app and workers with `docker compose down --remove-orphans`. Use the same Compose project name as the running installation. This stops the old `world-cup-sync` and `beercoin-rewards` workers before any schema changes.
2. Back up `data/trip-scheduler.sqlite3` while the app and workers are stopped. Keep that backup outside the clean checkout; use a separate copy for the `crazy` installation. For non-Docker development, back up the file selected by `SQLITE_PATH` or the default `db.sqlite3`.
3. Select `main`, then run `docker compose up --build -d --remove-orphans`. The app applies the cleanup migrations before Gunicorn starts. Only the trip scheduler service remains.
4. Check a saved trip URL, availability, date rankings, and proposals. The game pages and APIs now return 404.

For a local Python deployment, stop old workers, back up the database, run `manage.py migrate` against the clean copy, and rebuild static assets with `manage.py collectstatic --clear --noinput` before restarting the app.

The `world_cup` package remains only as migration history with a final table-removal migration. It has no runtime models, views, admin, provider, settings, or commands. Keep this migration-only app registered until a future migration squash provides an upgrade path that no longer needs it. Historical scheduler migrations also remain so existing installations can upgrade normally.

To return to the experimental version, stop the clean app and start `crazy` against its original database or the pre-cleanup backup. Switching Git branches alone does not restore game data. Changes made after the database split stay in the database where they were made.
