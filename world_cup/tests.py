from datetime import datetime, timezone

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from scheduler.models import Market, MarketTrade, Participant, Trip
from scheduler.services import trip_results
from world_cup.models import WorldCupFixture, WorldCupMarket
from world_cup.provider import FootballDataClient, FootballDataError
from world_cup.services import (
    materialize_world_cup_markets_for_trip,
    sync_world_cup,
)


def fixture_payload(fixture_id, home, away, *, status="SCHEDULED", home_goals=None, away_goals=None):
    return {
        "id": fixture_id,
        "utcDate": "2026-06-24T18:00:00+00:00",
        "status": status,
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "score": {"fullTime": {"home": home_goals, "away": away_goals}},
    }


class FakeClient:
    def __init__(self, fixtures):
        self.fixtures = fixtures
        self.calls = []

    def fetch_fixtures(self, **kwargs):
        self.calls.append(kwargs)
        return self.fixtures


class WorldCupFactoryMixin:
    def make_trip(self, title="Trip"):
        return Trip.objects.create(
            title=title,
            start_date=datetime(2026, 7, 1, tzinfo=timezone.utc).date(),
            end_date=datetime(2026, 7, 5, tzinfo=timezone.utc).date(),
            minimum_duration_days=2,
            ideal_duration_days=2,
            maximum_duration_days=2,
        )


class WorldCupSyncTests(TestCase, WorldCupFactoryMixin):
    def test_unresolved_knockout_slot_is_skipped_until_both_team_names_exist(self):
        self.make_trip()
        payload = fixture_payload(99, "Germany", "Japan")
        payload["awayTeam"]["name"] = None

        totals = sync_world_cup(FakeClient([payload]), full=True)

        self.assertEqual(totals, {"fixtures": 0, "markets": 0, "settled": 0})
        self.assertEqual(WorldCupFixture.objects.count(), 0)

    def test_all_fixtures_with_known_teams_are_imported(self):
        first = self.make_trip("First")
        second = self.make_trip("Second")
        client = FakeClient([
            fixture_payload(1, "Austria", "Brazil"),
            fixture_payload(2, "Cabo Verde", "Germany"),
            fixture_payload(3, "Spain", "Morocco"),
        ])

        totals = sync_world_cup(client, full=True)

        self.assertEqual(totals, {"fixtures": 3, "markets": 6, "settled": 0})
        self.assertEqual(WorldCupFixture.objects.count(), 3)
        self.assertEqual(WorldCupMarket.objects.count(), 6)
        self.assertEqual(WorldCupMarket.objects.filter(trip=first).count(), 3)
        self.assertEqual(WorldCupMarket.objects.filter(trip=second).count(), 3)
        self.assertEqual(client.calls, [{}])

    def test_sync_is_idempotent_and_new_trip_receives_known_fixture_markets(self):
        existing = self.make_trip("Existing")
        client = FakeClient([fixture_payload(10, "Germany", "Mexico")])
        first = sync_world_cup(client, full=True)
        second = sync_world_cup(client, full=True)
        new_trip = self.make_trip("New")

        self.assertEqual(first["markets"], 1)
        self.assertEqual(second["markets"], 0)
        self.assertEqual(materialize_world_cup_markets_for_trip(new_trip), 1)
        self.assertEqual(WorldCupMarket.objects.filter(trip=existing).count(), 1)
        self.assertEqual(WorldCupMarket.objects.filter(trip=new_trip).count(), 1)

    def test_final_regulation_score_settles_each_market_once(self):
        trip = self.make_trip()
        client = FakeClient([fixture_payload(20, "Austria", "Germany")])
        sync_world_cup(client, full=True)
        market = WorldCupMarket.objects.get(trip=trip).market
        winner = Participant.objects.create(trip=trip, name="Winner", beer_chip_millis=7000)
        loser = Participant.objects.create(trip=trip, name="Loser", beer_chip_millis=8000)
        MarketTrade.objects.create(market=market, participant=winner, outcome="yes", chips=3)
        MarketTrade.objects.create(market=market, participant=loser, outcome="no", chips=2)

        client.fixtures = [fixture_payload(20, "Austria", "Germany", status="FINISHED", home_goals=2, away_goals=1)]
        first = sync_world_cup(client, full=False)
        second = sync_world_cup(client, full=False)

        winner.refresh_from_db()
        loser.refresh_from_db()
        market.refresh_from_db()
        self.assertEqual(first["settled"], 1)
        self.assertEqual(second["settled"], 0)
        self.assertEqual(market.resolved_outcome, Market.Outcome.YES)
        self.assertEqual(winner.beer_chip_millis, 10000)
        self.assertEqual(winner.beer_karma_bonus, 1)
        self.assertEqual(loser.beer_chip_millis, 8000)

    def test_nearby_sync_requests_a_bounded_date_window(self):
        client = FakeClient([])

        sync_world_cup(client, full=False)

        self.assertEqual(len(client.calls), 1)
        self.assertIn("from_date", client.calls[0])
        self.assertIn("to_date", client.calls[0])


class FootballDataClientTests(TestCase):
    def test_fetch_fixtures_uses_the_world_cup_competition_and_date_filters(self):
        client = FootballDataClient("test-token")
        payload = {"matches": [{"id": 1}, {"id": 2}]}

        with patch.object(client, "_get", return_value=payload) as get:
            fixtures = client.fetch_fixtures(from_date="2026-06-20", to_date="2026-06-22")

        self.assertEqual([fixture["id"] for fixture in fixtures], [1, 2])
        self.assertEqual(get.call_args.args[0], "/competitions/WC/matches")
        self.assertEqual(get.call_args.args[1], {"dateFrom": "2026-06-20", "dateTo": "2026-06-22"})

    def test_provider_errors_are_raised_without_writing_market_data(self):
        client = FootballDataClient("test-token")
        with patch.object(client, "_get", side_effect=FootballDataError("HTTP 429")):
            with self.assertRaises(FootballDataError):
                client.fetch_fixtures()


class WorldCupMarketIntegrationTests(TestCase, WorldCupFactoryMixin):
    def setUp(self):
        self.trip = self.make_trip()
        sync_world_cup(FakeClient([fixture_payload(30, "Germany", "Japan")]), full=True)
        self.link = WorldCupMarket.objects.get(trip=self.trip)

    def test_results_include_optional_fixture_metadata_and_manual_markets_remain_plain(self):
        manual = Market.objects.create(trip=self.trip, question="Will it rain?")

        markets = {market["id"]: market for market in trip_results(self.trip)["markets"]}

        self.assertEqual(markets[self.link.market_id]["world_cup"]["home_team"], "Germany")
        self.assertTrue(markets[self.link.market_id]["is_tradeable"])
        self.assertIsNone(markets[manual.id]["world_cup"])
        self.assertTrue(markets[manual.id]["is_tradeable"])

    def test_closed_world_cup_fixture_rejects_trades_while_manual_market_still_accepts_them(self):
        self.link.fixture.status = WorldCupFixture.Status.CANCELLED
        self.link.fixture.save(update_fields=["status"])
        automatic_url = reverse("market_trade_api", args=[self.trip.public_id, self.link.market_id])
        rejected = self.client.post(
            automatic_url,
            data='{"name":"Maya","outcome":"yes","chips":1}',
            content_type="application/json",
        )

        manual = Market.objects.create(trip=self.trip, question="Manual question")
        manual_url = reverse("market_trade_api", args=[self.trip.public_id, manual.id])
        accepted = self.client.post(
            manual_url,
            data='{"name":"Maya","outcome":"yes","chips":1}',
            content_type="application/json",
        )

        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(accepted.status_code, 200)

    def test_create_trip_materializes_existing_world_cup_markets(self):
        response = self.client.post(reverse("create_trip"), {
            "title": "Created later",
            "start_date": "2026-08-01",
            "end_date": "2026-08-08",
            "minimum_duration_days": 3,
            "ideal_duration_days": 3,
            "maximum_duration_days": 3,
        })
        created_trip = Trip.objects.get(title="Created later")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(WorldCupMarket.objects.filter(trip=created_trip).count(), 1)

    @override_settings(WORLD_CUP_SYNC_ENABLED=False)
    def test_disabled_management_command_makes_no_request(self):
        call_command("sync_world_cup_markets")
