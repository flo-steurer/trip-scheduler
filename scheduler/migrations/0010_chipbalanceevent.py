import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def create_opening_balance_events(apps, schema_editor):
    Participant = apps.get_model("scheduler", "Participant")
    ChipBalanceEvent = apps.get_model("scheduler", "ChipBalanceEvent")
    now = timezone.now()
    ChipBalanceEvent.objects.bulk_create([
        ChipBalanceEvent(
            participant_id=participant.id,
            amount_millis=participant.beer_chip_millis,
            balance_after_millis=participant.beer_chip_millis,
            reason="opening_balance",
            created_at=now,
        )
        for participant in Participant.objects.all()
    ])


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0009_dailybeercoingrant"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChipBalanceEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount_millis", models.IntegerField()),
                ("balance_after_millis", models.PositiveIntegerField()),
                ("reason", models.CharField(choices=[("opening_balance", "Opening balance"), ("daily_grant", "Daily grant"), ("market_trade", "Market trade"), ("market_payout", "Market payout"), ("legacy_refund", "Legacy market refund")], max_length=24)),
                ("created_at", models.DateTimeField(default=timezone.now)),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chip_balance_events", to="scheduler.participant")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.RunPython(create_opening_balance_events, migrations.RunPython.noop),
    ]
