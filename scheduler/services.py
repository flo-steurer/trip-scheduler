from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .models import (
    Availability,
    ChipBalanceEvent,
    ClickerAccount,
    ClickerDailyConversion,
    DailyBeercoinGrant,
    Market,
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


def _format_chip_millis(amount_millis, include_sign=False):
    whole_chips, fractional_millis = divmod(abs(amount_millis), 1000)
    value = (
        str(whole_chips)
        if not fractional_millis
        else f"{whole_chips}.{fractional_millis:03d}".rstrip("0")
    )
    if include_sign and amount_millis > 0:
        return f"+{value}"
    if amount_millis < 0:
        return f"-{value}"
    return value


def market_performance(trip):
    """Return final P/L for participants in settled share markets only."""
    markets = trip.markets.filter(
        pricing_model=Market.PricingModel.SHARES,
        cancelled_at__isnull=True,
        resolved_outcome__in=Market.Outcome.values,
    ).prefetch_related("trades__participant")
    totals = {}

    for market in markets:
        results_by_participant = defaultdict(lambda: {"spent_millis": 0, "payout_millis": 0, "name": ""})
        for trade in market.trades.all():
            result = results_by_participant[trade.participant_id]
            result["name"] = trade.participant.name
            result["spent_millis"] += (
                trade.cost_millis
                if trade.cost_millis is not None
                else trade.chips * Market.SHARE_SCALE
            )
            if trade.outcome == market.resolved_outcome:
                result["payout_millis"] += (
                    trade.shares_millis
                    if trade.shares_millis is not None
                    else trade.chips * Market.SHARE_SCALE
                )

        for participant_id, result in results_by_participant.items():
            entry = totals.setdefault(participant_id, {
                "name": result["name"],
                "spent_millis": 0,
                "payout_millis": 0,
                "wins": 0,
                "losses": 0,
                "market_count": 0,
            })
            entry["spent_millis"] += result["spent_millis"]
            entry["payout_millis"] += result["payout_millis"]
            entry["market_count"] += 1
            net_millis = result["payout_millis"] - result["spent_millis"]
            if net_millis > 0:
                entry["wins"] += 1
            elif net_millis < 0:
                entry["losses"] += 1

    entries = []
    for entry in totals.values():
        entry["net_millis"] = entry["payout_millis"] - entry["spent_millis"]
        entry["spent"] = _format_chip_millis(entry["spent_millis"])
        entry["payout"] = _format_chip_millis(entry["payout_millis"])
        entry["net"] = _format_chip_millis(entry["net_millis"], include_sign=True)
        entry["net_kind"] = "gain" if entry["net_millis"] > 0 else "loss" if entry["net_millis"] < 0 else "even"
        entries.append(entry)
    entries.sort(key=lambda entry: (-entry["net_millis"], entry["name"].casefold()))
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank

    return {
        "entries": entries,
        "biggest_winner": next((entry for entry in entries if entry["net_millis"] > 0), None),
        "biggest_loser": next((entry for entry in reversed(entries) if entry["net_millis"] < 0), None),
    }


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
        trip.proposals.select_related("submitted_by").prefetch_related(
            "votes__participant", "booking_interests__participant"
        )
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
        booking_names = sorted(interest.participant.name for interest in proposal.booking_interests.all())
        price_per_active_person = (
            proposal.total_price / len(scoring_participants)
            if proposal.total_price is not None and scoring_participants
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
            "price_per_active_person": price_per_active_person,
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

    markets = list(trip.markets.filter(cancelled_at__isnull=True).prefetch_related("trades__participant").select_related("world_cup_market__fixture"))
    market_results = []
    for market in markets:
        world_cup_market = getattr(market, "world_cup_market", None)
        fixture = world_cup_market.fixture if world_cup_market else None
        trades = list(market.trades.all())
        if market.pricing_model == market.PricingModel.SHARES:
            _yes_shares, _no_shares, yes_price = market.share_market_state(trades)
            odds_history = [{"timestamp": market.created_at.isoformat(), "yes_odds": 50}]
            positions = defaultdict(lambda: {
                "yes_shares_millis": 0,
                "no_shares_millis": 0,
                "yes_entry_total": 0,
                "no_entry_total": 0,
                "cost_millis": 0,
            })
            prior_trades = []
            for trade in trades:
                position = positions[trade.participant_id]
                position["name"] = trade.participant.name
                trade_shares_millis = trade.shares_millis if trade.shares_millis is not None else trade.chips * market.SHARE_SCALE
                trade_cost_millis = trade.cost_millis if trade.cost_millis is not None else trade.chips * market.SHARE_SCALE
                position["cost_millis"] += trade_cost_millis
                if trade.outcome == "yes":
                    position["yes_shares_millis"] += trade_shares_millis
                    position["yes_entry_total"] += trade_shares_millis * trade.entry_odds
                else:
                    position["no_shares_millis"] += trade_shares_millis
                    position["no_entry_total"] += trade_shares_millis * trade.entry_odds
                prior_trades.append(trade)
                _a, _b, historical_yes_price = market.share_market_state(prior_trades)
                odds_history.append({"timestamp": trade.created_at.isoformat(), "yes_odds": round(historical_yes_price * 100)})
            payouts = defaultdict(int)
            if market.is_resolved:
                for trade in trades:
                    if trade.outcome == market.resolved_outcome:
                        payouts[trade.participant_id] += trade.shares_millis if trade.shares_millis is not None else trade.chips * market.SHARE_SCALE
            market_positions = [{
                "name": shares["name"],
                "yes_shares_millis": shares["yes_shares_millis"],
                "no_shares_millis": shares["no_shares_millis"],
                "cost_millis": shares["cost_millis"],
                "mark_value_millis": round(
                    shares["yes_shares_millis"] * yes_price
                    + shares["no_shares_millis"] * (1 - yes_price)
                ),
                "profit_loss_millis": round(
                    shares["yes_shares_millis"] * yes_price
                    + shares["no_shares_millis"] * (1 - yes_price)
                ) - shares["cost_millis"],
                "yes_entry_odds": round(shares["yes_entry_total"] / shares["yes_shares_millis"]) if shares["yes_shares_millis"] else None,
                "no_entry_odds": round(shares["no_entry_total"] / shares["no_shares_millis"]) if shares["no_shares_millis"] else None,
                "yes_payout_millis": shares["yes_shares_millis"],
                "no_payout_millis": shares["no_shares_millis"],
                "payout_millis": payouts.get(participant_id, 0),
            } for participant_id, shares in sorted(
                positions.items(),
                key=lambda item: (-item[1]["cost_millis"], item[1]["name"].casefold()),
            )]
            yes_odds = round(yes_price * 100)
            no_odds = 100 - yes_odds
            total_chips_millis = sum(trade.cost_millis if trade.cost_millis is not None else trade.chips * market.SHARE_SCALE for trade in trades)
        else:
            yes_chips = market.seed_chips
            no_chips = market.seed_chips
            odds_history = [{"timestamp": market.created_at.isoformat(), "yes_odds": 50}]
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
                odds_history.append({"timestamp": trade.created_at.isoformat(), "yes_odds": round(yes_chips / (yes_chips + no_chips) * 100)})
            payouts = market.payout_distribution(trades, market.resolved_outcome) if market.is_resolved else {}
            market_positions = [{
                "name": shares["name"],
                "yes_shares_millis": shares["yes_shares"] * market.SHARE_SCALE,
                "no_shares_millis": shares["no_shares"] * market.SHARE_SCALE,
                "cost_millis": (shares["yes_shares"] + shares["no_shares"]) * market.SHARE_SCALE,
                "mark_value_millis": 0,
                "profit_loss_millis": 0,
                "yes_entry_odds": None,
                "no_entry_odds": None,
                "yes_payout_millis": 0,
                "no_payout_millis": 0,
                "payout_millis": payouts.get(participant_id, 0) * market.SHARE_SCALE,
            } for participant_id, shares in positions.items()]
            yes_odds = round(yes_chips / (yes_chips + no_chips) * 100)
            no_odds = 100 - yes_odds
            total_chips_millis = sum(trade.chips for trade in trades) * market.SHARE_SCALE
        market_results.append({
            "id": market.id,
            "question": market.question,
            "is_resolved": market.is_resolved,
            "is_tradeable": market.pricing_model == market.PricingModel.SHARES and not market.is_resolved and not market.is_cancelled and (not fixture or fixture.is_tradeable),
            "pricing_model": market.pricing_model,
            "resolved_outcome": market.resolved_outcome,
            "yes_odds": yes_odds,
            "no_odds": no_odds,
            "total_chips_millis": total_chips_millis,
            "odds_history": odds_history,
            "positions": market_positions,
            "world_cup": {
                "home_team": fixture.home_team,
                "away_team": fixture.away_team,
                "kickoff_at": fixture.kickoff_at.isoformat(),
                "status": fixture.status,
                "current_score": fixture.current_score,
                "final_score": fixture.final_score,
            } if fixture else None,
        })

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
