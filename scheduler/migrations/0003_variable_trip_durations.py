from django.db import migrations, models


def copy_existing_duration(apps, schema_editor):
    Trip = apps.get_model("scheduler", "Trip")
    for trip in Trip.objects.all().iterator():
        trip.minimum_duration_days = trip.duration_days
        trip.ideal_duration_days = trip.duration_days
        trip.maximum_duration_days = trip.duration_days
        trip.save(update_fields=["minimum_duration_days", "ideal_duration_days", "maximum_duration_days"])


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0002_proposal_proposalvote"),
    ]

    operations = [
        migrations.AddField(
            model_name="trip",
            name="minimum_duration_days",
            field=models.PositiveSmallIntegerField(default=1),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trip",
            name="ideal_duration_days",
            field=models.PositiveSmallIntegerField(default=1),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trip",
            name="maximum_duration_days",
            field=models.PositiveSmallIntegerField(default=1),
            preserve_default=False,
        ),
        migrations.RunPython(copy_existing_duration, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="trip",
            name="duration_days",
        ),
    ]
