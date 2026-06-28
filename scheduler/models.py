import uuid
from collections import defaultdict
from datetime import date
from math import ceil, exp, log

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
    beer_chip_millis = models.PositiveIntegerField(default=10000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["trip", "normalized_name"], name="unique_participant_name_per_trip"),
        ]
        ordering = ["name"]

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        self.name = self.name.strip()
        self.normalized_name = self.name.casefold()
        super().save(*args, **kwargs)
        if is_new:
            ChipBalanceEvent.objects.create(
                participant=self,
                amount_millis=self.beer_chip_millis,
                balance_after_millis=self.beer_chip_millis,
                reason=ChipBalanceEvent.Reason.OPENING_BALANCE,
            )

    def clean(self):
        if self.minimum_attendance_days > self.trip.maximum_duration_days:
            raise ValidationError({"minimum_attendance_days": "This cannot exceed the trip's maximum length."})

    def __str__(self):
        return f"{self.name} ({self.trip})"


class DailyBeercoinGrant(models.Model):
    grant_date = models.DateField(unique=True)
    amount_millis = models.PositiveIntegerField(default=10000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-grant_date"]

    def __str__(self):
        return f"{self.amount_millis / 1000:g} Beer Chips on {self.grant_date}"


class ChipBalanceEvent(models.Model):
    class Reason(models.TextChoices):
        OPENING_BALANCE = "opening_balance", "Opening balance"
        DAILY_GRANT = "daily_grant", "Daily grant"
        MARKET_TRADE = "market_trade", "Market trade"
        MARKET_PAYOUT = "market_payout", "Market payout"
        CLICKER_CONVERSION = "clicker_conversion", "Beer-clicker conversion"

    participant = models.ForeignKey(Participant, related_name="chip_balance_events", on_delete=models.CASCADE)
    amount_millis = models.IntegerField()
    balance_after_millis = models.PositiveIntegerField()
    reason = models.CharField(max_length=24, choices=Reason.choices)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.participant}: {self.amount_millis / 1000:g} chips"


class ClickerAccount(models.Model):
    """A participant's separate Beer-clicker currency account."""

    participant = models.OneToOneField(
        Participant,
        related_name="clicker_account",
        on_delete=models.CASCADE,
    )
    balance = models.PositiveIntegerField(default=0)
    lifetime_earned = models.PositiveIntegerField(default=0)
    last_clicked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.participant}: {self.balance} clicker currency"


class ClickerDailyConversion(models.Model):
    """The auditable daily limit for moving clicker currency into Beer Chips."""

    participant = models.ForeignKey(
        Participant,
        related_name="clicker_daily_conversions",
        on_delete=models.CASCADE,
    )
    conversion_date = models.DateField()
    clicker_spent = models.PositiveIntegerField(default=0)
    beer_chip_millis = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "conversion_date"],
                name="unique_clicker_conversion_per_participant_day",
            ),
        ]
        ordering = ["-conversion_date", "-id"]

    def __str__(self):
        return f"{self.participant}: {self.beer_chip_millis / 1000:g} chips on {self.conversion_date}"


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
    total_price = models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)
    currency = models.CharField(blank=True, max_length=3)
    location = models.CharField(blank=True, max_length=120)
    bedrooms = models.PositiveSmallIntegerField(blank=True, null=True)
    sleeps = models.PositiveSmallIntegerField(blank=True, null=True)
    cancellation_terms = models.CharField(blank=True, max_length=240)
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


class ProposalBookingInterest(models.Model):
    """A participant's non-binding signal that they would book a stay."""

    proposal = models.ForeignKey(Proposal, related_name="booking_interests", on_delete=models.CASCADE)
    participant = models.ForeignKey(Participant, related_name="proposal_booking_interests", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["proposal", "participant"],
                name="unique_proposal_booking_interest_per_participant",
            ),
        ]

    def clean(self):
        if self.proposal_id and self.participant_id:
            if self.proposal.type != Proposal.Type.STAY:
                raise ValidationError({"proposal": "Only stays can receive booking interest."})
            if self.proposal.trip_id != self.participant.trip_id:
                raise ValidationError({"participant": "Booking interest must come from the same trip."})


class Market(models.Model):
    SHARE_SCALE = 1000
    DEFAULT_SEED_CHIPS = 50

    class Outcome(models.TextChoices):
        YES = "yes", "Yes"
        NO = "no", "No"

    trip = models.ForeignKey(Trip, related_name="markets", on_delete=models.CASCADE)
    question = models.CharField(max_length=240)
    resolved_outcome = models.CharField(max_length=3, choices=Outcome.choices, blank=True)
    seed_chips = models.PositiveIntegerField(default=DEFAULT_SEED_CHIPS)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_resolved(self):
        return bool(self.resolved_outcome)

    @classmethod
    def seed_chips_for_trip(cls, trip):
        """Choose stable liquidity from the chip economy when a market is created."""
        balances = trip.participants.aggregate(
            total_millis=models.Sum("beer_chip_millis"),
            participant_count=models.Count("id"),
        )
        total_millis = balances["total_millis"] or 0
        participant_count = balances["participant_count"] or 0
        if not total_millis or not participant_count:
            return cls.DEFAULT_SEED_CHIPS

        average_chips = ceil(total_millis / participant_count / cls.SHARE_SCALE)
        total_quarter_chips = ceil(total_millis / cls.SHARE_SCALE / 4)
        return max(cls.DEFAULT_SEED_CHIPS, average_chips, total_quarter_chips)

    def save(self, *args, **kwargs):
        if (
            self._state.adding
            and self.trip_id
            and self.seed_chips == self.DEFAULT_SEED_CHIPS
        ):
            self.seed_chips = self.seed_chips_for_trip(self.trip)
        super().save(*args, **kwargs)

    @staticmethod
    def _lmsr_cost(yes_shares_millis, no_shares_millis, liquidity):
        yes = yes_shares_millis / Market.SHARE_SCALE
        no = no_shares_millis / Market.SHARE_SCALE
        maximum = max(yes, no)
        return maximum + liquidity * log(exp((yes - maximum) / liquidity) + exp((no - maximum) / liquidity))

    def share_market_state(self, trades):
        yes_shares = sum((trade.shares_millis if trade.shares_millis is not None else trade.chips * self.SHARE_SCALE) for trade in trades if trade.outcome == self.Outcome.YES)
        no_shares = sum((trade.shares_millis if trade.shares_millis is not None else trade.chips * self.SHARE_SCALE) for trade in trades if trade.outcome == self.Outcome.NO)
        liquidity = max(self.seed_chips, 1)
        yes_price = 1 / (1 + exp((no_shares - yes_shares) / self.SHARE_SCALE / liquidity))
        return yes_shares, no_shares, yes_price

    def shares_for_cost(self, trades, outcome, cost_millis):
        yes_shares, no_shares, _yes_price = self.share_market_state(trades)
        liquidity = max(self.seed_chips, 1)
        starting_cost = self._lmsr_cost(yes_shares, no_shares, liquidity)
        target_cost = starting_cost + cost_millis / self.SHARE_SCALE
        low, high = 0.0, max(cost_millis / self.SHARE_SCALE * 2, 1.0)
        while self._lmsr_cost(
            yes_shares + (int(high * self.SHARE_SCALE) if outcome == self.Outcome.YES else 0),
            no_shares + (int(high * self.SHARE_SCALE) if outcome == self.Outcome.NO else 0),
            liquidity,
        ) < target_cost:
            high *= 2
        for _ in range(48):
            middle = (low + high) / 2
            shares_millis = int(middle * self.SHARE_SCALE)
            new_cost = self._lmsr_cost(
                yes_shares + (shares_millis if outcome == self.Outcome.YES else 0),
                no_shares + (shares_millis if outcome == self.Outcome.NO else 0),
                liquidity,
            )
            if new_cost <= target_cost:
                low = middle
            else:
                high = middle
        return max(int(low * self.SHARE_SCALE), 1)

    def resolve(self, outcome):
        if outcome not in self.Outcome.values:
            raise ValidationError("Choose a valid market outcome.")
        with transaction.atomic():
            market = type(self).objects.select_for_update().get(pk=self.pk)
            if market.is_resolved:
                raise ValidationError("This market has already been resolved.")
            trades = list(market.trades.select_for_update().all())
            payouts = defaultdict(int)
            for trade in trades:
                if trade.outcome == outcome:
                    payouts[trade.participant_id] += (
                        trade.shares_millis
                        if trade.shares_millis is not None
                        else trade.chips * self.SHARE_SCALE
                    )
            for participant_id, payout in payouts.items():
                participant = Participant.objects.select_for_update().get(pk=participant_id)
                participant.beer_chip_millis += payout
                participant.beer_karma_bonus += 1
                participant.save(update_fields=["beer_chip_millis", "beer_karma_bonus"])
                ChipBalanceEvent.objects.create(
                    participant=participant,
                    amount_millis=payout,
                    balance_after_millis=participant.beer_chip_millis,
                    reason=ChipBalanceEvent.Reason.MARKET_PAYOUT,
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
    entry_odds = models.PositiveSmallIntegerField(default=50)
    cost_millis = models.PositiveIntegerField(null=True, blank=True)
    shares_millis = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def clean(self):
        if self.market_id and self.participant_id and self.market.trip_id != self.participant.trip_id:
            raise ValidationError({"participant": "Market trades must come from a participant in the same trip."})
        if not 0 <= self.entry_odds <= 100:
            raise ValidationError({"entry_odds": "Entry odds must be between 0 and 100."})
