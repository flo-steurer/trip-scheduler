from django.db import migrations, models
from django.db.models import Count, Sum


DEFAULT_SEED_CHIPS = 50
SHARE_SCALE = 1000


def _ceil_div(numerator, denominator):
    return (numerator + denominator - 1) // denominator


def _seed_for_balance(total_millis, participant_count):
    if not total_millis or not participant_count:
        return DEFAULT_SEED_CHIPS
    average_chips = _ceil_div(total_millis, participant_count * SHARE_SCALE)
    total_quarter_chips = _ceil_div(total_millis, SHARE_SCALE * 4)
    return max(DEFAULT_SEED_CHIPS, average_chips, total_quarter_chips)


def raise_open_share_market_seeds(apps, schema_editor):
    Market = apps.get_model("scheduler", "Market")
    Participant = apps.get_model("scheduler", "Participant")

    seeds_by_trip = {
        entry["trip_id"]: _seed_for_balance(entry["total_millis"], entry["participant_count"])
        for entry in Participant.objects.values("trip_id").annotate(
            total_millis=Sum("beer_chip_millis"),
            participant_count=Count("id"),
        )
    }

    open_share_markets = Market.objects.filter(
        pricing_model="shares",
        resolved_outcome="",
        cancelled_at__isnull=True,
    )
    for market in open_share_markets.iterator():
        seed_chips = seeds_by_trip.get(market.trip_id, DEFAULT_SEED_CHIPS)
        if market.seed_chips < seed_chips:
            market.seed_chips = seed_chips
            market.save(update_fields=["seed_chips"])


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0012_beer_clicker"),
    ]

    operations = [
        migrations.AlterField(
            model_name="market",
            name="seed_chips",
            field=models.PositiveIntegerField(default=50),
        ),
        migrations.RunPython(raise_open_share_market_seeds, migrations.RunPython.noop),
    ]
