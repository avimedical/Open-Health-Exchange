from django.urls import path, include
from rest_framework import routers

router = routers.DefaultRouter()
# router.register(r'your-model', YourViewSet) # Example

urlpatterns = [
    path('', include(router.urls)),
]
