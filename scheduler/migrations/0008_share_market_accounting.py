from django.db import migrations, models
import django.db.models.deletion


def initialize_millichips(apps, schema_editor):
    Participant = apps.get_model("scheduler", "Participant")
    for participant in Participant.objects.all().only("id", "beer_chips"):
        participant.beer_chip_millis = participant.beer_chips * 1000
        participant.save(update_fields=["beer_chip_millis"])


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0007_markettrade_entry_odds"),
    ]

    operations = [
        migrations.AddField(
            model_name="participant",
            name="beer_chip_millis",
            field=models.PositiveIntegerField(default=10000),
        ),
        migrations.RunPython(initialize_millichips, migrations.RunPython.noop),
        migrations.AddField(
            model_name="market",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="market",
            name="pricing_model",
            field=models.CharField(choices=[("legacy", "Legacy pool"), ("shares", "Share market")], default="legacy", max_length=12),
        ),
        migrations.AddField(
            model_name="market",
            name="replacement",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="replaced_markets", to="scheduler.market"),
        ),
        migrations.AlterField(
            model_name="market",
            name="pricing_model",
            field=models.CharField(choices=[("legacy", "Legacy pool"), ("shares", "Share market")], default="shares", max_length=12),
        ),
        migrations.AddField(
            model_name="markettrade",
            name="cost_millis",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="markettrade",
            name="shares_millis",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
