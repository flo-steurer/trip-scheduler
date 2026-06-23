from django.contrib import admin
from django.core.exceptions import ValidationError

from .models import Availability, Market, MarketTrade, Participant, Trip


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
    list_display = ("name", "trip", "beer_chip_balance", "beer_karma_bonus", "created_at")
    search_fields = ("name",)
    list_select_related = ("trip",)
    inlines = [AvailabilityInline]

    @admin.display(description="Beer Chips")
    def beer_chip_balance(self, participant):
        return f"{participant.beer_chip_millis / 1000:g}"


class MarketTradeInline(admin.TabularInline):
    model = MarketTrade
    extra = 0
    readonly_fields = ("participant", "outcome", "chips", "entry_odds", "created_at")
    can_delete = False


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = ("question", "trip", "resolved_outcome", "created_at", "resolved_at")
    list_filter = ("resolved_outcome", "trip")
    search_fields = ("question",)
    list_select_related = ("trip",)
    readonly_fields = ("resolved_outcome", "resolved_at")
    inlines = [MarketTradeInline]
    actions = ("resolve_yes", "resolve_no")

    @admin.action(description="Resolve selected markets: Yes wins (pay chips + Beer Karma)")
    def resolve_yes(self, request, queryset):
        self._resolve(request, queryset, Market.Outcome.YES)

    @admin.action(description="Resolve selected markets: No wins (pay chips + Beer Karma)")
    def resolve_no(self, request, queryset):
        self._resolve(request, queryset, Market.Outcome.NO)

    def _resolve(self, request, queryset, outcome):
        awarded = 0
        resolved = 0
        skipped_automatic = 0
        for market in queryset.filter(resolved_outcome=""):
            if hasattr(market, "world_cup_market"):
                skipped_automatic += 1
                continue
            try:
                awarded += market.resolve(outcome)
                resolved += 1
            except ValidationError:
                continue
        message = f"Resolved {resolved} market(s); awarded Beer Karma to {awarded} winning trader(s)."
        if skipped_automatic:
            message += f" Skipped {skipped_automatic} automatic World Cup market(s)."
        self.message_user(request, message)
