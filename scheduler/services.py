from collections import defaultdict
from datetime import timedelta

from .models import Availability


def date_range(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def trip_results(trip):
    participants = list(trip.participants.prefetch_related("availabilities"))
    days = list(date_range(trip.start_date, trip.end_date))
    status_by_person = {
        participant.id: {availability.date: availability.status for availability in participant.availabilities.all()}
        for participant in participants
    }

    daily = []
    for day in days:
        counts = defaultdict(int)
        for participant in participants:
            counts[status_by_person[participant.id].get(day, "unmarked")] += 1
        daily.append({"date": day.isoformat(), "available": counts[Availability.Status.AVAILABLE], "maybe": counts[Availability.Status.MAYBE], "unavailable": counts[Availability.Status.UNAVAILABLE], "unmarked": counts["unmarked"]})

    windows = []
    for offset in range(len(days) - trip.duration_days + 1):
        window_days = days[offset:offset + trip.duration_days]
        confirmed, possible = [], []
        for participant in participants:
            statuses = [status_by_person[participant.id].get(day, "unmarked") for day in window_days]
            if all(status == Availability.Status.AVAILABLE for status in statuses):
                confirmed.append(participant.name)
            elif all(status in (Availability.Status.AVAILABLE, Availability.Status.MAYBE) for status in statuses):
                possible.append(participant.name)
        windows.append({
            "start_date": window_days[0].isoformat(),
            "end_date": window_days[-1].isoformat(),
            "confirmed": confirmed,
            "possible": possible,
            "confirmed_count": len(confirmed),
            "possible_count": len(possible),
        })
    windows.sort(key=lambda item: (-item["confirmed_count"], -item["possible_count"], item["start_date"]))

    return {
        "daily": daily,
        "windows": windows,
        "participants": [{
            "id": participant.id,
            "name": participant.name,
            "availability": {day.isoformat(): status for day, status in status_by_person[participant.id].items()},
        } for participant in participants],
    }
