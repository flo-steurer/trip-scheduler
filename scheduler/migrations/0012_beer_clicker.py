import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scheduler", "0011_stay_details_and_booking_interest"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClickerAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("balance", models.PositiveIntegerField(default=0)),
                ("lifetime_earned", models.PositiveIntegerField(default=0)),
                ("last_clicked_at", models.DateTimeField(blank=True, null=True)),
                ("participant", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="clicker_account", to="scheduler.participant")),
            ],
        ),
        migrations.CreateModel(
            name="ClickerDailyConversion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("conversion_date", models.DateField()),
                ("clicker_spent", models.PositiveIntegerField(default=0)),
                ("beer_chip_millis", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="clicker_daily_conversions", to="scheduler.participant")),
            ],
            options={"ordering": ["-conversion_date", "-id"]},
        ),
        migrations.AlterField(
            model_name="chipbalanceevent",
            name="reason",
            field=models.CharField(choices=[("opening_balance", "Opening balance"), ("daily_grant", "Daily grant"), ("market_trade", "Market trade"), ("market_payout", "Market payout"), ("legacy_refund", "Legacy market refund"), ("clicker_conversion", "Beer-clicker conversion")], max_length=24),
        ),
        migrations.AddConstraint(
            model_name="clickerdailyconversion",
            constraint=models.UniqueConstraint(fields=("participant", "conversion_date"), name="unique_clicker_conversion_per_participant_day"),
        ),
    ]
