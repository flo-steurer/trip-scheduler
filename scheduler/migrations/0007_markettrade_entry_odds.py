from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0006_remove_bets_add_beermarket"),
    ]

    operations = [
        migrations.AddField(
            model_name="markettrade",
            name="entry_odds",
            field=models.PositiveSmallIntegerField(default=50),
        ),
    ]
