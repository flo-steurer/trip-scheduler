from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0015_alter_market_seed_chips"),
        ("world_cup", "0002_remove_game_features"),
    ]

    # Remove dependent tables before the models and fields they reference.
    operations = [
        migrations.DeleteModel(name="MarketTrade"),
        migrations.DeleteModel(name="Market"),
        migrations.DeleteModel(name="ChipBalanceEvent"),
        migrations.DeleteModel(name="ClickerAccount"),
        migrations.DeleteModel(name="ClickerDailyConversion"),
        migrations.DeleteModel(name="DailyBeercoinGrant"),
        migrations.RemoveField(model_name="participant", name="beer_chip_millis"),
        migrations.RemoveField(model_name="participant", name="beer_chips"),
        migrations.RemoveField(model_name="participant", name="beer_karma_bonus"),
    ]
