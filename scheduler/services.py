from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .beermarket import market_performance as beermarket_performance
from .beermarket import project_trip_markets
from .models import (
    Availability,
    ChipBalanceEvent,
    ClickerAccount,
    ClickerDailyConversion,
    DailyBeercoinGrant,
    Participant,
    Proposal,
)


DAILY_BEERCOIN_MILLIS = 10_000
CLICKER_CLICK_REWARD = 1
CLICKER_CLICK_COOLDOWN_SECONDS = 0.1
CLICKER_UNITS_PER_BEER_CHIP = 100
CLICKER_DAILY_CONVERSION_CAP_MILLIS = 5_000


def date_range(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def grant_daily_beercoins(grant_date=None):
    """Credit every current participant once for the given calendar day."""
    grant_date = grant_date or timezone.localdate()
    with transaction.atomic():
        grant, created = DailyBeercoinGrant.objects.get_or_create(
            grant_date=grant_date,
            defaults={"amount_millis": DAILY_BEERCOIN_MILLIS},
        )
        if not created:
            return grant, 0
        participants = list(Participant.objects.select_for_update().all())
        for participant in participants:
            participant.beer_chip_millis += grant.amount_millis
            participant.save(update_fields=["beer_chip_millis"])
            ChipBalanceEvent.objects.create(
                participant=participant,
                amount_millis=grant.amount_millis,
                balance_after_millis=participant.beer_chip_millis,
                reason=ChipBalanceEvent.Reason.DAILY_GRANT,
            )
        recipient_count = len(participants)
    return grant, recipient_count


def _locked_clicker_account(participant):
    """Return an account while its participant row is already locked by the caller."""
    account, _created = ClickerAccount.objects.select_for_update().get_or_create(
        participant=participant,
    )
    return account


def clicker_status(participant, account=None, conversion_date=None):
    """Return the account and the participant's UTC-day conversion allowance."""
    conversion_date = conversion_date or timezone.localdate()
    account = account or ClickerAccount.objects.filter(participant=participant).first()
    balance = account.balance if account else 0
    lifetime_earned = account.lifetime_earned if account else 0
    conversion = ClickerDailyConversion.objects.filter(
        participant=participant,
        conversion_date=conversion_date,
    ).first()
    converted_millis = conversion.beer_chip_millis if conversion else 0
    remaining_millis = max(CLICKER_DAILY_CONVERSION_CAP_MILLIS - converted_millis, 0)
    available_millis = min(
        balance // CLICKER_UNITS_PER_BEER_CHIP * 1000,
        remaining_millis,
    )
    return {
        "clicker_balance": balance,
        "lifetime_earned": lifetime_earned,
        "beer_chip_millis": participant.beer_chip_millis,
        "conversion_rate_units": CLICKER_UNITS_PER_BEER_CHIP,
        "daily_conversion_cap_millis": CLICKER_DAILY_CONVERSION_CAP_MILLIS,
        "converted_today_millis": converted_millis,
        "remaining_daily_conversion_millis": remaining_millis,
        "available_conversion_millis": available_millis,
    }


def award_clicker_click(participant, now=None):
    """Award one clicker unit only when the server-side cooldown has elapsed."""
    now = now or timezone.now()
    with transaction.atomic():
        participant = Participant.objects.select_for_update().get(pk=participant.pk)
        account = _locked_clicker_account(participant)
        if account.last_clicked_at:
            elapsed = (now - account.last_clicked_at).total_seconds()
            if elapsed < CLICKER_CLICK_COOLDOWN_SECONDS:
                return participant, account, max(CLICKER_CLICK_COOLDOWN_SECONDS - elapsed, 0)
        account.balance += CLICKER_CLICK_REWARD
        account.lifetime_earned += CLICKER_CLICK_REWARD
        account.last_clicked_at = now
        account.save(update_fields=["balance", "lifetime_earned", "last_clicked_at"])
        return participant, account, None


def convert_clicker_currency(participant, conversion_date=None):
    """Atomically convert only the daily allowance; safe to retry after a response loss."""
    conversion_date = conversion_date or timezone.localdate()
    with transaction.atomic():
        participant = Participant.objects.select_for_update().get(pk=participant.pk)
        account = _locked_clicker_account(participant)
        conversion, _created = ClickerDailyConversion.objects.select_for_update().get_or_create(
            participant=participant,
            conversion_date=conversion_date,
        )
        remaining_millis = max(
            CLICKER_DAILY_CONVERSION_CAP_MILLIS - conversion.beer_chip_millis,
            0,
        )
        max_units = remaining_millis // 1000 * CLICKER_UNITS_PER_BEER_CHIP
        clicker_spent = min(account.balance, max_units)
        clicker_spent -= clicker_spent % CLICKER_UNITS_PER_BEER_CHIP
        beer_chip_millis = clicker_spent // CLICKER_UNITS_PER_BEER_CHIP * 1000
        if beer_chip_millis:
            account.balance -= clicker_spent
            account.save(update_fields=["balance"])
            conversion.clicker_spent += clicker_spent
            conversion.beer_chip_millis += beer_chip_millis
            conversion.save(update_fields=["clicker_spent", "beer_chip_millis", "updated_at"])
            participant.beer_chip_millis += beer_chip_millis
            participant.save(update_fields=["beer_chip_millis"])
            ChipBalanceEvent.objects.create(
                participant=participant,
                amount_millis=beer_chip_millis,
                balance_after_millis=participant.beer_chip_millis,
                reason=ChipBalanceEvent.Reason.CLICKER_CONVERSION,
            )
        return participant, account, conversion, beer_chip_millis


def idea_leaderboard(trip):
    """Return the trip's proposal contributors ranked by received support."""
    participants = trip.participants.annotate(
        post_count=Count("proposals", distinct=True),
        upvote_count=Count("proposals__votes", distinct=True),
    )
    entries = []
    for participant in participants:
        idea_karma = participant.post_count + participant.upvote_count
        karma = idea_karma + participant.beer_karma_bonus
        if karma >= 8:
            title = "Itinerary Overlord"
        elif participant.beer_karma_bonus and not idea_karma:
            title = "Market Wizard"
        elif participant.upvote_count >= participant.post_count and karma:
            title = "Upvote Magnet"
        elif participant.post_count:
            title = "Idea Machine"
        else:
            title = "Mysterious Lurker"
        entries.append({
            "name": participant.name,
            "post_count": participant.post_count,
            "upvote_count": participant.upvote_count,
            "market_karma": participant.beer_karma_bonus,
            "karma": karma,
            "title": title,
        })
    entries.sort(key=lambda entry: (
        -entry["karma"],
        -entry["market_karma"],
        -entry["upvote_count"],
        -entry["post_count"],
        entry["name"].casefold(),
    ))
    for position, entry in enumerate(entries, start=1):
        entry["rank"] = position
    return entries


def chip_leaderboard(trip):
    """Return the trip's participants ranked by their current Beer Chip balance."""
    entries = [{
        "name": participant.name,
        "beer_chip_millis": participant.beer_chip_millis,
    } for participant in trip.participants.all()]
    entries.sort(key=lambda entry: (-entry["beer_chip_millis"], entry["name"].casefold()))
    for position, entry in enumerate(entries, start=1):
        whole_chips, fractional_millis = divmod(entry["beer_chip_millis"], 1000)
        entry["chip_balance"] = (
            str(whole_chips)
            if not fractional_millis
            else f"{whole_chips}.{fractional_millis:03d}".rstrip("0")
        )
        entry["rank"] = position
    return entries


def clicker_leaderboard(trip):
    """Return participants ranked by clicker lifetime earnings, then balance."""
    entries = []
    for participant in trip.participants.select_related("clicker_account"):
        try:
            account = participant.clicker_account
        except ClickerAccount.DoesNotExist:
            account = None
        entries.append({
            "name": participant.name,
            "clicker_balance": account.balance if account else 0,
            "lifetime_earned": account.lifetime_earned if account else 0,
        })
    entries.sort(key=lambda entry: (
        -entry["lifetime_earned"],
        -entry["clicker_balance"],
        entry["name"].casefold(),
    ))
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank
    return entries


def market_performance(trip):
    """Return final P/L for participants in settled markets only."""
    return beermarket_performance(trip=trip)


def chip_holdings_history(trip):
    """Return timestamped chip-balance series suitable for the leaderboard chart."""
    participants = list(trip.participants.all())
    events = list(
        ChipBalanceEvent.objects.filter(participant__trip=trip)
        .select_related("participant")
        .order_by("created_at", "id")
    )
    timestamps = sorted({event.created_at for event in events})
    events_by_participant = defaultdict(lambda: defaultdict(list))
    for event in events:
        events_by_participant[event.participant_id][event.created_at].append(event)

    series = []
    for participant in participants:
        running_balance = 0
        started = False
        points = []
        participant_events = events_by_participant[participant.id]
        for timestamp in timestamps:
            if timestamp in participant_events:
                running_balance = participant_events[timestamp][-1].balance_after_millis
                started = True
            if started:
                points.append({
                    "timestamp": timestamp.isoformat(),
                    "balance_millis": running_balance,
                })
        if points:
            series.append({"name": participant.name, "points": points})
    return series


def trip_results(trip):
    participants = list(trip.participants.prefetch_related("availabilities"))
    days = list(date_range(trip.start_date, trip.end_date))
    status_by_person = {
        participant.id: {availability.date: availability.status for availability in participant.availabilities.all()}
        for participant in participants
    }
    scoring_participants = [
        participant
        for participant in participants
        if any(
            status_by_person[participant.id].get(day)
            in (Availability.Status.AVAILABLE, Availability.Status.MAYBE)
            for day in days
        )
    ]
    active_participant_ids = {participant.id for participant in scoring_participants}

    daily = []
    for day in days:
        counts = defaultdict(int)
        for participant in participants:
            counts[status_by_person[participant.id].get(day, "unmarked")] += 1
        daily.append({"date": day.isoformat(), "available": counts[Availability.Status.AVAILABLE], "maybe": counts[Availability.Status.MAYBE], "unavailable": counts[Availability.Status.UNAVAILABLE], "unmarked": counts["unmarked"]})

    windows = []
    for duration_days in range(trip.minimum_duration_days, trip.maximum_duration_days + 1):
        for offset in range(len(days) - duration_days + 1):
            window_days = days[offset:offset + duration_days]
            confirmed, possible, partial, eligible_attendees, below_minimum = [], [], [], [], []
            available_person_days = 0
            maybe_person_days = 0
            daily_confirmed_attendance = [0] * duration_days
            daily_potential_attendance = [0] * duration_days
            for participant in scoring_participants:
                statuses = [status_by_person[participant.id].get(day, "unmarked") for day in window_days]
                available_days = statuses.count(Availability.Status.AVAILABLE)
                maybe_days = statuses.count(Availability.Status.MAYBE)
                weighted_attendance = available_days * 2 + maybe_days
                minimum_score = participant.minimum_attendance_days * 2
                if weighted_attendance < minimum_score:
                    below_minimum.append({
                        "name": participant.name,
                        "available_days": available_days,
                        "maybe_days": maybe_days,
                        "minimum_days": participant.minimum_attendance_days,
                    })
                    continue
                available_person_days += available_days
                maybe_person_days += maybe_days
                eligible_attendees.append(participant.name)
                for day_index, status in enumerate(statuses):
                    if status == Availability.Status.AVAILABLE:
                        daily_confirmed_attendance[day_index] += 1
                    if status in (Availability.Status.AVAILABLE, Availability.Status.MAYBE):
                        daily_potential_attendance[day_index] += 1
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
            attendance_score = available_person_days * 2 + maybe_person_days
            possible_score = len(scoring_participants) * duration_days * 2
            attendance_rate_value = attendance_score / possible_score if possible_score else 0
            attendance_rate = round(attendance_rate_value * 100)
            maximum_villa_capacity = max(daily_potential_attendance, default=0)
            maximum_confirmed_villa_capacity = max(daily_confirmed_attendance, default=0)
            minimum_villa_occupancy = min(daily_potential_attendance, default=0)
            average_villa_fill = round(
                ((available_person_days + maybe_person_days) / (maximum_villa_capacity * duration_days)) * 100
            ) if maximum_villa_capacity else 0
            windows.append({
                "start_date": window_days[0].isoformat(),
                "end_date": window_days[-1].isoformat(),
                "duration_days": duration_days,
                "confirmed": confirmed,
                "possible": possible,
                "confirmed_count": len(confirmed),
                "possible_count": len(possible),
                "partial": partial,
                "eligible_attendees": eligible_attendees,
                "eligible_attendee_count": len(eligible_attendees),
                "below_minimum": below_minimum,
                "available_person_days": available_person_days,
                "maybe_person_days": maybe_person_days,
                "attendance_score": attendance_score,
                "attendance_rate": attendance_rate,
                "minimum_villa_occupancy": minimum_villa_occupancy,
                "maximum_villa_capacity": maximum_villa_capacity,
                "maximum_confirmed_villa_capacity": maximum_confirmed_villa_capacity,
                "average_villa_fill": average_villa_fill,
                "attendance_rate_value": attendance_rate_value,
            })
    windows.sort(key=lambda item: (
        -item["attendance_rate_value"],
        abs(item["duration_days"] - trip.ideal_duration_days),
        -item["eligible_attendee_count"],
        item["start_date"],
    ))
    for window in windows:
        window.pop("attendance_rate_value", None)

    proposals = list(
        trip.proposals.select_related("submitted_by").prefetch_related(
            "votes__participant", "booking_interests__participant"
        )
    )
    best_window_capacity = windows[0]["maximum_villa_capacity"] if windows else 0
    karma_by_participant = {
        participant.id: {"post_count": 0, "upvote_count": 0}
        for participant in participants
    }
    proposal_results = []
    for proposal in proposals:
        karma_by_participant[proposal.submitted_by_id]["post_count"] += 1
        votes = list(proposal.votes.all())
        for vote in votes:
            karma_by_participant[proposal.submitted_by_id]["upvote_count"] += 1
        voter_names = sorted(vote.participant.name for vote in votes)
        booking_names = sorted(interest.participant.name for interest in proposal.booking_interests.all())
        price_person_count = min(best_window_capacity, proposal.sleeps) if proposal.sleeps else best_window_capacity
        price_per_best_window_person = (
            proposal.total_price / price_person_count
            if proposal.total_price is not None and price_person_count
            else None
        )
        proposal_results.append({
            "id": proposal.id,
            "type": proposal.type,
            "type_label": Proposal.Type(proposal.type).label,
            "title": proposal.title,
            "url": proposal.url,
            "note": proposal.note,
            "price": proposal.price,
            "total_price": proposal.total_price,
            "currency": proposal.currency,
            "location": proposal.location,
            "bedrooms": proposal.bedrooms,
            "sleeps": proposal.sleeps,
            "cancellation_terms": proposal.cancellation_terms,
            "price_per_best_window_person": price_per_best_window_person,
            "submitted_by": proposal.submitted_by.name,
            "voter_names": voter_names,
            "vote_count": len(voter_names),
            "booking_names": booking_names,
            "booking_count": len(booking_names),
            "created_at": proposal.created_at.isoformat(),
            "created_at_timestamp": proposal.created_at.timestamp(),
        })
    proposal_results.sort(key=lambda item: (-item["vote_count"], -item["created_at_timestamp"]))
    for proposal in proposal_results:
        proposal.pop("created_at_timestamp", None)

    market_results = project_trip_markets(trip=trip)

    return {
        "daily": daily,
        "windows": windows,
        "active_participant_count": len(scoring_participants),
        "participants": [{
            "id": participant.id,
            "name": participant.name,
            "is_active": participant.id in active_participant_ids,
            "minimum_attendance_days": participant.minimum_attendance_days,
            "idea_karma": (
                karma_by_participant[participant.id]["post_count"]
                + karma_by_participant[participant.id]["upvote_count"]
            ),
            "market_karma": participant.beer_karma_bonus,
            "beer_chip_millis": participant.beer_chip_millis,
            "beer_karma": (
                karma_by_participant[participant.id]["post_count"]
                + karma_by_participant[participant.id]["upvote_count"]
                + participant.beer_karma_bonus
            ),
            "availability": {day.isoformat(): status for day, status in status_by_person[participant.id].items()},
        } for participant in participants],
        "proposals": proposal_results,
        "markets": market_results,
    }
