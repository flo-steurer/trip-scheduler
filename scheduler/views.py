import json
from datetime import date
from urllib.parse import urljoin

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import TripForm
from .models import Availability, Participant, Proposal, ProposalVote, Trip
from .services import trip_results


def _trip(public_id):
    return get_object_or_404(Trip, public_id=public_id)


def _json_body(request):
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _participant_for_name(trip, name):
    if not isinstance(name, str):
        return None, "Enter a name first."
    display_name = name.strip()
    if not display_name:
        return None, "Enter a name first."
    if len(display_name) > 80:
        return None, "Names must be 80 characters or fewer."

    normalized_name = display_name.casefold()
    participant = Participant.objects.filter(trip=trip, normalized_name=normalized_name).first()
    if participant:
        return participant, None
    try:
        participant = Participant.objects.create(trip=trip, name=display_name)
    except IntegrityError:
        participant = Participant.objects.get(trip=trip, normalized_name=normalized_name)
    return participant, None


def _minimum_attendance_days(trip, value):
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "Minimum attendance must be a whole number."
    try:
        minimum_days = int(value)
    except (TypeError, ValueError):
        return None, "Minimum attendance must be a whole number."
    if minimum_days < 1 or minimum_days > trip.maximum_duration_days:
        return None, f"Choose between 1 and {trip.maximum_duration_days} days."
    return minimum_days, None


def _participant_payload(participant):
    return {
        "id": participant.id,
        "name": participant.name,
        "minimum_attendance_days": participant.minimum_attendance_days,
    }


def _results_response(trip, **extra):
    payload = {"results": trip_results(trip)}
    payload.update(extra)
    return JsonResponse(payload)


def _proposal_fields(body, existing=None):
    values = {
        "type": existing.type if existing else None,
        "title": existing.title if existing else "",
        "url": existing.url if existing else "",
        "note": existing.note if existing else "",
        "price": existing.price if existing else "",
    }
    for field in values:
        if field in body:
            if not isinstance(body[field], str):
                return None, f"{field.title()} must be text."
            values[field] = body[field].strip()

    if values["type"] not in Proposal.Type.values:
        return None, "Choose a valid proposal type."
    if not values["title"]:
        return None, "Enter a proposal title."
    if len(values["title"]) > 160:
        return None, "Titles must be 160 characters or fewer."
    if len(values["url"]) > 500 or len(values["note"]) > 1000 or len(values["price"]) > 100:
        return None, "One of the proposal fields is too long."
    if values["url"]:
        try:
            URLValidator(schemes=["http", "https"])(values["url"])
        except ValidationError:
            return None, "Enter a valid http(s) link."
    return values, None


@require_GET
def home(request):
    return render(request, "scheduler/home.html", {"form": TripForm()})


@require_POST
def create_trip(request):
    form = TripForm(request.POST)
    if form.is_valid():
        trip = form.save()
        return redirect("trip_detail", public_id=trip.public_id)
    return render(request, "scheduler/home.html", {"form": form}, status=400)


@require_GET
def trip_detail(request, public_id):
    trip = _trip(public_id)
    trip_path = reverse("trip_detail", args=[trip.public_id])
    share_url = urljoin(f"{settings.PUBLIC_BASE_URL}/", trip_path.lstrip("/")) if settings.PUBLIC_BASE_URL else request.build_absolute_uri(trip_path)
    return render(request, "scheduler/trip_detail.html", {
        "trip": trip,
        "initial_results": trip_results(trip),
        "share_url": share_url,
    })


@require_POST
def participant_api(request, public_id):
    trip = _trip(public_id)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Expected a JSON request body."}, status=400)
    participant, error = _participant_for_name(trip, body.get("name"))
    if error:
        return JsonResponse({"error": error}, status=400)
    minimum_days, error = _minimum_attendance_days(trip, body.get("minimum_attendance_days"))
    if error:
        return JsonResponse({"error": error}, status=400)
    if minimum_days is not None and participant.minimum_attendance_days != minimum_days:
        participant.minimum_attendance_days = minimum_days
        participant.save(update_fields=["minimum_attendance_days"])
    return _results_response(trip, participant=_participant_payload(participant))


@require_POST
def availability_api(request, public_id):
    trip = _trip(public_id)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Expected a JSON request body."}, status=400)
    participant, error = _participant_for_name(trip, body.get("name"))
    if error:
        return JsonResponse({"error": error}, status=400)

    try:
        selected_day = date.fromisoformat(body.get("date", ""))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Enter a valid date."}, status=400)
    if not trip.start_date <= selected_day <= trip.end_date:
        return JsonResponse({"error": "That date is outside the candidate range."}, status=400)

    status = body.get("status")
    valid_statuses = {choice for choice, _label in Availability.Status.choices}
    if status in (None, "unmarked"):
        Availability.objects.filter(participant=participant, date=selected_day).delete()
    elif status in valid_statuses:
        Availability.objects.update_or_create(participant=participant, date=selected_day, defaults={"status": status})
    else:
        return JsonResponse({"error": "Unknown availability status."}, status=400)

    return _results_response(trip, participant=_participant_payload(participant))


@require_GET
def results_api(request, public_id):
    return _results_response(_trip(public_id))


@require_POST
def proposal_collection_api(request, public_id):
    trip = _trip(public_id)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Expected a JSON request body."}, status=400)
    participant, error = _participant_for_name(trip, body.get("name"))
    if error:
        return JsonResponse({"error": error}, status=400)
    fields, error = _proposal_fields(body)
    if error:
        return JsonResponse({"error": error}, status=400)
    Proposal.objects.create(trip=trip, submitted_by=participant, **fields)
    return _results_response(trip, participant=_participant_payload(participant))


@require_http_methods(["PATCH", "DELETE"])
def proposal_detail_api(request, public_id, proposal_id):
    trip = _trip(public_id)
    proposal = get_object_or_404(Proposal, trip=trip, pk=proposal_id)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Expected a JSON request body."}, status=400)
    _participant, error = _participant_for_name(trip, body.get("name"))
    if error:
        return JsonResponse({"error": error}, status=400)
    if request.method == "DELETE":
        proposal.delete()
        return _results_response(trip)

    fields, error = _proposal_fields(body, existing=proposal)
    if error:
        return JsonResponse({"error": error}, status=400)
    for field, value in fields.items():
        setattr(proposal, field, value)
    proposal.full_clean()
    proposal.save()
    return _results_response(trip)


@require_POST
def proposal_vote_api(request, public_id, proposal_id):
    trip = _trip(public_id)
    proposal = get_object_or_404(Proposal, trip=trip, pk=proposal_id)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Expected a JSON request body."}, status=400)
    participant, error = _participant_for_name(trip, body.get("name"))
    if error:
        return JsonResponse({"error": error}, status=400)
    vote = ProposalVote.objects.filter(proposal=proposal, participant=participant).first()
    if vote:
        vote.delete()
    else:
        ProposalVote.objects.create(proposal=proposal, participant=participant)
    return _results_response(trip, participant=_participant_payload(participant))
