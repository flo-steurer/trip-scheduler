import json
from datetime import date

from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.contrib.staticfiles import finders

from .models import Availability, Market, MarketTrade, Participant, Proposal, ProposalVote, Trip
from .services import idea_leaderboard, trip_results


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


class BeermarketTests(TestCase, TripFactoryMixin):
    def setUp(self):
        self.trip = self.make_trip()
        self.market = Market.objects.create(trip=self.trip, question="Will Kai join the trip planning?")
        self.url = reverse("market_trade_api", args=[self.trip.public_id, self.market.id])

    def post_json(self, data):
        return self.client.post(self.url, data=json.dumps(data), content_type="application/json")

    def test_trade_deducts_chips_and_updates_market_odds_history(self):
        first = self.post_json({"name": "Maya", "outcome": "yes", "chips": 3})
        self.assertEqual(first.status_code, 200)
        participant = Participant.objects.get()
        self.assertEqual(participant.beer_chips, 7)
        self.assertEqual(MarketTrade.objects.get().outcome, "yes")
        self.assertEqual(MarketTrade.objects.get().entry_odds, 50)
        market = first.json()["results"]["markets"][0]
        self.assertEqual(market["yes_odds"], 57)
        self.assertEqual(len(market["odds_history"]), 2)
        self.assertEqual(market["positions"], [{
            "name": "Maya", "yes_shares": 3, "no_shares": 0, "stake": 3,
            "yes_entry_odds": 50, "no_entry_odds": None, "yes_payout": 3, "no_payout": 0, "payout": 0,
        }])

    def test_resolution_pays_the_pool_to_winners_and_locks_the_market(self):
        maya = self.person(self.trip, "Maya")
        ari = self.person(self.trip, "Ari")
        maya.beer_chips = 7
        ari.beer_chips = 8
        maya.save(update_fields=["beer_chips"])
        ari.save(update_fields=["beer_chips"])
        MarketTrade.objects.create(market=self.market, participant=maya, outcome="yes", chips=3)
        MarketTrade.objects.create(market=self.market, participant=ari, outcome="no", chips=2)

        self.assertEqual(self.market.resolve(Market.Outcome.YES), 1)
        maya.refresh_from_db()
        ari.refresh_from_db()
        self.assertEqual(maya.beer_karma_bonus, 1)
        self.assertEqual(ari.beer_karma_bonus, 0)
        self.assertEqual(maya.beer_chips, 12)
        self.assertEqual(ari.beer_chips, 8)
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
