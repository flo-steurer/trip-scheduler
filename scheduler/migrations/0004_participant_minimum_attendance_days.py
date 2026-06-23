from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0003_variable_trip_durations"),
    ]

    operations = [
        migrations.AddField(
            model_name="participant",
            name="minimum_attendance_days",
            field=models.PositiveSmallIntegerField(default=1),
        ),
    ]
