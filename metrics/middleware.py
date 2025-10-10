"""
Django middleware for metrics collection.
"""

import logging
import time

from django.utils.deprecation import MiddlewareMixin

from .collectors import metrics

logger = logging.getLogger(__name__)


class MetricsMiddleware(MiddlewareMixin):
    """Middleware to collect API request metrics."""

    def process_request(self, request):
        """Start timing the request."""
        request._metrics_start_time = time.time()
        return None

    def process_response(self, request, response):
        """Record request metrics."""
        try:
            # Calculate request duration
            duration = None
            if hasattr(request, "_metrics_start_time"):
                duration = time.time() - request._metrics_start_time

            # Extract endpoint from path
            endpoint = self._get_endpoint_pattern(request.path)

            # Record the API request
            metrics.record_api_request(
                method=request.method, endpoint=endpoint, status_code=response.status_code, duration=duration
            )

        except Exception as e:
            logger.warning(f"Failed to record API metrics: {e}")

        return response

    def process_exception(self, request, exception):
        """Record exceptions as 500 errors."""
        try:
            duration = None
            if hasattr(request, "_metrics_start_time"):
                duration = time.time() - request._metrics_start_time

            endpoint = self._get_endpoint_pattern(request.path)

            metrics.record_api_request(method=request.method, endpoint=endpoint, status_code=500, duration=duration)

        except Exception as e:
            logger.warning(f"Failed to record exception metrics: {e}")

        return None

    def _get_endpoint_pattern(self, path: str) -> str:
        """Extract a normalized endpoint pattern from the request path."""
        # Remove leading/trailing slashes and normalize
        path = path.strip("/")

        # Common API patterns
        if path.startswith("api/"):
            parts = path.split("/")
            if len(parts) >= 2:
                # api/base/providers/ -> api/base/providers
                if len(parts) >= 3:
                    return f"{parts[0]}/{parts[1]}/{parts[2]}"
                return f"{parts[0]}/{parts[1]}"

        # Webhook patterns
        if path.startswith("webhooks/"):
            parts = path.split("/")
            if len(parts) >= 2:
                return f"webhooks/{parts[1]}"

        # Health checks and admin
        if path in ["health", "health/", "admin", "admin/", "metrics", "metrics/"]:
            return path.rstrip("/")

        # Default to path without parameters
        return path or "root"
