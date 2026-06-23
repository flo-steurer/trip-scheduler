from django.core.exceptions import ValidationError
from django.db import models


class WorldCupFixture(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        LIVE = "live", "Live"
        FINAL = "final", "Final"
        CANCELLED = "cancelled", "Cancelled"

    provider_fixture_id = models.PositiveBigIntegerField(unique=True)
    home_team = models.CharField(max_length=100)
    away_team = models.CharField(max_length=100)
    kickoff_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    home_regulation_goals = models.PositiveSmallIntegerField(null=True, blank=True)
    away_regulation_goals = models.PositiveSmallIntegerField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kickoff_at", "provider_fixture_id"]

    @property
    def is_tradeable(self):
        return self.status in {self.Status.SCHEDULED, self.Status.LIVE}

    @property
    def final_score(self):
        if self.home_regulation_goals is None or self.away_regulation_goals is None:
            return None
        return f"{self.home_regulation_goals}–{self.away_regulation_goals}"

    def __str__(self):
        return f"{self.home_team} vs {self.away_team}"


class WorldCupMarket(models.Model):
    fixture = models.ForeignKey(WorldCupFixture, related_name="markets", on_delete=models.CASCADE)
    market = models.OneToOneField("scheduler.Market", related_name="world_cup_market", on_delete=models.CASCADE)
    trip = models.ForeignKey("scheduler.Trip", related_name="world_cup_markets", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["fixture", "trip"], name="unique_world_cup_market_per_trip_fixture"),
        ]

    def clean(self):
        if self.market_id and self.trip_id and self.market.trip_id != self.trip_id:
            raise ValidationError({"trip": "The linked market must belong to this trip."})

    def __str__(self):
        return f"{self.fixture} ({self.trip})"
