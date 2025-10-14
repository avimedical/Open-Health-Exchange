from django.utils import timezone
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


class RootTimeView(APIView):
    """Return current UTC time, throttled to 10 requests per minute."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "root_time"

    def get(self, request, *args, **kwargs):
        # Use ISO format with space separator to match the requested example
        current_time = timezone.now().isoformat(sep=" ")
        return Response({"current_time": current_time})
