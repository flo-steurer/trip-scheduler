import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0005_bet_betprediction_participant_beer_karma_bonus"),
    ]

    operations = [
        migrations.DeleteModel(name="BetPrediction"),
        migrations.DeleteModel(name="Bet"),
        migrations.AddField(
            model_name="participant",
            name="beer_chips",
            field=models.PositiveIntegerField(default=10),
        ),
        migrations.CreateModel(
            name="Market",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.CharField(max_length=240)),
                ("resolved_outcome", models.CharField(blank=True, choices=[("yes", "Yes"), ("no", "No")], max_length=3)),
                ("seed_chips", models.PositiveSmallIntegerField(default=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("trip", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="markets", to="scheduler.trip")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="MarketTrade",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("outcome", models.CharField(choices=[("yes", "Yes"), ("no", "No")], max_length=3)),
                ("chips", models.PositiveSmallIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("market", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="trades", to="scheduler.market")),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="market_trades", to="scheduler.participant")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
    ]
