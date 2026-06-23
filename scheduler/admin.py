from django.contrib import admin

from .models import Availability, Participant, Trip


class AvailabilityInline(admin.TabularInline):
    model = Availability
    extra = 0


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ("title", "destination", "start_date", "end_date", "duration_days", "created_at")
    search_fields = ("title", "destination")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("name", "trip", "created_at")
    search_fields = ("name",)
    list_select_related = ("trip",)
    inlines = [AvailabilityInline]

