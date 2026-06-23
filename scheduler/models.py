import uuid
from datetime import date

from django.core.exceptions import ValidationError
from django.db import models


class Trip(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=120)
    destination = models.CharField(max_length=120, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    duration_days = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        errors = {}
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = "The end date must be on or after the start date."
        if self.start_date and self.end_date and self.duration_days:
            total_days = (self.end_date - self.start_date).days + 1
            if self.duration_days > total_days:
                errors["duration_days"] = "The trip length cannot exceed the candidate date range."
        if errors:
            raise ValidationError(errors)

    @property
    def candidate_days(self):
        return (self.end_date - self.start_date).days + 1

    def __str__(self):
        return self.title


class Participant(models.Model):
    trip = models.ForeignKey(Trip, related_name="participants", on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    normalized_name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["trip", "normalized_name"], name="unique_participant_name_per_trip"),
        ]
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.normalized_name = self.name.casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.trip})"


class Availability(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        MAYBE = "maybe", "Maybe"
        UNAVAILABLE = "unavailable", "Unavailable"

    participant = models.ForeignKey(Participant, related_name="availabilities", on_delete=models.CASCADE)
    date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["participant", "date"], name="unique_availability_per_day"),
        ]
        ordering = ["date"]

    def clean(self):
        if self.participant_id and not (self.participant.trip.start_date <= self.date <= self.participant.trip.end_date):
            raise ValidationError({"date": "Availability must be inside the trip's candidate date range."})

