import json
from io import StringIO
from datetime import date

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.test import override_settings
from django.urls import reverse
from django.contrib.staticfiles import finders

from .models import Availability, Participant, Proposal, ProposalBookingInterest, ProposalVote, Trip
from .services import trip_results


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
        self.assertIsNotNone(finders.find("scheduler/favicon.svg"))

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


class CleanTripTests(TestCase, TripFactoryMixin):
    def test_trip_page_and_results_only_expose_planning_features(self):
        trip = self.make_trip()
        participant = self.person(trip, "Maya", {trip.start_date: "available"})
        response = self.client.get(reverse("trip_detail", args=[trip.public_id]))
        self.assertContains(response, reverse("home"))
        self.assertContains(response, reverse("trip_detail", args=[trip.public_id]))
        self.assertContains(response, "Trip ideas")
        for label in ("Beermarket", "Beer-clicker", "Karma", "Chips"):
            self.assertNotContains(response, label)

        results = self.client.get(reverse("results_api", args=[trip.public_id])).json()["results"]
        self.assertEqual(set(results), {"daily", "windows", "active_participant_count", "participants", "proposals"})
        self.assertEqual(results["participants"], [{
            "id": participant.id,
            "name": "Maya",
            "is_active": True,
            "minimum_attendance_days": 1,
            "availability": {"2026-07-01": "available"},
        }])

    def test_removed_pages_and_apis_return_404(self):
        trip = self.make_trip()
        for suffix in (
            "beermarket/", "beer-clicker/", "leaderboard/", "chip-leaderboard/",
            "api/beer-clicker/status/", "api/beer-clicker/click/",
            "api/beer-clicker/convert/", "api/markets/1/trade/",
        ):
            for method in ("get", "post"):
                with self.subTest(suffix=suffix, method=method):
                    response = getattr(self.client, method)(f"/trips/{trip.public_id}/{suffix}")
                    self.assertEqual(response.status_code, 404)
        self.assertEqual(Participant.objects.count(), 0)


class CleanupMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_all_planning_records_and_removes_game_schema(self):
        old_targets = [
            ("scheduler", "0015_alter_market_seed_chips"),
            ("world_cup", "0001_initial"),
        ]
        executor = MigrationExecutor(connection)
        latest_targets = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest_targets))
        executor.migrate(old_targets)
        old_apps = executor.loader.project_state(old_targets).apps
        def old(name):
            return old_apps.get_model("scheduler", name)

        trip = old("Trip").objects.create(
            title="Existing trip", destination="Istria",
            start_date=date(2026, 7, 1), end_date=date(2026, 7, 5),
            minimum_duration_days=2, ideal_duration_days=3, maximum_duration_days=4,
        )
        person = old("Participant").objects.create(
            trip=trip, name="Maya", normalized_name="maya", minimum_attendance_days=2,
            beer_chip_millis=42000, beer_chips=42, beer_karma_bonus=7,
        )
        old("Availability").objects.create(participant=person, date=trip.start_date, status="available")
        proposal = old("Proposal").objects.create(
            trip=trip, submitted_by=person, type="stay", title="Villa",
            total_price="3200.00", currency="EUR", sleeps=8, bedrooms=4,
        )
        old("ProposalVote").objects.create(proposal=proposal, participant=person)
        old("ProposalBookingInterest").objects.create(proposal=proposal, participant=person)
        market = old("Market").objects.create(trip=trip, question="Will we go?")
        old("MarketTrade").objects.create(market=market, participant=person, outcome="yes", chips=3)
        old("ChipBalanceEvent").objects.create(
            participant=person, amount_millis=42000, balance_after_millis=42000, reason="opening_balance",
        )
        old("ClickerAccount").objects.create(participant=person, balance=100, lifetime_earned=100)
        old("ClickerDailyConversion").objects.create(participant=person, conversion_date=trip.start_date)
        old("DailyBeercoinGrant").objects.create(grant_date=trip.start_date)
        fixture = old_apps.get_model("world_cup", "WorldCupFixture").objects.create(
            provider_fixture_id=1, home_team="A", away_team="B", kickoff_at=trip.created_at, status="scheduled",
        )
        old_apps.get_model("world_cup", "WorldCupMarket").objects.create(fixture=fixture, market=market, trip=trip)
        planning_models = (Trip, Participant, Availability, Proposal, ProposalVote, ProposalBookingInterest)
        snapshots = {
            model.__name__: list(old(model.__name__).objects.values(*[f.attname for f in model._meta.fields]))
            for model in planning_models
        }

        MigrationExecutor(connection).migrate(latest_targets)

        for model in planning_models:
            with self.subTest(model=model.__name__):
                self.assertEqual(list(model.objects.values()), snapshots[model.__name__])
        tables = set(connection.introspection.table_names())
        for name in ("market", "markettrade", "chipbalanceevent", "clickeraccount", "clickerdailyconversion", "dailybeercoingrant"):
            self.assertNotIn(f"scheduler_{name}", tables)
        self.assertFalse(any(name.startswith("world_cup_") for name in tables))
        self.assertEqual(Participant.objects.create(trip_id=trip.id, name=" New person ").normalized_name, "new person")
        results = trip_results(Trip.objects.get(pk=trip.id))
        self.assertEqual(results["proposals"][0]["booking_names"], ["Maya"])
