import json
from datetime import date

from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.contrib.staticfiles import finders

from .models import Availability, Participant, Proposal, ProposalVote, Trip
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
        self.assertEqual(windows[0]["strong_attendee_count"], 2)
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

    def test_rejects_invalid_status_and_date_outside_trip(self):
        invalid_status = self.post_json({"name": "Maya", "date": "2026-07-02", "status": "yes"})
        outside_range = self.post_json({"name": "Maya", "date": "2026-08-02", "status": "available"})
        self.assertEqual(invalid_status.status_code, 400)
        self.assertEqual(outside_range.status_code, 400)
        self.assertEqual(Availability.objects.count(), 0)

    def test_participant_endpoint_returns_existing_person_and_results(self):
        url = reverse("participant_api", args=[self.trip.public_id])
        response = self.client.post(url, data=json.dumps({"name": "Kei"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["participant"]["name"], "Kei")
        self.assertIn("windows", payload["results"])
