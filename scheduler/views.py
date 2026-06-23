import json
import logging
from datetime import date, timedelta
from urllib.parse import urljoin

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import TripForm
from .models import Availability, Market, MarketTrade, Participant, Proposal, ProposalVote, Trip
from .services import idea_leaderboard, trip_results
from world_cup.models import WorldCupMarket
from world_cup.services import materialize_world_cup_markets_for_trip


activity_logger = logging.getLogger("scheduler.activity")


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
        "beer_chips": participant.beer_chips,
    }


def _activity(request, participant, action):
    activity_logger.info(
        "activity name=%r ip=%s action=%s",
        participant.name,
        request.META.get("REMOTE_ADDR", "unknown"),
        action,
    )


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
        materialize_world_cup_markets_for_trip(trip)
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


@require_GET
def leaderboard(request, public_id):
    trip = _trip(public_id)
    return render(request, "scheduler/leaderboard.html", {
        "trip": trip,
        "leaderboard": idea_leaderboard(trip),
    })


@require_GET
def beermarket(request, public_id):
    trip = _trip(public_id)
    return render(request, "scheduler/beermarket.html", {
        "trip": trip,
        "initial_results": trip_results(trip),
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
        _activity(request, participant, "minimum_attendance_updated")
    else:
        _activity(request, participant, "participant_saved")
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
    _activity(request, participant, f"availability_set_{status or 'unmarked'}")
    return _results_response(trip, participant=_participant_payload(participant))


@require_POST
def availability_range_api(request, public_id):
    trip = _trip(public_id)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Expected a JSON request body."}, status=400)
    participant, error = _participant_for_name(trip, body.get("name"))
    if error:
        return JsonResponse({"error": error}, status=400)
    try:
        start_date = date.fromisoformat(body.get("start_date", ""))
        end_date = date.fromisoformat(body.get("end_date", ""))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Enter a valid date range."}, status=400)
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    if start_date < trip.start_date or end_date > trip.end_date:
        return JsonResponse({"error": "That range is outside the candidate dates."}, status=400)

    status = body.get("status")
    valid_statuses = {choice for choice, _label in Availability.Status.choices}
    if status in (None, "unmarked"):
        Availability.objects.filter(participant=participant, date__range=(start_date, end_date)).delete()
    elif status in valid_statuses:
        with transaction.atomic():
            selected_day = start_date
            while selected_day <= end_date:
                Availability.objects.update_or_create(
                    participant=participant,
                    date=selected_day,
                    defaults={"status": status},
                )
                selected_day += timedelta(days=1)
    else:
        return JsonResponse({"error": "Unknown availability status."}, status=400)
    _activity(request, participant, f"availability_range_set_{status or 'unmarked'}")
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
    _activity(request, participant, "proposal_created")
    return _results_response(trip, participant=_participant_payload(participant))


@require_http_methods(["PATCH", "DELETE"])
def proposal_detail_api(request, public_id, proposal_id):
    trip = _trip(public_id)
    proposal = get_object_or_404(Proposal, trip=trip, pk=proposal_id)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Expected a JSON request body."}, status=400)
    participant, error = _participant_for_name(trip, body.get("name"))
    if error:
        return JsonResponse({"error": error}, status=400)
    if request.method == "DELETE":
        proposal.delete()
        _activity(request, participant, "proposal_deleted")
        return _results_response(trip)

    fields, error = _proposal_fields(body, existing=proposal)
    if error:
        return JsonResponse({"error": error}, status=400)
    for field, value in fields.items():
        setattr(proposal, field, value)
    proposal.full_clean()
    proposal.save()
    _activity(request, participant, "proposal_updated")
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
        action = "proposal_vote_removed"
    else:
        ProposalVote.objects.create(proposal=proposal, participant=participant)
        action = "proposal_upvoted"
    _activity(request, participant, action)
    return _results_response(trip, participant=_participant_payload(participant))


@require_POST
def market_trade_api(request, public_id, market_id):
    trip = _trip(public_id)
    market = get_object_or_404(Market, trip=trip, pk=market_id)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Expected a JSON request body."}, status=400)
    participant, error = _participant_for_name(trip, body.get("name"))
    if error:
        return JsonResponse({"error": error}, status=400)
    outcome = body.get("outcome")
    if outcome not in Market.Outcome.values:
        return JsonResponse({"error": "Choose Yes or No."}, status=400)
    chips = body.get("chips")
    if isinstance(chips, bool):
        return JsonResponse({"error": "Choose a whole number of Beer Chips."}, status=400)
    try:
        chips = int(chips)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Choose a whole number of Beer Chips."}, status=400)
    if chips < 1:
        return JsonResponse({"error": "Spend at least 1 Beer Chip."}, status=400)
    with transaction.atomic():
        market = Market.objects.select_for_update().get(trip=trip, pk=market_id)
        participant = Participant.objects.select_for_update().get(pk=participant.pk)
        if market.is_resolved:
            return JsonResponse({"error": "This Beermarket has already been resolved."}, status=400)
        world_cup_market = WorldCupMarket.objects.select_related("fixture").filter(market=market).first()
        if world_cup_market and not world_cup_market.fixture.is_tradeable:
            return JsonResponse({"error": "This World Cup market is no longer accepting trades."}, status=400)
        if chips > participant.beer_chips:
            return JsonResponse({"error": "You do not have that many Beer Chips."}, status=400)
        participant.beer_chips -= chips
        participant.save(update_fields=["beer_chips"])
        MarketTrade.objects.create(market=market, participant=participant, outcome=outcome, chips=chips)
    _activity(request, participant, f"market_trade_bought_{outcome}_{chips}")
    return _results_response(trip, participant=_participant_payload(participant))
