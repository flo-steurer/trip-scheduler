from collections import defaultdict
from datetime import timedelta

from .models import Availability, Proposal


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
        confirmed, possible, partial = [], [], []
        available_person_days = 0
        maybe_person_days = 0
        for participant in participants:
            statuses = [status_by_person[participant.id].get(day, "unmarked") for day in window_days]
            available_days = statuses.count(Availability.Status.AVAILABLE)
            maybe_days = statuses.count(Availability.Status.MAYBE)
            available_person_days += available_days
            maybe_person_days += maybe_days
            if all(status == Availability.Status.AVAILABLE for status in statuses):
                confirmed.append(participant.name)
            elif all(status in (Availability.Status.AVAILABLE, Availability.Status.MAYBE) for status in statuses):
                possible.append(participant.name)
            elif available_days or maybe_days:
                partial.append({
                    "name": participant.name,
                    "available_days": available_days,
                    "maybe_days": maybe_days,
                })
        windows.append({
            "start_date": window_days[0].isoformat(),
            "end_date": window_days[-1].isoformat(),
            "confirmed": confirmed,
            "possible": possible,
            "confirmed_count": len(confirmed),
            "possible_count": len(possible),
            "partial": partial,
            "available_person_days": available_person_days,
            "maybe_person_days": maybe_person_days,
            # Use integer half-points: available days are worth 2, maybe days 1.
            "attendance_score": available_person_days * 2 + maybe_person_days,
        })
    windows.sort(key=lambda item: (
        -item["attendance_score"],
        -item["available_person_days"],
        -item["confirmed_count"],
        item["start_date"],
    ))

    proposals = list(
        trip.proposals.select_related("submitted_by").prefetch_related("votes__participant")
    )
    proposal_results = []
    for proposal in proposals:
        voter_names = sorted(vote.participant.name for vote in proposal.votes.all())
        proposal_results.append({
            "id": proposal.id,
            "type": proposal.type,
            "type_label": Proposal.Type(proposal.type).label,
            "title": proposal.title,
            "url": proposal.url,
            "note": proposal.note,
            "price": proposal.price,
            "submitted_by": proposal.submitted_by.name,
            "voter_names": voter_names,
            "vote_count": len(voter_names),
            "created_at": proposal.created_at.isoformat(),
            "created_at_timestamp": proposal.created_at.timestamp(),
        })
    proposal_results.sort(key=lambda item: (-item["vote_count"], -item["created_at_timestamp"]))
    for proposal in proposal_results:
        proposal.pop("created_at_timestamp", None)

    return {
        "daily": daily,
        "windows": windows,
        "participants": [{
            "id": participant.id,
            "name": participant.name,
            "availability": {day.isoformat(): status for day, status in status_by_person[participant.id].items()},
        } for participant in participants],
        "proposals": proposal_results,
    }
