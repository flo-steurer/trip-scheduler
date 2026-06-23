# Generated manually for proposal voting.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Proposal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type", models.CharField(choices=[("destination", "Destination"), ("stay", "Villa / stay"), ("other", "Other idea")], max_length=16)),
                ("title", models.CharField(max_length=160)),
                ("url", models.URLField(blank=True, max_length=500)),
                ("note", models.TextField(blank=True, max_length=1000)),
                ("price", models.CharField(blank=True, max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("submitted_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="proposals", to="scheduler.participant")),
                ("trip", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="proposals", to="scheduler.trip")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ProposalVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="proposal_votes", to="scheduler.participant")),
                ("proposal", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="votes", to="scheduler.proposal")),
            ],
        ),
        migrations.AddConstraint(
            model_name="proposalvote",
            constraint=models.UniqueConstraint(fields=("proposal", "participant"), name="unique_proposal_vote_per_participant"),
        ),
    ]
