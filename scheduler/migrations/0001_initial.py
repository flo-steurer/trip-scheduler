# Generated manually for the initial application schema.
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Trip",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("title", models.CharField(max_length=120)),
                ("destination", models.CharField(blank=True, max_length=120)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("duration_days", models.PositiveSmallIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Participant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("normalized_name", models.CharField(max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("trip", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participants", to="scheduler.trip")),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Availability",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("status", models.CharField(choices=[("available", "Available"), ("maybe", "Maybe"), ("unavailable", "Unavailable")], max_length=12)),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="availabilities", to="scheduler.participant")),
            ],
            options={"ordering": ["date"]},
        ),
        migrations.AddConstraint(
            model_name="participant",
            constraint=models.UniqueConstraint(fields=("trip", "normalized_name"), name="unique_participant_name_per_trip"),
        ),
        migrations.AddConstraint(
            model_name="availability",
            constraint=models.UniqueConstraint(fields=("participant", "date"), name="unique_availability_per_day"),
        ),
    ]
