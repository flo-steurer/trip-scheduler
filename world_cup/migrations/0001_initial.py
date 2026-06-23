import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("scheduler", "0006_remove_bets_add_beermarket"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorldCupFixture",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider_fixture_id", models.PositiveBigIntegerField(unique=True)),
                ("home_team", models.CharField(max_length=100)),
                ("away_team", models.CharField(max_length=100)),
                ("kickoff_at", models.DateTimeField()),
                ("status", models.CharField(choices=[("scheduled", "Scheduled"), ("live", "Live"), ("final", "Final"), ("cancelled", "Cancelled")], default="scheduled", max_length=12)),
                ("home_regulation_goals", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("away_regulation_goals", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("synced_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["kickoff_at", "provider_fixture_id"]},
        ),
        migrations.CreateModel(
            name="WorldCupMarket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("fixture", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="markets", to="world_cup.worldcupfixture")),
                ("market", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="world_cup_market", to="scheduler.market")),
                ("trip", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="world_cup_markets", to="scheduler.trip")),
            ],
        ),
        migrations.AddConstraint(
            model_name="worldcupmarket",
            constraint=models.UniqueConstraint(fields=("fixture", "trip"), name="unique_world_cup_market_per_trip_fixture"),
        ),
    ]
