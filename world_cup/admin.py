from django.contrib import admin, messages

from .models import WorldCupFixture, WorldCupMarket
from .provider import FootballDataClient, FootballDataError
from .services import sync_world_cup


@admin.register(WorldCupFixture)
class WorldCupFixtureAdmin(admin.ModelAdmin):
    list_display = ("home_team", "away_team", "kickoff_at", "status", "final_score", "synced_at")
    list_filter = ("status",)
    search_fields = ("home_team", "away_team")
    readonly_fields = (
        "provider_fixture_id", "home_team", "away_team", "kickoff_at", "status",
        "home_regulation_goals", "away_regulation_goals", "synced_at",
    )
    actions = ("sync_now",)

    @admin.action(description="Sync World Cup fixtures now")
    def sync_now(self, request, queryset):
        from django.conf import settings

        if not settings.FOOTBALL_DATA_API_KEY:
            self.message_user(request, "FOOTBALL_DATA_API_KEY is not configured.", level=messages.ERROR)
            return
        try:
            totals = sync_world_cup(FootballDataClient(settings.FOOTBALL_DATA_API_KEY), full=True)
        except FootballDataError as error:
            self.message_user(request, str(error), level=messages.ERROR)
            return
        self.message_user(request, f"Synced {totals['fixtures']} targeted fixtures; created {totals['markets']} markets; settled {totals['settled']} markets.")


@admin.register(WorldCupMarket)
class WorldCupMarketAdmin(admin.ModelAdmin):
    list_display = ("fixture", "trip", "market", "created_at")
    list_select_related = ("fixture", "trip", "market")
    readonly_fields = ("fixture", "trip", "market", "created_at")
    search_fields = ("fixture__home_team", "fixture__away_team", "trip__title", "market__question")
