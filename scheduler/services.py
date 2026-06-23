from collections import defaultdict
from datetime import timedelta

from django.db.models import Count

from .models import Availability, Proposal


def date_range(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


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
    for duration_days in range(trip.minimum_duration_days, trip.maximum_duration_days + 1):
        for offset in range(len(days) - duration_days + 1):
            window_days = days[offset:offset + duration_days]
            confirmed, possible, partial, eligible_attendees, below_minimum = [], [], [], [], []
            available_person_days = 0
            maybe_person_days = 0
            daily_confirmed_attendance = [0] * duration_days
            for participant in participants:
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
            possible_score = len(participants) * duration_days * 2
            attendance_rate_value = attendance_score / possible_score if possible_score else 0
            attendance_rate = round(attendance_rate_value * 100)
            maximum_villa_capacity = max(daily_confirmed_attendance, default=0)
            minimum_villa_occupancy = min(daily_confirmed_attendance, default=0)
            average_villa_fill = round(
                (available_person_days / (maximum_villa_capacity * duration_days)) * 100
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
        trip.proposals.select_related("submitted_by").prefetch_related("votes__participant")
    )
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

    markets = list(trip.markets.prefetch_related("trades__participant").select_related("world_cup_market__fixture"))
    market_results = []
    for market in markets:
        world_cup_market = getattr(market, "world_cup_market", None)
        fixture = world_cup_market.fixture if world_cup_market else None
        trades = list(market.trades.all())
        yes_chips = market.seed_chips
        no_chips = market.seed_chips
        odds_history = [{
            "timestamp": market.created_at.isoformat(),
            "yes_odds": 50,
        }]
        positions = defaultdict(lambda: {"yes_shares": 0, "no_shares": 0})
        for trade in trades:
            position = positions[trade.participant_id]
            position["name"] = trade.participant.name
            if trade.outcome == "yes":
                yes_chips += trade.chips
                position["yes_shares"] += trade.chips
            else:
                no_chips += trade.chips
                position["no_shares"] += trade.chips
            odds_history.append({
                "timestamp": trade.created_at.isoformat(),
                "yes_odds": round(yes_chips / (yes_chips + no_chips) * 100),
            })
        payouts = market.payout_distribution(trades, market.resolved_outcome) if market.is_resolved else {}
        market_results.append({
            "id": market.id,
            "question": market.question,
            "is_resolved": market.is_resolved,
            "is_tradeable": not market.is_resolved and (not fixture or fixture.is_tradeable),
            "resolved_outcome": market.resolved_outcome,
            "yes_odds": round(yes_chips / (yes_chips + no_chips) * 100),
            "no_odds": round(no_chips / (yes_chips + no_chips) * 100),
            "total_chips": sum(trade.chips for trade in trades),
            "odds_history": odds_history,
            "positions": [{
                "name": shares["name"],
                "yes_shares": shares["yes_shares"],
                "no_shares": shares["no_shares"],
                "stake": shares["yes_shares"] + shares["no_shares"],
                "payout": payouts.get(participant_id, 0),
            } for participant_id, shares in sorted(
                positions.items(),
                key=lambda item: (-(item[1]["yes_shares"] + item[1]["no_shares"]), item[1]["name"].casefold()),
            )],
            "world_cup": {
                "home_team": fixture.home_team,
                "away_team": fixture.away_team,
                "kickoff_at": fixture.kickoff_at.isoformat(),
                "status": fixture.status,
                "final_score": fixture.final_score,
            } if fixture else None,
        })

    return {
        "daily": daily,
        "windows": windows,
        "participants": [{
            "id": participant.id,
            "name": participant.name,
            "minimum_attendance_days": participant.minimum_attendance_days,
            "idea_karma": (
                karma_by_participant[participant.id]["post_count"]
                + karma_by_participant[participant.id]["upvote_count"]
            ),
            "market_karma": participant.beer_karma_bonus,
            "beer_chips": participant.beer_chips,
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
