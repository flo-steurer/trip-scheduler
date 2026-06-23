from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("trips/new/", views.create_trip, name="create_trip"),
    path("trips/<uuid:public_id>/", views.trip_detail, name="trip_detail"),
    path("trips/<uuid:public_id>/api/participant/", views.participant_api, name="participant_api"),
    path("trips/<uuid:public_id>/api/availability/", views.availability_api, name="availability_api"),
    path("trips/<uuid:public_id>/api/results/", views.results_api, name="results_api"),
    path("trips/<uuid:public_id>/api/proposals/", views.proposal_collection_api, name="proposal_collection_api"),
    path("trips/<uuid:public_id>/api/proposals/<int:proposal_id>/", views.proposal_detail_api, name="proposal_detail_api"),
    path("trips/<uuid:public_id>/api/proposals/<int:proposal_id>/vote/", views.proposal_vote_api, name="proposal_vote_api"),
]
