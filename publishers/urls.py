from django.urls import include, path
from rest_framework import routers

router = routers.DefaultRouter()
# router.register(r'your-model', YourViewSet) # Example

urlpatterns = [
    path("", include(router.urls)),
]
