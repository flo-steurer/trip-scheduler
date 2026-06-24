# Generated manually for structured villa proposals and non-binding booking interest.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("scheduler", "0010_chipbalanceevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="proposal",
            name="bedrooms",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="proposal",
            name="cancellation_terms",
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.AddField(
            model_name="proposal",
            name="currency",
            field=models.CharField(blank=True, max_length=3),
        ),
        migrations.AddField(
            model_name="proposal",
            name="location",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="proposal",
            name="sleeps",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="proposal",
            name="total_price",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.CreateModel(
            name="ProposalBookingInterest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="proposal_booking_interests", to="scheduler.participant")),
                ("proposal", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="booking_interests", to="scheduler.proposal")),
            ],
        ),
        migrations.AddConstraint(
            model_name="proposalbookinginterest",
            constraint=models.UniqueConstraint(fields=("proposal", "participant"), name="unique_proposal_booking_interest_per_participant"),
        ),
    ]
