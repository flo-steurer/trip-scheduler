import unicodedata
from datetime import timedelta, timezone as datetime_timezone

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from scheduler.models import Market, Trip

from .models import WorldCupFixture, WorldCupMarket


TARGET_TEAM_ALIASES = {
    "austria",
    "germany",
    "cape verde",
    "cape verde islands",
    "cabo verde",
}

LIVE_STATUSES = {"IN_PLAY", "PAUSED"}
FINAL_STATUSES = {"FINISHED"}
CANCELLED_STATUSES = {"SUSPENDED", "CANCELLED", "AWARDED"}


def normalize_team_name(name):
    normalized = unicodedata.normalize("NFKD", name or "")
    return " ".join(normalized.encode("ascii", "ignore").decode("ascii").casefold().split())


def is_target_fixture(home_team, away_team):
    return bool(home_team and away_team) and (
        normalize_team_name(home_team) in TARGET_TEAM_ALIASES
        or normalize_team_name(away_team) in TARGET_TEAM_ALIASES
    )


def fixture_status(source_status):
    short_status = (source_status or "").upper()
    if short_status in FINAL_STATUSES:
        return WorldCupFixture.Status.FINAL
    if short_status in CANCELLED_STATUSES:
        return WorldCupFixture.Status.CANCELLED
    if short_status in LIVE_STATUSES:
        return WorldCupFixture.Status.LIVE
    return WorldCupFixture.Status.SCHEDULED


def team_name(team):
    name = (team or {}).get("name")
    return name.strip() if isinstance(name, str) else ""


def fixture_values(payload):
    score = payload.get("score") or {}
    kickoff_at = parse_datetime(payload["utcDate"])
    if kickoff_at is None:
        raise ValueError("Fixture has no valid kickoff date.")
    if timezone.is_naive(kickoff_at):
        kickoff_at = timezone.make_aware(kickoff_at, datetime_timezone.utc)
    fulltime = score.get("fullTime") or {}
    return {
        "provider_fixture_id": int(payload["id"]),
        "home_team": team_name(payload.get("homeTeam")),
        "away_team": team_name(payload.get("awayTeam")),
        "kickoff_at": kickoff_at,
        "status": fixture_status(payload.get("status")),
        "home_regulation_goals": fulltime.get("home"),
        "away_regulation_goals": fulltime.get("away"),
    }


def question_for(fixture):
    return f"Will {fixture.home_team} beat {fixture.away_team} in regulation time?"


def _market_for_trip(fixture, trip):
    existing = WorldCupMarket.objects.filter(fixture=fixture, trip=trip).select_related("market").first()
    if existing:
        return existing, False
    market = Market.objects.create(trip=trip, question=question_for(fixture))
    try:
        return WorldCupMarket.objects.create(fixture=fixture, trip=trip, market=market), True
    except IntegrityError:
        market.delete()
        return WorldCupMarket.objects.select_related("market").get(fixture=fixture, trip=trip), False


def materialize_fixture_markets(fixture, trips=None):
    if not fixture.is_tradeable or not is_target_fixture(fixture.home_team, fixture.away_team):
        return 0
    created = 0
    for trip in trips if trips is not None else Trip.objects.all():
        _world_cup_market, did_create = _market_for_trip(fixture, trip)
        created += int(did_create)
    return created


def materialize_world_cup_markets_for_trip(trip):
    fixtures = WorldCupFixture.objects.filter(
        status__in=[WorldCupFixture.Status.SCHEDULED, WorldCupFixture.Status.LIVE],
    )
    return sum(materialize_fixture_markets(fixture, [trip]) for fixture in fixtures)


def settle_fixture_markets(fixture):
    if fixture.status != WorldCupFixture.Status.FINAL:
        return 0
    if fixture.home_regulation_goals is None or fixture.away_regulation_goals is None:
        return 0
    outcome = Market.Outcome.YES if fixture.home_regulation_goals > fixture.away_regulation_goals else Market.Outcome.NO
    settled = 0
    for world_cup_market in WorldCupMarket.objects.filter(fixture=fixture).select_related("market"):
        if world_cup_market.market.is_resolved:
            continue
        world_cup_market.market.resolve(outcome)
        settled += 1
    return settled


@transaction.atomic
def sync_fixture(payload):
    values = fixture_values(payload)
    if not is_target_fixture(values["home_team"], values["away_team"]):
        return {"fixtures": 0, "markets": 0, "settled": 0}
    fixture, _created = WorldCupFixture.objects.update_or_create(
        provider_fixture_id=values.pop("provider_fixture_id"),
        defaults=values,
    )
    markets = materialize_fixture_markets(fixture)
    settled = settle_fixture_markets(fixture)
    return {"fixtures": 1, "markets": markets, "settled": settled}


def sync_world_cup(client, *, full=False):
    if full:
        payloads = client.fetch_fixtures()
    else:
        today = timezone.now().date()
        payloads = client.fetch_fixtures(from_date=today - timedelta(days=1), to_date=today + timedelta(days=1))
    totals = {"fixtures": 0, "markets": 0, "settled": 0}
    for payload in payloads:
        result = sync_fixture(payload)
        for key, value in result.items():
            totals[key] += value
    return totals
