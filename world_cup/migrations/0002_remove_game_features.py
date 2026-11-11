from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("world_cup", "0001_initial"),
        ("scheduler", "0015_alter_market_seed_chips"),
    ]

    operations = [
        migrations.DeleteModel(name="WorldCupMarket"),
        migrations.DeleteModel(name="WorldCupFixture"),
    ]
