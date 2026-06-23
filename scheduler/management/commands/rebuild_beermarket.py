from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from scheduler.models import ChipBalanceEvent, Market, Participant


class Command(BaseCommand):
    help = "Refund and replace open legacy pool markets with share-priced Beermarkets."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply the rebuild. Without this flag, only show the plan.")

    def handle(self, *args, **options):
        markets = list(Market.objects.filter(
            pricing_model=Market.PricingModel.LEGACY,
            resolved_outcome="",
            cancelled_at__isnull=True,
        ).prefetch_related("trades", "world_cup_market"))
        if not markets:
            self.stdout.write("No open legacy markets need rebuilding.")
            return

        refunds = defaultdict(int)
        for market in markets:
            for trade in market.trades.all():
                refunds[trade.participant_id] += trade.chips * Market.SHARE_SCALE
            self.stdout.write(f"Replace #{market.pk}: {market.question}")
        for participant_id, refund_millis in refunds.items():
            participant = Participant.objects.get(pk=participant_id)
            self.stdout.write(f"Refund {refund_millis / Market.SHARE_SCALE:g} chips to {participant.name}")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --apply to make these changes."))
            return

        with transaction.atomic():
            now = timezone.now()
            for participant_id, refund_millis in refunds.items():
                participant = Participant.objects.select_for_update().get(pk=participant_id)
                participant.beer_chip_millis += refund_millis
                participant.save(update_fields=["beer_chip_millis"])
                ChipBalanceEvent.objects.create(
                    participant=participant,
                    amount_millis=refund_millis,
                    balance_after_millis=participant.beer_chip_millis,
                    reason=ChipBalanceEvent.Reason.LEGACY_REFUND,
                )
            for market in markets:
                replacement = Market.objects.create(
                    trip=market.trip,
                    question=market.question,
                    seed_chips=market.seed_chips,
                    pricing_model=Market.PricingModel.SHARES,
                )
                if hasattr(market, "world_cup_market"):
                    world_cup_market = market.world_cup_market
                    world_cup_market.market = replacement
                    world_cup_market.save(update_fields=["market"])
                market.cancelled_at = now
                market.replacement = replacement
                market.save(update_fields=["cancelled_at", "replacement"])
        self.stdout.write(self.style.SUCCESS(f"Rebuilt {len(markets)} market(s) and refunded {len(refunds)} participant(s)."))
