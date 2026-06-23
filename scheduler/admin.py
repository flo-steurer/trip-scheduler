from django.contrib import admin
from django.core.exceptions import ValidationError

from .models import Availability, Bet, BetPrediction, Participant, Trip


class AvailabilityInline(admin.TabularInline):
    model = Availability
    extra = 0


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = (
        "title", "destination", "start_date", "end_date",
        "minimum_duration_days", "ideal_duration_days", "maximum_duration_days", "created_at",
    )
    search_fields = ("title", "destination")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("name", "trip", "beer_karma_bonus", "created_at")
    search_fields = ("name",)
    list_select_related = ("trip",)
    inlines = [AvailabilityInline]


class BetPredictionInline(admin.TabularInline):
    model = BetPrediction
    extra = 0
    readonly_fields = ("participant", "prediction", "created_at", "updated_at")
    can_delete = False


@admin.register(Bet)
class BetAdmin(admin.ModelAdmin):
    list_display = ("question", "trip", "settled_outcome", "created_at", "settled_at")
    list_filter = ("settled_outcome", "trip")
    search_fields = ("question",)
    list_select_related = ("trip",)
    readonly_fields = ("settled_outcome", "settled_at")
    inlines = [BetPredictionInline]
    actions = ("settle_yes", "settle_no")

    @admin.action(description="Settle selected bets: Yes wins (+1 Beer Karma)")
    def settle_yes(self, request, queryset):
        self._settle(request, queryset, Bet.Outcome.YES)

    @admin.action(description="Settle selected bets: No wins (+1 Beer Karma)")
    def settle_no(self, request, queryset):
        self._settle(request, queryset, Bet.Outcome.NO)

    def _settle(self, request, queryset, outcome):
        awarded = 0
        settled = 0
        for bet in queryset.filter(settled_outcome=""):
            try:
                awarded += bet.settle(outcome)
                settled += 1
            except ValidationError:
                continue
        self.message_user(request, f"Settled {settled} bet(s); awarded {awarded} Beer Karma point(s).")
