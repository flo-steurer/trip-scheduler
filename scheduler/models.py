import uuid
from collections import defaultdict
from datetime import date

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class Trip(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=120)
    destination = models.CharField(max_length=120, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    minimum_duration_days = models.PositiveSmallIntegerField()
    ideal_duration_days = models.PositiveSmallIntegerField()
    maximum_duration_days = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        errors = {}
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = "The end date must be on or after the start date."
        if self.start_date and self.end_date:
            total_days = (self.end_date - self.start_date).days + 1
            durations = {
                "minimum_duration_days": self.minimum_duration_days,
                "ideal_duration_days": self.ideal_duration_days,
                "maximum_duration_days": self.maximum_duration_days,
            }
            for field, duration in durations.items():
                if duration and duration > total_days:
                    errors[field] = "The trip length cannot exceed the candidate date range."
            if self.minimum_duration_days and self.ideal_duration_days and self.maximum_duration_days:
                if not self.minimum_duration_days <= self.ideal_duration_days <= self.maximum_duration_days:
                    errors["ideal_duration_days"] = "Choose durations in order: minimum, ideal, then maximum."
        if errors:
            raise ValidationError(errors)

    @property
    def candidate_days(self):
        return (self.end_date - self.start_date).days + 1

    @property
    def duration_summary(self):
        if self.minimum_duration_days == self.maximum_duration_days:
            return f"{self.minimum_duration_days} day{'s' if self.minimum_duration_days != 1 else ''}"
        return f"{self.minimum_duration_days}–{self.maximum_duration_days} days (ideal {self.ideal_duration_days})"

    def __str__(self):
        return self.title


class Participant(models.Model):
    trip = models.ForeignKey(Trip, related_name="participants", on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    normalized_name = models.CharField(max_length=80)
    minimum_attendance_days = models.PositiveSmallIntegerField(default=1)
    beer_karma_bonus = models.PositiveIntegerField(default=0)
    beer_chips = models.PositiveIntegerField(default=10)
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

    def clean(self):
        if self.minimum_attendance_days > self.trip.maximum_duration_days:
            raise ValidationError({"minimum_attendance_days": "This cannot exceed the trip's maximum length."})

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


class Proposal(models.Model):
    class Type(models.TextChoices):
        DESTINATION = "destination", "Destination"
        STAY = "stay", "Villa / stay"
        OTHER = "other", "Other idea"

    trip = models.ForeignKey(Trip, related_name="proposals", on_delete=models.CASCADE)
    submitted_by = models.ForeignKey(Participant, related_name="proposals", on_delete=models.CASCADE)
    type = models.CharField(max_length=16, choices=Type.choices)
    title = models.CharField(max_length=160)
    url = models.URLField(blank=True, max_length=500)
    note = models.TextField(blank=True, max_length=1000)
    price = models.CharField(blank=True, max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        if self.submitted_by_id and self.trip_id and self.submitted_by.trip_id != self.trip_id:
            raise ValidationError({"submitted_by": "The proposer must belong to this trip."})

    def __str__(self):
        return self.title


class ProposalVote(models.Model):
    proposal = models.ForeignKey(Proposal, related_name="votes", on_delete=models.CASCADE)
    participant = models.ForeignKey(Participant, related_name="proposal_votes", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["proposal", "participant"], name="unique_proposal_vote_per_participant"),
        ]

    def clean(self):
        if self.proposal_id and self.participant_id and self.proposal.trip_id != self.participant.trip_id:
            raise ValidationError({"participant": "Votes must come from a participant in the same trip."})


class Market(models.Model):
    class Outcome(models.TextChoices):
        YES = "yes", "Yes"
        NO = "no", "No"

    trip = models.ForeignKey(Trip, related_name="markets", on_delete=models.CASCADE)
    question = models.CharField(max_length=240)
    resolved_outcome = models.CharField(max_length=3, choices=Outcome.choices, blank=True)
    seed_chips = models.PositiveSmallIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_resolved(self):
        return bool(self.resolved_outcome)

    @staticmethod
    def payout_distribution(trades, outcome):
        total_pool = sum(trade.chips for trade in trades)
        winning_stakes = defaultdict(int)
        for trade in trades:
            if trade.outcome == outcome:
                winning_stakes[trade.participant_id] += trade.chips
        winning_pool = sum(winning_stakes.values())
        if not winning_pool:
            return {}

        payouts = {}
        remainders = []
        for participant_id, stake in winning_stakes.items():
            gross_payout = total_pool * stake
            payouts[participant_id], remainder = divmod(gross_payout, winning_pool)
            remainders.append((remainder, participant_id))
        unallocated = total_pool - sum(payouts.values())
        for _remainder, participant_id in sorted(remainders, key=lambda item: (-item[0], item[1]))[:unallocated]:
            payouts[participant_id] += 1
        return payouts

    def resolve(self, outcome):
        if outcome not in self.Outcome.values:
            raise ValidationError("Choose a valid market outcome.")
        with transaction.atomic():
            market = type(self).objects.select_for_update().get(pk=self.pk)
            if market.is_resolved:
                raise ValidationError("This market has already been resolved.")
            trades = list(market.trades.select_for_update().all())
            payouts = self.payout_distribution(trades, outcome)
            for participant_id, payout in payouts.items():
                Participant.objects.filter(pk=participant_id).update(
                    beer_chips=models.F("beer_chips") + payout,
                    beer_karma_bonus=models.F("beer_karma_bonus") + 1,
                )
            market.resolved_outcome = outcome
            market.resolved_at = timezone.now()
            market.save(update_fields=["resolved_outcome", "resolved_at"])
        self.resolved_outcome = market.resolved_outcome
        self.resolved_at = market.resolved_at
        return len(payouts)

    def __str__(self):
        return self.question


class MarketTrade(models.Model):
    market = models.ForeignKey(Market, related_name="trades", on_delete=models.CASCADE)
    participant = models.ForeignKey(Participant, related_name="market_trades", on_delete=models.CASCADE)
    outcome = models.CharField(max_length=3, choices=Market.Outcome.choices)
    chips = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def clean(self):
        if self.market_id and self.participant_id and self.market.trip_id != self.participant.trip_id:
            raise ValidationError({"participant": "Market trades must come from a participant in the same trip."})
