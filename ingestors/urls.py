from django.urls import path, include
from rest_framework import routers
from ingestors.views import IngestorsViewSet

router = routers.DefaultRouter()
router.register(r'ingestors', IngestorsViewSet, basename='ingestors')  # rename router and basename

urlpatterns = [
    path('', include(router.urls)),
]
