import json
from io import StringIO
from datetime import date, timedelta

from django.core.management import call_command
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.staticfiles import finders

from .models import Availability, ChipBalanceEvent, ClickerAccount, ClickerDailyConversion, DailyBeercoinGrant, Market, MarketTrade, Participant, Proposal, ProposalBookingInterest, ProposalVote, Trip
from .services import award_clicker_click, chip_holdings_history, chip_leaderboard, clicker_leaderboard, convert_clicker_currency, grant_daily_beercoins, idea_leaderboard, market_performance, trip_results


class TripFactoryMixin:
    def make_trip(self, **overrides):
        values = {
            "title": "Lake weekend",
            "start_date": date(2026, 7, 1),
            "end_date": date(2026, 7, 5),
            "minimum_duration_days": 2,
            "ideal_duration_days": 2,
            "maximum_duration_days": 2,
        }
        duration_days = overrides.pop("duration_days", None)
        if duration_days is not None:
            values.update({
                "minimum_duration_days": duration_days,
                "ideal_duration_days": duration_days,
                "maximum_duration_days": duration_days,
            })
        values.update(overrides)
        return Trip.objects.create(**values)

    def person(self, trip, name, statuses=None):
        participant = Participant.objects.create(trip=trip, name=name)
        for day, status in (statuses or {}).items():
            Availability.objects.create(participant=participant, date=day, status=status)
        return participant


class TripFormTests(TestCase):
    def test_stylesheet_and_script_are_discoverable_static_assets(self):
        self.assertIsNotNone(finders.find("scheduler/app.css"))
        self.assertIsNotNone(finders.find("scheduler/trip.js"))
        self.assertIsNotNone(finders.find("scheduler/beermarket.js"))
        self.assertIsNotNone(finders.find("scheduler/beer_clicker.js"))
        self.assertIsNotNone(finders.find("scheduler/chip_leaderboard.js"))
        self.assertIsNotNone(finders.find("scheduler/vendor/echarts.common.min.js"))
        self.assertIsNotNone(finders.find("scheduler/favicon.svg"))

    def test_calendar_uses_millisecond_chip_balances(self):
        with open(finders.find("scheduler/trip.js"), encoding="utf-8") as script:
            contents = script.read()

        self.assertIn("person.beer_chip_millis", contents)
        self.assertNotIn("person.beer_chips", contents)
        self.assertIn("person.is_active", contents)

    def test_beermarket_groups_world_cup_markets_separately(self):
        with open(finders.find("scheduler/beermarket.js"), encoding="utf-8") as script:
            contents = script.read()

        self.assertIn("renderWorldCupMarkets", contents)
        self.assertIn("renderOtherMarkets", contents)
        self.assertIn("Show ${settled.length} settled match", contents)
        self.assertIn("collapsedMarketSections", contents)
        self.assertIn("aria-expanded", contents)
        self.assertIn("fixtureIsLive", contents)
        self.assertIn("fixture.kickoff_at", contents)
        self.assertIn("fixture.current_score", contents)

    def test_trip_page_uses_absolute_static_asset_urls(self):
        trip = Trip.objects.create(
            title="Island escape",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            minimum_duration_days=4,
            ideal_duration_days=4,
            maximum_duration_days=4,
        )
        response = self.client.get(reverse("trip_detail", args=[trip.public_id]))
        self.assertContains(response, 'href="/static/scheduler/app.css"')
        self.assertContains(response, 'href="/static/scheduler/favicon.svg"')
        self.assertContains(response, 'src="/static/scheduler/trip.js"')
        self.assertIn("csrftoken", response.cookies)
        self.assertContains(response, 'data-collapsible="daily-overlap"')
        self.assertContains(response, 'data-collapsible="trip-ideas" open')

    def test_beermarket_page_uses_its_static_script(self):
        trip = Trip.objects.create(
            title="Island escape",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            minimum_duration_days=4,
            ideal_duration_days=4,
            maximum_duration_days=4,
        )
        response = self.client.get(reverse("beermarket", args=[trip.public_id]))
        self.assertContains(response, "Beermarket")
        self.assertContains(response, 'src="/static/scheduler/beermarket.js"')

    def test_trip_pages_share_the_same_navigation(self):
        trip = Trip.objects.create(
            title="Island escape",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            minimum_duration_days=4,
            ideal_duration_days=4,
            maximum_duration_days=4,
        )
        pages = ("trip_detail", "beermarket", "beer_clicker", "leaderboard", "chip_leaderboard")
        navigation = ("trip_detail", "beermarket", "beer_clicker", "leaderboard", "chip_leaderboard", "home")

        for page in pages:
            response = self.client.get(reverse(page, args=[trip.public_id]))
            self.assertEqual(response.status_code, 200)
            for destination in navigation:
                args = [trip.public_id] if destination != "home" else []
                self.assertContains(response, reverse(destination, args=args))
            self.assertContains(response, 'class="trip-nav-link active"')

    @override_settings(PUBLIC_BASE_URL="http://100.64.0.10:8000")
    def test_trip_page_uses_configured_public_share_url(self):
        trip = Trip.objects.create(
            title="Island escape",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            minimum_duration_days=4,
            ideal_duration_days=4,
            maximum_duration_days=4,
        )
        response = self.client.get(reverse("trip_detail", args=[trip.public_id]))
        self.assertContains(response, f'value="http://100.64.0.10:8000/trips/{trip.public_id}/"')

    def test_create_trip_redirects_to_opaque_public_url(self):
        response = self.client.post(reverse("create_trip"), {
            "title": "Island escape",
            "destination": "Mallorca",
            "start_date": "2026-08-01",
            "end_date": "2026-08-08",
            "minimum_duration_days": 3,
            "ideal_duration_days": 4,
            "maximum_duration_days": 5,
        })
        trip = Trip.objects.get()
        self.assertRedirects(response, reverse("trip_detail", args=[trip.public_id]))
        self.assertEqual(response.url, f"/trips/{trip.public_id}/")

    def test_create_trip_rejects_duration_longer_than_range(self):
        response = self.client.post(reverse("create_trip"), {
            "title": "Too long",
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
            "minimum_duration_days": 1,
            "ideal_duration_days": 3,
            "maximum_duration_days": 3,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Trip.objects.count(), 0)
        self.assertContains(response, "cannot exceed", status_code=400)

    def test_create_trip_requires_ordered_duration_range(self):
        response = self.client.post(reverse("create_trip"), {
            "title": "Out of order",
            "start_date": "2026-08-01",
            "end_date": "2026-08-12",
            "minimum_duration_days": 8,
            "ideal_duration_days": 7,
            "maximum_duration_days": 10,
        })
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "minimum, ideal, then maximum", status_code=400)


class ResultsTests(TestCase, TripFactoryMixin):
    def test_results_ranks_confirmed_before_possible_and_date_ties(self):
        trip = self.make_trip(end_date=date(2026, 7, 4), duration_days=2)
        self.person(trip, "Ari", {
            date(2026, 7, 1): "available", date(2026, 7, 2): "available",
            date(2026, 7, 3): "maybe", date(2026, 7, 4): "maybe",
        })
        self.person(trip, "Bea", {
            date(2026, 7, 1): "available", date(2026, 7, 2): "available",
            date(2026, 7, 3): "available", date(2026, 7, 4): "available",
        })
        results = trip_results(trip)
        self.assertEqual(results["windows"][0]["start_date"], "2026-07-01")
        self.assertEqual(results["windows"][0]["confirmed"], ["Ari", "Bea"])
        self.assertEqual(results["windows"][1]["start_date"], "2026-07-02")
        self.assertEqual(results["windows"][1]["confirmed"], ["Bea"])
        self.assertEqual(results["windows"][1]["possible"], ["Ari"])

    def test_unmarked_and_unavailable_do_not_count_as_possible(self):
        trip = self.make_trip(end_date=date(2026, 7, 2))
        self.person(trip, "Ari", {date(2026, 7, 1): "available", date(2026, 7, 2): "unavailable"})
        self.person(trip, "Bea", {date(2026, 7, 1): "available"})
        window = trip_results(trip)["windows"][0]
        self.assertEqual(window["confirmed"], [])
        self.assertEqual(window["possible"], [])

    def test_partial_attendance_improves_a_window_overall_rank(self):
        trip = self.make_trip(
            start_date=date(2026, 9, 3),
            end_date=date(2026, 9, 11),
            duration_days=7,
        )
        full_range = {date(2026, 9, day): "available" for day in range(3, 12)}
        self.person(trip, "Flo", full_range)
        self.person(trip, "Max", full_range)
        self.person(trip, "Vivienne", full_range)
        self.person(trip, "Alex", {date(2026, 9, day): "available" for day in range(8, 12)})

        windows = trip_results(trip)["windows"]
        self.assertEqual(windows[0]["start_date"], "2026-09-05")
        self.assertEqual(windows[0]["available_person_days"], 25)
        self.assertEqual(windows[0]["minimum_villa_occupancy"], 3)
        self.assertEqual(windows[0]["maximum_villa_capacity"], 4)
        self.assertEqual(windows[0]["average_villa_fill"], 89)
        self.assertEqual(windows[0]["partial"], [{"name": "Alex", "available_days": 4, "maybe_days": 0}])

    def test_villa_capacity_counts_maybe_statuses_as_potential_guests(self):
        trip = self.make_trip(end_date=date(2026, 7, 2))
        self.person(trip, "Ari", {
            date(2026, 7, 1): "available",
            date(2026, 7, 2): "available",
        })
        self.person(trip, "Bea", {
            date(2026, 7, 1): "maybe",
            date(2026, 7, 2): "maybe",
        })
        self.person(trip, "Cam", {
            date(2026, 7, 1): "available",
            date(2026, 7, 2): "maybe",
        })

        window = trip_results(trip)["windows"][0]

        self.assertEqual(window["minimum_villa_occupancy"], 3)
        self.assertEqual(window["maximum_villa_capacity"], 3)
        self.assertEqual(window["maximum_confirmed_villa_capacity"], 2)
        self.assertEqual(window["average_villa_fill"], 100)

    def test_variable_durations_prefer_ideal_when_attendance_rates_tie(self):
        trip = self.make_trip(
            end_date=date(2026, 7, 5),
            minimum_duration_days=2,
            ideal_duration_days=3,
            maximum_duration_days=4,
        )
        self.person(trip, "Ari", {date(2026, 7, day): "available" for day in range(1, 6)})
        self.person(trip, "Bea", {date(2026, 7, day): "available" for day in range(1, 6)})

        windows = trip_results(trip)["windows"]
        self.assertEqual(windows[0]["duration_days"], 3)
        self.assertEqual(windows[0]["attendance_rate"], 100)
        self.assertEqual(windows[0]["eligible_attendee_count"], 2)
        self.assertEqual({window["duration_days"] for window in windows}, {2, 3, 4})

    def test_normalized_attendance_rate_prevents_longer_windows_from_auto_winning(self):
        trip = self.make_trip(
            end_date=date(2026, 7, 4),
            minimum_duration_days=2,
            ideal_duration_days=3,
            maximum_duration_days=3,
        )
        self.person(trip, "Ari", {date(2026, 7, day): "available" for day in range(1, 5)})
        self.person(trip, "Bea", {date(2026, 7, day): "available" for day in (1, 2)})

        windows = trip_results(trip)["windows"]
        self.assertEqual(windows[0]["duration_days"], 2)
        self.assertEqual(windows[0]["attendance_rate"], 100)
        self.assertEqual(windows[1]["duration_days"], 3)
        self.assertLess(windows[1]["attendance_rate"], windows[0]["attendance_rate"])

    def test_attendance_below_personal_minimum_is_not_scored(self):
        trip = self.make_trip(end_date=date(2026, 7, 3), duration_days=3)
        ari = self.person(trip, "Ari", {date(2026, 7, day): "available" for day in range(1, 4)})
        bea = self.person(trip, "Bea", {date(2026, 7, 1): "available"})
        bea.minimum_attendance_days = 2
        bea.save(update_fields=["minimum_attendance_days"])

        window = trip_results(trip)["windows"][0]
        self.assertEqual(window["eligible_attendees"], [ari.name])
        self.assertEqual(window["available_person_days"], 3)
        self.assertEqual(window["attendance_rate"], 50)
        self.assertEqual(window["below_minimum"], [{
            "name": "Bea", "available_days": 1, "maybe_days": 0, "minimum_days": 2,
        }])

    def test_people_with_no_available_or_maybe_dates_are_excluded_from_scoring(self):
        trip = self.make_trip(end_date=date(2026, 7, 2), duration_days=2)
        self.person(trip, "Ari", {
            date(2026, 7, 1): "available",
            date(2026, 7, 2): "available",
        })
        self.person(trip, "Bea", {
            date(2026, 7, 1): "unavailable",
            date(2026, 7, 2): "unavailable",
        })
        self.person(trip, "Cy")

        results = trip_results(trip)
        window = results["windows"][0]

        self.assertEqual(window["eligible_attendees"], ["Ari"])
        self.assertEqual(window["attendance_rate"], 100)
        self.assertEqual(window["below_minimum"], [])
        self.assertEqual(results["active_participant_count"], 1)
        active_by_name = {participant["name"]: participant["is_active"] for participant in results["participants"]}
        self.assertEqual(active_by_name, {"Ari": True, "Bea": False, "Cy": False})

    def test_daily_beercoins_are_awarded_once_per_day(self):
        trip = self.make_trip()
        maya = self.person(trip, "Maya")
        ari = self.person(trip, "Ari")
        maya.beer_chip_millis = 3000
        ari.beer_chip_millis = 7000
        maya.save(update_fields=["beer_chip_millis"])
        ari.save(update_fields=["beer_chip_millis"])

        grant, recipient_count = grant_daily_beercoins(date(2026, 7, 1))

        self.assertEqual(recipient_count, 2)
        self.assertEqual(grant.amount_millis, 10000)
        maya.refresh_from_db()
        ari.refresh_from_db()
        self.assertEqual(maya.beer_chip_millis, 13000)
        self.assertEqual(ari.beer_chip_millis, 17000)

        repeated_grant, repeated_recipient_count = grant_daily_beercoins(date(2026, 7, 1))

        self.assertEqual(repeated_grant.pk, grant.pk)
        self.assertEqual(repeated_recipient_count, 0)
        self.assertEqual(DailyBeercoinGrant.objects.count(), 1)

    def test_proposals_are_ranked_by_upvotes_and_expose_voters(self):
        trip = self.make_trip()
        ari = self.person(trip, "Ari")
        bea = self.person(trip, "Bea")
        destination = Proposal.objects.create(trip=trip, submitted_by=ari, type="destination", title="Sicily")
        stay = Proposal.objects.create(trip=trip, submitted_by=bea, type="stay", title="Villa Mare")
        ProposalVote.objects.create(proposal=stay, participant=ari)
        ProposalVote.objects.create(proposal=stay, participant=bea)

        proposals = trip_results(trip)["proposals"]
        self.assertEqual(proposals[0]["title"], "Villa Mare")
        self.assertEqual(proposals[0]["voter_names"], ["Ari", "Bea"])
        self.assertEqual(proposals[1]["title"], "Sicily")
        participants = {participant["name"]: participant for participant in trip_results(trip)["participants"]}
        self.assertEqual(participants["Ari"]["idea_karma"], 1)
        self.assertEqual(participants["Bea"]["idea_karma"], 3)

    def test_stay_price_uses_the_smaller_of_best_window_peak_and_villa_sleeps(self):
        trip = self.make_trip(end_date=date(2026, 7, 4), duration_days=2)
        ari = self.person(trip, "Ari", {
            date(2026, 7, 1): "available",
            date(2026, 7, 2): "available",
        })
        self.person(trip, "Bea", {
            date(2026, 7, 1): "available",
            date(2026, 7, 2): "available",
        })
        self.person(trip, "Cam", {
            date(2026, 7, 3): "available",
            date(2026, 7, 4): "available",
        })
        Proposal.objects.create(
            trip=trip,
            submitted_by=ari,
            type=Proposal.Type.STAY,
            title="Villa Mare",
            total_price="1000.00",
            currency="EUR",
            sleeps=1,
        )

        results = trip_results(trip)

        self.assertEqual(results["active_participant_count"], 3)
        self.assertEqual(results["windows"][0]["maximum_villa_capacity"], 2)
        self.assertEqual(results["proposals"][0]["price_per_best_window_person"], 1000)

    def test_idea_leaderboard_ranks_karma_then_upvotes(self):
        trip = self.make_trip()
        ari = self.person(trip, "Ari")
        bea = self.person(trip, "Bea")
        cam = self.person(trip, "Cam")
        ari_post = Proposal.objects.create(trip=trip, submitted_by=ari, type="destination", title="Sicily")
        bea_post = Proposal.objects.create(trip=trip, submitted_by=bea, type="stay", title="Villa Mare")
        ProposalVote.objects.create(proposal=ari_post, participant=bea)
        ProposalVote.objects.create(proposal=ari_post, participant=cam)
        ProposalVote.objects.create(proposal=bea_post, participant=ari)
        leaderboard = idea_leaderboard(trip)
        self.assertEqual([(entry["name"], entry["karma"]) for entry in leaderboard], [("Ari", 3), ("Bea", 2), ("Cam", 0)])
        self.assertEqual(leaderboard[0]["title"], "Upvote Magnet")

    def test_chip_leaderboard_ranks_balances_then_names(self):
        trip = self.make_trip()
        ari = self.person(trip, "Ari")
        bea = self.person(trip, "Bea")
        cam = self.person(trip, "Cam")
        ari.beer_chip_millis = 9500
        bea.beer_chip_millis = 12000
        cam.beer_chip_millis = 12000
        ari.save(update_fields=["beer_chip_millis"])
        bea.save(update_fields=["beer_chip_millis"])
        cam.save(update_fields=["beer_chip_millis"])

        leaderboard = chip_leaderboard(trip)

        self.assertEqual(
            [(entry["name"], entry["chip_balance"]) for entry in leaderboard],
            [("Bea", "12"), ("Cam", "12"), ("Ari", "9.5")],
        )

    def test_chip_holdings_history_records_opening_and_daily_grant_balances(self):
        trip = self.make_trip()
        self.person(trip, "Ari")

        grant_daily_beercoins(date(2026, 7, 1))

        history = chip_holdings_history(trip)
        self.assertEqual(history[0]["name"], "Ari")
        self.assertEqual(
            [point["balance_millis"] for point in history[0]["points"]],
            [10000, 20000],
        )
        self.assertEqual(
            list(ChipBalanceEvent.objects.values_list("reason", flat=True)),
            [ChipBalanceEvent.Reason.OPENING_BALANCE, ChipBalanceEvent.Reason.DAILY_GRANT],
        )

    def test_market_performance_uses_only_settled_markets_and_ranks_final_net_results(self):
        trip = self.make_trip()
        ari = self.person(trip, "Ari")
        bea = self.person(trip, "Bea")
        cam = self.person(trip, "Cam")
        settled_yes = Market.objects.create(trip=trip, question="Settled yes", resolved_outcome=Market.Outcome.YES)
        settled_no = Market.objects.create(trip=trip, question="Settled no", resolved_outcome=Market.Outcome.NO)
        open_market = Market.objects.create(trip=trip, question="Open")
        MarketTrade.objects.bulk_create([
            MarketTrade(market=settled_yes, participant=ari, outcome="yes", chips=3, cost_millis=3000, shares_millis=6000),
            MarketTrade(market=settled_yes, participant=bea, outcome="no", chips=5, cost_millis=5000, shares_millis=1000),
            MarketTrade(market=settled_no, participant=ari, outcome="yes", chips=2, cost_millis=2000, shares_millis=1000),
            MarketTrade(market=settled_no, participant=bea, outcome="no", chips=1, cost_millis=1000, shares_millis=4000),
            MarketTrade(market=open_market, participant=cam, outcome="yes", chips=9, cost_millis=9000, shares_millis=18000),
        ])

        performance = market_performance(trip)

        self.assertEqual([(entry["name"], entry["net"], entry["wins"], entry["losses"]) for entry in performance["entries"]], [
            ("Ari", "+1", 1, 1),
            ("Bea", "-2", 1, 1),
        ])
        self.assertEqual(performance["entries"][0]["spent"], "5")
        self.assertEqual(performance["entries"][0]["payout"], "6")
        self.assertEqual(performance["biggest_winner"]["name"], "Ari")
        self.assertEqual(performance["biggest_loser"]["name"], "Bea")

    def test_market_performance_orders_tied_break_even_entries_by_name_and_has_no_highlights(self):
        trip = self.make_trip()
        bea = self.person(trip, "Bea")
        ari = self.person(trip, "Ari")
        market = Market.objects.create(trip=trip, question="Even", resolved_outcome=Market.Outcome.YES)
        MarketTrade.objects.bulk_create([
            MarketTrade(market=market, participant=bea, outcome="yes", chips=2, cost_millis=2000, shares_millis=2000),
            MarketTrade(market=market, participant=ari, outcome="yes", chips=2, cost_millis=2000, shares_millis=2000),
        ])

        performance = market_performance(trip)

        self.assertEqual([(entry["name"], entry["net"], entry["wins"], entry["losses"]) for entry in performance["entries"]], [
            ("Ari", "0", 0, 0),
            ("Bea", "0", 0, 0),
        ])
        self.assertIsNone(performance["biggest_winner"])
        self.assertIsNone(performance["biggest_loser"])


class LeaderboardPageTests(TestCase, TripFactoryMixin):
    def test_leaderboard_page_shows_score_breakdown_and_back_link(self):
        trip = self.make_trip()
        ari = self.person(trip, "Ari")
        proposal = Proposal.objects.create(trip=trip, submitted_by=ari, type="destination", title="Sicily")
        ProposalVote.objects.create(proposal=proposal, participant=ari)
        response = self.client.get(reverse("leaderboard", args=[trip.public_id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Beer Karma")
        self.assertContains(response, "Ari")
        self.assertContains(response, "1 post")
        self.assertContains(response, "1 upvote")
        self.assertContains(response, reverse("trip_detail", args=[trip.public_id]))

    def test_chip_leaderboard_page_shows_balances_and_back_link(self):
        trip = self.make_trip()
        ari = self.person(trip, "Ari")
        ari.beer_chip_millis = 7500
        ari.save(update_fields=["beer_chip_millis"])

        response = self.client.get(reverse("chip_leaderboard", args=[trip.public_id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Beer Chips")
        self.assertContains(response, "7.5 chips")
        self.assertContains(response, 'id="chip-history-chart"')
        self.assertContains(response, "Market performance")
        self.assertContains(response, "No settled share-market trades yet")
        self.assertContains(response, 'src="/static/scheduler/vendor/echarts.common.min.js"')
        self.assertContains(response, 'src="/static/scheduler/chip_leaderboard.js"')
        self.assertContains(response, reverse("trip_detail", args=[trip.public_id]))


class BeerClickerTests(TestCase, TripFactoryMixin):
    def setUp(self):
        self.trip = self.make_trip()
        self.participant = self.person(self.trip, "Maya")
        self.click_url = reverse("beer_clicker_click_api", args=[self.trip.public_id])
        self.convert_url = reverse("beer_clicker_convert_api", args=[self.trip.public_id])

    def post_json(self, url, data):
        return self.client.post(url, data=json.dumps(data), content_type="application/json")

    def test_click_is_server_authoritative_and_rate_limited(self):
        invalid = self.post_json(self.click_url, {})
        first = self.post_json(self.click_url, {"name": "Maya"})
        repeated = self.post_json(self.click_url, {"name": "Maya"})

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["earned"], 1)
        self.assertEqual(repeated.status_code, 429)
        account = ClickerAccount.objects.get(participant=self.participant)
        self.assertEqual((account.balance, account.lifetime_earned), (1, 1))
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.beer_chip_millis, 10_000)
        self.assertFalse(ChipBalanceEvent.objects.filter(reason=ChipBalanceEvent.Reason.CLICKER_CONVERSION).exists())

    def test_click_service_rejects_rapid_click_without_changing_balances(self):
        now = timezone.now()
        _participant, first_account, first_retry = award_clicker_click(self.participant, now=now)
        _participant, repeated_account, repeated_retry = award_clicker_click(self.participant, now=now + timedelta(milliseconds=50))

        self.assertIsNone(first_retry)
        self.assertIsNotNone(repeated_retry)
        self.assertEqual(first_account.pk, repeated_account.pk)
        repeated_account.refresh_from_db()
        self.assertEqual((repeated_account.balance, repeated_account.lifetime_earned), (1, 1))

    def test_conversion_enforces_daily_cap_and_is_idempotent_on_repeat(self):
        ClickerAccount.objects.create(participant=self.participant, balance=600, lifetime_earned=600)
        conversion_day = date(2026, 7, 1)

        participant, account, conversion, credited = convert_clicker_currency(self.participant, conversion_day)
        participant, account, repeated_conversion, repeated_credit = convert_clicker_currency(self.participant, conversion_day)

        self.assertEqual(credited, 5_000)
        self.assertEqual(repeated_credit, 0)
        self.assertEqual(conversion.pk, repeated_conversion.pk)
        account.refresh_from_db()
        participant.refresh_from_db()
        self.assertEqual((account.balance, account.lifetime_earned), (100, 600))
        self.assertEqual(participant.beer_chip_millis, 15_000)
        self.assertEqual((conversion.clicker_spent, conversion.beer_chip_millis), (500, 5_000))
        self.assertEqual(ClickerDailyConversion.objects.count(), 1)
        self.assertEqual(
            ChipBalanceEvent.objects.filter(reason=ChipBalanceEvent.Reason.CLICKER_CONVERSION).count(),
            1,
        )

    def test_conversion_endpoint_reports_a_noop_after_the_daily_cap(self):
        ClickerAccount.objects.create(participant=self.participant, balance=500, lifetime_earned=500)

        first = self.post_json(self.convert_url, {"name": "Maya"})
        repeated = self.post_json(self.convert_url, {"name": "Maya"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["credited_millis"], 5_000)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["credited_millis"], 0)
        self.assertEqual(repeated.json()["account"]["remaining_daily_conversion_millis"], 0)

    def test_clicker_leaderboard_orders_lifetime_then_balance_then_name(self):
        ari = self.person(self.trip, "Ari")
        bea = self.person(self.trip, "Bea")
        ClickerAccount.objects.create(participant=self.participant, balance=8, lifetime_earned=50)
        ClickerAccount.objects.create(participant=ari, balance=9, lifetime_earned=50)
        ClickerAccount.objects.create(participant=bea, balance=100, lifetime_earned=40)

        leaderboard = clicker_leaderboard(self.trip)

        self.assertEqual(
            [(entry["name"], entry["lifetime_earned"], entry["clicker_balance"]) for entry in leaderboard],
            [("Ari", 50, 9), ("Maya", 50, 8), ("Bea", 40, 100)],
        )

    def test_clicker_page_uses_the_shared_navigation_and_script(self):
        response = self.client.get(reverse("beer_clicker", args=[self.trip.public_id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Beer-clicker")
        self.assertContains(response, 'src="/static/scheduler/beer_clicker.js"')
        self.assertContains(response, reverse("beermarket", args=[self.trip.public_id]))
        self.assertContains(response, reverse("chip_leaderboard", args=[self.trip.public_id]))

class BeermarketTests(TestCase, TripFactoryMixin):
    def setUp(self):
        self.trip = self.make_trip()
        self.market = Market.objects.create(trip=self.trip, question="Will Kai join the trip planning?")
        self.url = reverse("market_trade_api", args=[self.trip.public_id, self.market.id])

    def post_json(self, data):
        return self.client.post(self.url, data=json.dumps(data), content_type="application/json")

    def test_new_share_markets_seed_from_trip_chip_economy(self):
        trip = self.make_trip(title="Bigger bankroll")
        for index in range(8):
            participant = self.person(trip, f"Trader {index}")
            participant.beer_chip_millis = 100000
            participant.save(update_fields=["beer_chip_millis"])

        market = Market.objects.create(trip=trip, question="Will liquidity scale?")

        self.assertEqual(market.seed_chips, 50)

    def test_middle_seed_keeps_normal_bet_price_impact_visible(self):
        shallow = Market.objects.create(trip=self.trip, question="Shallow", seed_chips=10)
        seeded = Market.objects.create(trip=self.trip, question="Seeded", seed_chips=50)
        shallow_shares = shallow.shares_for_cost([], Market.Outcome.YES, 10000)
        seeded_shares = seeded.shares_for_cost([], Market.Outcome.YES, 10000)

        shallow_yes_price = shallow.share_market_state([
            MarketTrade(
                market=shallow,
                participant=self.person(self.trip, "Shallow Buyer"),
                outcome="yes",
                chips=10,
                shares_millis=shallow_shares,
            )
        ])[2]
        seeded_yes_price = seeded.share_market_state([
            MarketTrade(
                market=seeded,
                participant=self.person(self.trip, "Seeded Buyer"),
                outcome="yes",
                chips=10,
                shares_millis=seeded_shares,
            )
        ])[2]

        self.assertGreater(round(shallow_yes_price * 100), 70)
        self.assertGreater(round(seeded_yes_price * 100), 55)
        self.assertLess(round(seeded_yes_price * 100), 65)

    def test_first_trade_raises_untraded_market_seed_from_current_trip_economy(self):
        market = Market.objects.create(trip=self.trip, question="Created before bankroll")
        trader = self.person(self.trip, "Maya")
        trader.beer_chip_millis = 100000
        trader.save(update_fields=["beer_chip_millis"])
        url = reverse("market_trade_api", args=[self.trip.public_id, market.id])

        response = self.client.post(
            url,
            data=json.dumps({"name": "Maya", "outcome": "yes", "chips": 10}),
            content_type="application/json",
        )

        market.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(market.seed_chips, 50)

    def test_trade_deducts_chips_and_updates_market_odds_history(self):
        first = self.post_json({"name": "Maya", "outcome": "yes", "chips": 3})
        self.assertEqual(first.status_code, 200)
        participant = Participant.objects.get()
        self.assertEqual(participant.beer_chip_millis, 7000)
        self.assertEqual(participant.chip_balance_events.last().reason, ChipBalanceEvent.Reason.MARKET_TRADE)
        self.assertEqual(MarketTrade.objects.get().outcome, "yes")
        self.assertEqual(MarketTrade.objects.get().entry_odds, 50)
        market = first.json()["results"]["markets"][0]
        self.assertGreater(market["yes_odds"], 50)
        self.assertEqual(len(market["odds_history"]), 2)
        self.assertEqual(market["positions"][0]["name"], "Maya")
        self.assertEqual(market["positions"][0]["cost_millis"], 3000)
        trade = MarketTrade.objects.get()
        self.assertEqual(
            market["positions"][0]["yes_entry_odds"],
            round(trade.cost_millis / trade.shares_millis * 100),
        )
        self.assertGreater(market["positions"][0]["yes_entry_odds"], 50)
        self.assertGreater(market["positions"][0]["yes_shares_millis"], 3000)

    def test_position_entry_odds_use_average_fill_price_per_side(self):
        yes_response = self.post_json({"name": "Maya", "outcome": "yes", "chips": 3})
        self.assertEqual(yes_response.status_code, 200)
        no_response = self.post_json({"name": "Maya", "outcome": "no", "chips": 2})
        self.assertEqual(no_response.status_code, 200)

        market = no_response.json()["results"]["markets"][0]
        position = market["positions"][0]
        yes_trade = MarketTrade.objects.get(outcome=Market.Outcome.YES)
        no_trade = MarketTrade.objects.get(outcome=Market.Outcome.NO)

        self.assertEqual(position["cost_millis"], 5000)
        self.assertEqual(
            position["yes_entry_odds"],
            round(yes_trade.cost_millis / yes_trade.shares_millis * 100),
        )
        self.assertEqual(
            position["no_entry_odds"],
            round(no_trade.cost_millis / no_trade.shares_millis * 100),
        )

    def test_resolution_pays_the_pool_to_winners_and_locks_the_market(self):
        maya = self.person(self.trip, "Maya")
        ari = self.person(self.trip, "Ari")
        maya.beer_chip_millis = 7000
        ari.beer_chip_millis = 8000
        maya.save(update_fields=["beer_chip_millis"])
        ari.save(update_fields=["beer_chip_millis"])
        MarketTrade.objects.create(market=self.market, participant=maya, outcome="yes", chips=3)
        MarketTrade.objects.create(market=self.market, participant=ari, outcome="no", chips=2)

        self.assertEqual(self.market.resolve(Market.Outcome.YES), 1)
        maya.refresh_from_db()
        ari.refresh_from_db()
        self.assertEqual(maya.beer_karma_bonus, 1)
        self.assertEqual(ari.beer_karma_bonus, 0)
        self.assertEqual(maya.beer_chip_millis, 10000)
        self.assertEqual(ari.beer_chip_millis, 8000)
        self.assertEqual(maya.chip_balance_events.last().reason, ChipBalanceEvent.Reason.MARKET_PAYOUT)
        self.assertTrue(self.market.is_resolved)

        rejected = self.post_json({"name": "Maya", "outcome": "no", "chips": 1})
        self.assertEqual(rejected.status_code, 400)
        participants = {participant["name"]: participant for participant in trip_results(self.trip)["participants"]}
        self.assertEqual(participants["Maya"]["beer_karma"], 1)

class ProposalApiTests(TestCase, TripFactoryMixin):
    def setUp(self):
        self.trip = self.make_trip()
        self.collection_url = reverse("proposal_collection_api", args=[self.trip.public_id])

    def request_json(self, method, url, data):
        return self.client.generic(method, url, data=json.dumps(data), content_type="application/json")

    def create_proposal(self, **overrides):
        values = {
            "name": "Maya",
            "type": "stay",
            "title": "Villa Maris",
            "url": "https://example.com/villa",
            "note": "Walkable to the beach",
            "price": "€3,200 / week",
        }
        values.update(overrides)
        return self.request_json("POST", self.collection_url, values)

    def test_create_proposal_returns_results_and_validates_link(self):
        response = self.create_proposal()
        self.assertEqual(response.status_code, 200)
        proposal = Proposal.objects.get()
        self.assertEqual(proposal.submitted_by.name, "Maya")
        self.assertEqual(response.json()["results"]["proposals"][0]["title"], "Villa Maris")

        invalid = self.create_proposal(title="Bad link", url="ftp://example.com/villa")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(Proposal.objects.count(), 1)

    def test_vote_toggles_and_only_allows_one_vote(self):
        self.create_proposal()
        proposal = Proposal.objects.get()
        vote_url = reverse("proposal_vote_api", args=[self.trip.public_id, proposal.id])

        first = self.request_json("POST", vote_url, {"name": "Maya"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(ProposalVote.objects.count(), 1)
        self.assertEqual(first.json()["results"]["proposals"][0]["voter_names"], ["Maya"])

        second = self.request_json("POST", vote_url, {"name": "Maya"})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(ProposalVote.objects.count(), 0)

    def test_stay_details_and_booking_interest_are_optional_and_preserve_legacy_price(self):
        self.person(self.trip, "Maya", {date(2026, 7, 1): Availability.Status.AVAILABLE})
        response = self.create_proposal(
            price="€3,200 / week",
            total_price="3200.00",
            currency="eur",
            location="South Istria",
            bedrooms=5,
            sleeps=11,
            cancellation_terms="Free cancellation until 1 July",
        )
        self.assertEqual(response.status_code, 200)
        proposal = Proposal.objects.get()
        self.assertEqual(str(proposal.total_price), "3200.00")
        self.assertEqual(proposal.currency, "EUR")
        self.assertEqual(proposal.price, "€3,200 / week")
        result = response.json()["results"]["proposals"][0]
        self.assertEqual(result["price_per_best_window_person"], "3200.00")
        self.assertEqual(result["booking_count"], 0)

        booking_url = reverse("proposal_booking_interest_api", args=[self.trip.public_id, proposal.id])
        booked = self.request_json("POST", booking_url, {"name": "Maya"})
        self.assertEqual(booked.status_code, 200)
        self.assertEqual(ProposalBookingInterest.objects.count(), 1)
        self.assertEqual(booked.json()["results"]["proposals"][0]["booking_names"], ["Maya"])

        unbooked = self.request_json("POST", booking_url, {"name": "Maya"})
        self.assertEqual(unbooked.status_code, 200)
        self.assertEqual(ProposalBookingInterest.objects.count(), 0)

    def test_backfill_villa_prices_previews_then_updates_only_unambiguous_eur_prices(self):
        legacy = Proposal.objects.create(
            trip=self.trip, submitted_by=self.person(self.trip, "Flo"), type="stay", title="Legacy", price="2774€/Woche"
        )
        already_structured = Proposal.objects.create(
            trip=self.trip, submitted_by=legacy.submitted_by, type="stay", title="Structured", price="€3,200 / week", total_price="3000"
        )
        output = StringIO()
        call_command("backfill_villa_prices", stdout=output)
        legacy.refresh_from_db()
        self.assertIsNone(legacy.total_price)
        self.assertIn("Would update", output.getvalue())

        call_command("backfill_villa_prices", "--apply", stdout=StringIO())
        legacy.refresh_from_db()
        already_structured.refresh_from_db()
        self.assertEqual(str(legacy.total_price), "2774.00")
        self.assertEqual(legacy.currency, "EUR")
        self.assertEqual(str(already_structured.total_price), "3000.00")

    def test_edit_and_delete_require_a_name(self):
        self.create_proposal()
        proposal = Proposal.objects.get()
        detail_url = reverse("proposal_detail_api", args=[self.trip.public_id, proposal.id])

        rejected = self.request_json("PATCH", detail_url, {"title": "Changed"})
        self.assertEqual(rejected.status_code, 400)

        edited = self.request_json("PATCH", detail_url, {
            "name": "Maya", "type": "destination", "title": "Crete", "url": "", "note": "Warm in September", "price": "",
        })
        self.assertEqual(edited.status_code, 200)
        proposal.refresh_from_db()
        self.assertEqual(proposal.title, "Crete")
        self.assertEqual(proposal.type, "destination")

        deleted = self.request_json("DELETE", detail_url, {"name": "Maya"})
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(Proposal.objects.count(), 0)


class AvailabilityApiTests(TestCase, TripFactoryMixin):
    def setUp(self):
        self.trip = self.make_trip(end_date=date(2026, 7, 3))
        self.url = reverse("availability_api", args=[self.trip.public_id])
        self.range_url = reverse("availability_range_api", args=[self.trip.public_id])

    def post_json(self, data):
        return self.client.post(self.url, data=json.dumps(data), content_type="application/json")

    def test_creates_and_clears_availability(self):
        response = self.post_json({"name": "  Maya  ", "date": "2026-07-02", "status": "available"})
        self.assertEqual(response.status_code, 200)
        participant = Participant.objects.get()
        self.assertEqual(participant.name, "Maya")
        self.assertEqual(Availability.objects.get().status, "available")

        response = self.post_json({"name": "maya", "date": "2026-07-02", "status": "unmarked"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Participant.objects.count(), 1)
        self.assertEqual(Availability.objects.count(), 0)

    def test_activity_log_includes_name_ip_and_action(self):
        with self.assertLogs("scheduler.activity", level="INFO") as logs:
            response = self.client.post(
                self.url,
                data=json.dumps({"name": "Maya", "date": "2026-07-02", "status": "available"}),
                content_type="application/json",
                REMOTE_ADDR="203.0.113.42",
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("name='Maya' ip=203.0.113.42 action=availability_set_available", logs.output[0])

    def test_rejects_invalid_status_and_date_outside_trip(self):
        invalid_status = self.post_json({"name": "Maya", "date": "2026-07-02", "status": "yes"})
        outside_range = self.post_json({"name": "Maya", "date": "2026-08-02", "status": "available"})
        self.assertEqual(invalid_status.status_code, 400)
        self.assertEqual(outside_range.status_code, 400)
        self.assertEqual(Availability.objects.count(), 0)

    def test_applies_and_clears_a_contiguous_availability_range(self):
        applied = self.client.post(self.range_url, data=json.dumps({
            "name": "Maya", "start_date": "2026-07-01", "end_date": "2026-07-03", "status": "available",
        }), content_type="application/json")
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(Availability.objects.count(), 3)
        self.assertEqual({availability.status for availability in Availability.objects.all()}, {"available"})

        cleared = self.client.post(self.range_url, data=json.dumps({
            "name": "Maya", "start_date": "2026-07-02", "end_date": "2026-07-03", "status": "unmarked",
        }), content_type="application/json")
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(list(Availability.objects.values_list("date", flat=True)), [date(2026, 7, 1)])

    def test_normalizes_a_backward_availability_range(self):
        response = self.client.post(self.range_url, data=json.dumps({
            "name": "Maya", "start_date": "2026-07-03", "end_date": "2026-07-01", "status": "available",
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Availability.objects.count(), 3)

    def test_participant_endpoint_returns_existing_person_and_results(self):
        url = reverse("participant_api", args=[self.trip.public_id])
        response = self.client.post(url, data=json.dumps({"name": "Kei", "minimum_attendance_days": 2}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["participant"]["name"], "Kei")
        self.assertEqual(payload["participant"]["minimum_attendance_days"], 2)
        self.assertIn("windows", payload["results"])

    def test_participant_endpoint_rejects_minimum_above_trip_maximum(self):
        url = reverse("participant_api", args=[self.trip.public_id])
        response = self.client.post(url, data=json.dumps({"name": "Kei", "minimum_attendance_days": 4}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Participant.objects.count(), 1)
