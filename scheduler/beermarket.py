from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import exp, log

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import ChipBalanceEvent, Market, MarketTrade, Participant, Trip
from world_cup.models import WorldCupMarket


class BeermarketError(Exception):
    def __init__(self, public_message):
        self.public_message = public_message
        super().__init__(public_message)


@dataclass(frozen=True)
class TradeReceipt:
    trip: Trip
    participant: Participant
    trade: MarketTrade
    cost_millis: int
    shares_millis: int
    entry_odds: int
    balance_after_millis: int

    @property
    def activity_action(self):
        return f"market_trade_bought_{self.trade.outcome}_{self.cost_millis}"


def _participant_for_name(trip, name):
    if not isinstance(name, str):
        raise BeermarketError("Enter a name first.")
    display_name = name.strip()
    if not display_name:
        raise BeermarketError("Enter a name first.")
    if len(display_name) > 80:
        raise BeermarketError("Names must be 80 characters or fewer.")

    normalized_name = display_name.casefold()
    participant = Participant.objects.filter(trip=trip, normalized_name=normalized_name).first()
    if participant:
        return participant
    try:
        return Participant.objects.create(trip=trip, name=display_name)
    except IntegrityError:
        return Participant.objects.get(trip=trip, normalized_name=normalized_name)


def _parse_chip_millis(chips):
    if isinstance(chips, bool):
        raise BeermarketError("Choose a valid Beer Chip amount.")
    try:
        chip_millis_decimal = Decimal(str(chips)) * Market.SHARE_SCALE
        chip_millis = int(chip_millis_decimal)
    except (InvalidOperation, TypeError, ValueError):
        raise BeermarketError("Choose a valid Beer Chip amount.") from None
    if chip_millis_decimal != chip_millis or chip_millis < 1:
        raise BeermarketError("Spend at least 0.001 Beer Chips.")
    return chip_millis


def _trade_cost_millis(trade):
    return trade.cost_millis if trade.cost_millis is not None else trade.chips * Market.SHARE_SCALE


def _trade_shares_millis(trade):
    return trade.shares_millis if trade.shares_millis is not None else trade.chips * Market.SHARE_SCALE


def _lmsr_cost(yes_shares_millis, no_shares_millis, liquidity):
    yes = yes_shares_millis / Market.SHARE_SCALE
    no = no_shares_millis / Market.SHARE_SCALE
    maximum = max(yes, no)
    return maximum + liquidity * log(exp((yes - maximum) / liquidity) + exp((no - maximum) / liquidity))


def share_market_state(market, trades):
    yes_shares = sum(_trade_shares_millis(trade) for trade in trades if trade.outcome == Market.Outcome.YES)
    no_shares = sum(_trade_shares_millis(trade) for trade in trades if trade.outcome == Market.Outcome.NO)
    liquidity = max(market.seed_chips, 1)
    yes_price = 1 / (1 + exp((no_shares - yes_shares) / Market.SHARE_SCALE / liquidity))
    return yes_shares, no_shares, yes_price


def shares_for_cost(market, trades, outcome, cost_millis):
    yes_shares, no_shares, _yes_price = share_market_state(market, trades)
    liquidity = max(market.seed_chips, 1)
    starting_cost = _lmsr_cost(yes_shares, no_shares, liquidity)
    target_cost = starting_cost + cost_millis / Market.SHARE_SCALE
    low, high = 0.0, max(cost_millis / Market.SHARE_SCALE * 2, 1.0)
    while _lmsr_cost(
        yes_shares + (int(high * Market.SHARE_SCALE) if outcome == Market.Outcome.YES else 0),
        no_shares + (int(high * Market.SHARE_SCALE) if outcome == Market.Outcome.NO else 0),
        liquidity,
    ) < target_cost:
        high *= 2
    for _ in range(48):
        middle = (low + high) / 2
        shares_millis = int(middle * Market.SHARE_SCALE)
        new_cost = _lmsr_cost(
            yes_shares + (shares_millis if outcome == Market.Outcome.YES else 0),
            no_shares + (shares_millis if outcome == Market.Outcome.NO else 0),
            liquidity,
        )
        if new_cost <= target_cost:
            low = middle
        else:
            high = middle
    return max(int(low * Market.SHARE_SCALE), 1)


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


def place_trade(*, trip_public_id, market_id, participant_name, outcome, chips):
    trip = get_object_or_404(Trip, public_id=trip_public_id)
    market = get_object_or_404(Market, trip=trip, pk=market_id)
    participant = _participant_for_name(trip, participant_name)
    if outcome not in Market.Outcome.values:
        raise BeermarketError("Choose Yes or No.")
    chip_millis = _parse_chip_millis(chips)

    with transaction.atomic():
        market = Market.objects.select_for_update().get(pk=market.pk)
        participant = Participant.objects.select_for_update().get(pk=participant.pk)
        if market.is_resolved:
            raise BeermarketError("This Beermarket has already been resolved.")
        world_cup_market = WorldCupMarket.objects.select_related("fixture").filter(market=market).first()
        if world_cup_market and not world_cup_market.fixture.is_tradeable:
            raise BeermarketError("This World Cup market is no longer accepting trades.")
        if chip_millis > participant.beer_chip_millis:
            raise BeermarketError("You do not have that many Beer Chips.")
        existing_trades = list(market.trades.all())
        if not existing_trades:
            seed_chips = Market.seed_chips_for_trip(trip)
            if market.seed_chips < seed_chips:
                market.seed_chips = seed_chips
                market.save(update_fields=["seed_chips"])
        _yes_shares, _no_shares, yes_price = share_market_state(market, existing_trades)
        entry_odds = round((yes_price if outcome == Market.Outcome.YES else 1 - yes_price) * 100)
        shares_millis = shares_for_cost(market, existing_trades, outcome, chip_millis)
        participant.beer_chip_millis -= chip_millis
        participant.save(update_fields=["beer_chip_millis"])
        ChipBalanceEvent.objects.create(
            participant=participant,
            amount_millis=-chip_millis,
            balance_after_millis=participant.beer_chip_millis,
            reason=ChipBalanceEvent.Reason.MARKET_TRADE,
        )
        trade = MarketTrade.objects.create(
            market=market,
            participant=participant,
            outcome=outcome,
            chips=max(1, chip_millis // Market.SHARE_SCALE),
            entry_odds=entry_odds,
            cost_millis=chip_millis,
            shares_millis=shares_millis,
        )
    return TradeReceipt(
        trip=trip,
        participant=participant,
        trade=trade,
        cost_millis=chip_millis,
        shares_millis=shares_millis,
        entry_odds=entry_odds,
        balance_after_millis=participant.beer_chip_millis,
    )


def settle_market(*, market_id, outcome, allow_automatic=True):
    if outcome not in Market.Outcome.values:
        raise ValidationError("Choose a valid market outcome.")
    with transaction.atomic():
        market = Market.objects.select_for_update().get(pk=market_id)
        if not allow_automatic and WorldCupMarket.objects.filter(market=market).exists():
            raise ValidationError("Automatic World Cup markets cannot be resolved manually.")
        if market.is_resolved:
            raise ValidationError("This market has already been resolved.")
        trades = list(market.trades.select_for_update().all())
        payouts = defaultdict(int)
        for trade in trades:
            if trade.outcome == outcome:
                payouts[trade.participant_id] += _trade_shares_millis(trade)
        for participant_id, payout in payouts.items():
            participant = Participant.objects.select_for_update().get(pk=participant_id)
            participant.beer_chip_millis += payout
            participant.beer_karma_bonus += 1
            participant.save(update_fields=["beer_chip_millis", "beer_karma_bonus"])
            ChipBalanceEvent.objects.create(
                participant=participant,
                amount_millis=payout,
                balance_after_millis=participant.beer_chip_millis,
                reason=ChipBalanceEvent.Reason.MARKET_PAYOUT,
            )
        market.resolved_outcome = outcome
        market.resolved_at = timezone.now()
        market.save(update_fields=["resolved_outcome", "resolved_at"])
    return len(payouts)


def project_trip_markets(*, trip):
    markets = list(trip.markets.prefetch_related("trades__participant").select_related("world_cup_market__fixture"))
    market_results = []
    for market in markets:
        world_cup_market = getattr(market, "world_cup_market", None)
        fixture = world_cup_market.fixture if world_cup_market else None
        trades = list(market.trades.all())
        _yes_shares, _no_shares, yes_price = share_market_state(market, trades)
        odds_history = [{"timestamp": market.created_at.isoformat(), "yes_odds": 50}]
        positions = defaultdict(lambda: {
            "yes_shares_millis": 0,
            "no_shares_millis": 0,
            "yes_cost_millis": 0,
            "no_cost_millis": 0,
            "cost_millis": 0,
        })
        prior_trades = []
        for trade in trades:
            position = positions[trade.participant_id]
            position["name"] = trade.participant.name
            trade_shares_millis = _trade_shares_millis(trade)
            trade_cost_millis = _trade_cost_millis(trade)
            position["cost_millis"] += trade_cost_millis
            if trade.outcome == "yes":
                position["yes_shares_millis"] += trade_shares_millis
                position["yes_cost_millis"] += trade_cost_millis
            else:
                position["no_shares_millis"] += trade_shares_millis
                position["no_cost_millis"] += trade_cost_millis
            prior_trades.append(trade)
            _a, _b, historical_yes_price = share_market_state(market, prior_trades)
            odds_history.append({"timestamp": trade.created_at.isoformat(), "yes_odds": round(historical_yes_price * 100)})
        payouts = defaultdict(int)
        if market.is_resolved:
            for trade in trades:
                if trade.outcome == market.resolved_outcome:
                    payouts[trade.participant_id] += _trade_shares_millis(trade)
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
            "yes_entry_odds": (
                round(shares["yes_cost_millis"] / shares["yes_shares_millis"] * 100)
                if shares["yes_shares_millis"]
                else None
            ),
            "no_entry_odds": (
                round(shares["no_cost_millis"] / shares["no_shares_millis"] * 100)
                if shares["no_shares_millis"]
                else None
            ),
            "yes_payout_millis": shares["yes_shares_millis"],
            "no_payout_millis": shares["no_shares_millis"],
            "payout_millis": payouts.get(participant_id, 0),
        } for participant_id, shares in sorted(
            positions.items(),
            key=lambda item: (-item[1]["cost_millis"], item[1]["name"].casefold()),
        )]
        yes_odds = round(yes_price * 100)
        no_odds = 100 - yes_odds
        total_chips_millis = sum(_trade_cost_millis(trade) for trade in trades)
        market_results.append({
            "id": market.id,
            "question": market.question,
            "is_resolved": market.is_resolved,
            "is_tradeable": not market.is_resolved and (not fixture or fixture.is_tradeable),
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
    return market_results


def market_performance(*, trip):
    markets = trip.markets.filter(
        resolved_outcome__in=Market.Outcome.values,
    ).prefetch_related("trades__participant")
    totals = {}

    for market in markets:
        results_by_participant = defaultdict(lambda: {"spent_millis": 0, "payout_millis": 0, "name": ""})
        for trade in market.trades.all():
            result = results_by_participant[trade.participant_id]
            result["name"] = trade.participant.name
            result["spent_millis"] += _trade_cost_millis(trade)
            if trade.outcome == market.resolved_outcome:
                result["payout_millis"] += _trade_shares_millis(trade)

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
