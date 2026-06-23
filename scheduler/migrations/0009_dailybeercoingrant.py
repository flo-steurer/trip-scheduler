from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0008_share_market_accounting"),
    ]

    operations = [
        migrations.CreateModel(
            name="DailyBeercoinGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("grant_date", models.DateField(unique=True)),
                ("amount_millis", models.PositiveIntegerField(default=10000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-grant_date"]},
        ),
    ]
