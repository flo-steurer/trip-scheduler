import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0004_participant_minimum_attendance_days"),
    ]

    operations = [
        migrations.AddField(
            model_name="participant",
            name="beer_karma_bonus",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="Bet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.CharField(max_length=240)),
                ("settled_outcome", models.CharField(blank=True, choices=[("yes", "Yes"), ("no", "No")], max_length=3)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("settled_at", models.DateTimeField(blank=True, null=True)),
                ("trip", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bets", to="scheduler.trip")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="BetPrediction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("prediction", models.CharField(choices=[("yes", "Yes"), ("no", "No")], max_length=3)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("bet", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="predictions", to="scheduler.bet")),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bet_predictions", to="scheduler.participant")),
            ],
        ),
        migrations.AddConstraint(
            model_name="betprediction",
            constraint=models.UniqueConstraint(fields=("bet", "participant"), name="unique_bet_prediction_per_participant"),
        ),
    ]
