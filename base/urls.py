from django.urls import path, include
from rest_framework import routers

from base.views import ProviderViewSet
 

router = routers.DefaultRouter()
router.register(r'providers', ProviderViewSet, basename='provider')


urlpatterns = [
    path('', include(router.urls)),
]
