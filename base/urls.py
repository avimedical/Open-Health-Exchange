from django.urls import include, path
from rest_framework import routers

from base.views import (
    HealthSyncViewSet,
    InitiateProviderLinkingView,
    ProviderLinkErrorView,
    ProviderLinkSuccessView,
    ProviderViewSet,
    provider_linking_status,
)

# API router for ViewSets
router = routers.DefaultRouter()
router.register(r"providers", ProviderViewSet, basename="provider")
router.register(r"sync", HealthSyncViewSet, basename="health-sync")

urlpatterns = [
    # API endpoints using ViewSets
    path("", include(router.urls)),
    # Provider OAuth linking endpoints (keep existing for OAuth flow)
    path("link/success/", ProviderLinkSuccessView.as_view(), name="provider-link-success"),
    path("link/error/", ProviderLinkErrorView.as_view(), name="provider-link-error"),
    path("link/<str:provider>/", InitiateProviderLinkingView.as_view(), name="initiate-provider-linking"),
    path("link/<str:provider>/status/", provider_linking_status, name="provider-linking-status"),
]
