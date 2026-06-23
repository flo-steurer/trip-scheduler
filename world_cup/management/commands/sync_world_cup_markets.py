import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.utils import OperationalError
from django.utils import timezone

from world_cup.provider import FootballDataClient, FootballDataError
from world_cup.services import sync_world_cup


class Command(BaseCommand):
    help = "Create and settle automatic 2026 World Cup Beermarkets."

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", help="Refresh the full tournament schedule.")
        parser.add_argument("--watch", action="store_true", help="Run continuously at the configured interval.")
        parser.add_argument("--interval", type=int, help="Override the polling interval in seconds.")

    def handle(self, *args, **options):
        if not settings.WORLD_CUP_SYNC_ENABLED:
            self.stdout.write("World Cup sync is disabled.")
            return
        if not settings.FOOTBALL_DATA_API_KEY:
            raise CommandError("FOOTBALL_DATA_API_KEY must be configured when World Cup sync is enabled.")
        interval = options["interval"] or settings.WORLD_CUP_SYNC_INTERVAL_SECONDS
        if interval < 60:
            raise CommandError("The sync interval must be at least 60 seconds.")
        client = FootballDataClient(settings.FOOTBALL_DATA_API_KEY)
        full = options["full"]
        last_full_day = None
        while True:
            current_day = timezone.now().date()
            should_full_sync = full or last_full_day != current_day
            try:
                totals = sync_world_cup(client, full=should_full_sync)
                self.stdout.write(
                    f"World Cup sync: {totals['fixtures']} fixtures, {totals['markets']} markets created, {totals['settled']} settled."
                )
                if should_full_sync:
                    last_full_day = current_day
            except (FootballDataError, OperationalError) as error:
                self.stderr.write(f"World Cup sync failed: {error}")
                if not options["watch"]:
                    raise CommandError(str(error)) from error
            if not options["watch"]:
                return
            full = False
            time.sleep(interval)
