import time
from datetime import datetime, time as datetime_time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from scheduler.services import grant_daily_beercoins


class Command(BaseCommand):
    help = "Give every participant 10 Beer Chips once per calendar day."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="Keep running and grant again after each midnight.")

    def handle(self, *args, **options):
        while True:
            grant, recipient_count = grant_daily_beercoins()
            if recipient_count:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Granted {grant.amount_millis / 1000:g} Beer Chips to {recipient_count} participant(s) for {grant.grant_date}."
                    )
                )
            else:
                self.stdout.write(f"Daily Beer Chips were already granted for {grant.grant_date}.")

            if not options["watch"]:
                return

            now = timezone.localtime()
            next_midnight = datetime.combine(
                now.date() + timedelta(days=1),
                datetime_time.min,
                tzinfo=now.tzinfo,
            )
            time.sleep(max(1, (next_midnight - now).total_seconds()))
