from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("trips/new/", views.create_trip, name="create_trip"),
    path("trips/<uuid:public_id>/", views.trip_detail, name="trip_detail"),
    path("trips/<uuid:public_id>/leaderboard/", views.leaderboard, name="leaderboard"),
    path("trips/<uuid:public_id>/chip-leaderboard/", views.chip_leaderboard_view, name="chip_leaderboard"),
    path("trips/<uuid:public_id>/beermarket/", views.beermarket, name="beermarket"),
    path("trips/<uuid:public_id>/beer-clicker/", views.beer_clicker, name="beer_clicker"),
    path("trips/<uuid:public_id>/api/beer-clicker/status/", views.beer_clicker_status_api, name="beer_clicker_status_api"),
    path("trips/<uuid:public_id>/api/beer-clicker/click/", views.beer_clicker_click_api, name="beer_clicker_click_api"),
    path("trips/<uuid:public_id>/api/beer-clicker/convert/", views.beer_clicker_convert_api, name="beer_clicker_convert_api"),
    path("trips/<uuid:public_id>/api/participant/", views.participant_api, name="participant_api"),
    path("trips/<uuid:public_id>/api/availability/", views.availability_api, name="availability_api"),
    path("trips/<uuid:public_id>/api/availability/range/", views.availability_range_api, name="availability_range_api"),
    path("trips/<uuid:public_id>/api/results/", views.results_api, name="results_api"),
    path("trips/<uuid:public_id>/api/proposals/", views.proposal_collection_api, name="proposal_collection_api"),
    path("trips/<uuid:public_id>/api/proposals/<int:proposal_id>/", views.proposal_detail_api, name="proposal_detail_api"),
    path("trips/<uuid:public_id>/api/proposals/<int:proposal_id>/vote/", views.proposal_vote_api, name="proposal_vote_api"),
    path("trips/<uuid:public_id>/api/proposals/<int:proposal_id>/booking-interest/", views.proposal_booking_interest_api, name="proposal_booking_interest_api"),
    path("trips/<uuid:public_id>/api/markets/<int:market_id>/trade/", views.market_trade_api, name="market_trade_api"),
]
