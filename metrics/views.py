"""
Metrics and health check views.
"""

import logging
import time

from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.views import View
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .collectors import get_registry, metrics

logger = logging.getLogger(__name__)


class MetricsView(View):
    """Prometheus metrics endpoint."""

    def get(self, request):
        """Return Prometheus metrics."""
        try:
            # Update system metrics before export
            metrics.update_system_metrics()

            # Generate metrics in Prometheus format
            registry = get_registry()
            data = generate_latest(registry)

            return HttpResponse(data, content_type=CONTENT_TYPE_LATEST)

        except Exception as e:
            logger.error(f"Failed to generate metrics: {e}")
            return HttpResponse("Error generating metrics", status=500)


class HealthCheckView(View):
    """Health check endpoint for load balancers and monitoring."""

    def get(self, request):
        """Perform health checks and return status."""
        start_time = time.time()
        health_status = {"status": "healthy", "timestamp": int(time.time()), "checks": {}}

        # Database health check
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                health_status["checks"]["database"] = {
                    "status": "healthy",
                    "response_time_ms": round((time.time() - start_time) * 1000, 2),
                }
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")
            health_status["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
            health_status["status"] = "unhealthy"

        # Redis health check
        try:
            cache_start = time.time()
            cache.set("health_check", "ok", 10)
            cache.get("health_check")
            health_status["checks"]["redis"] = {
                "status": "healthy",
                "response_time_ms": round((time.time() - cache_start) * 1000, 2),
            }
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            health_status["checks"]["redis"] = {"status": "unhealthy", "error": str(e)}
            health_status["status"] = "unhealthy"

        # Huey health check
        try:
            import redis
            from django.conf import settings

            redis_client = redis.Redis(connection_pool=settings.HUEY.storage.conn)
            huey_start = time.time()
            redis_client.ping()
            health_status["checks"]["huey"] = {
                "status": "healthy",
                "response_time_ms": round((time.time() - huey_start) * 1000, 2),
            }
        except Exception as e:
            logger.warning(f"Huey health check failed: {e}")
            health_status["checks"]["huey"] = {"status": "unhealthy", "error": str(e)}

        # Set overall response time
        health_status["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

        # Return appropriate status code
        status_code = 200 if health_status["status"] == "healthy" else 503

        return JsonResponse(health_status, status=status_code)


class ReadinessCheckView(View):
    """Readiness check for Kubernetes deployment."""

    def get(self, request):
        """Check if the application is ready to serve traffic."""
        checks = {"database": False, "redis": False}

        # Quick database check
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                checks["database"] = True
        except Exception:
            pass

        # Quick Redis check
        try:
            cache.get("readiness_check")
            checks["redis"] = True
        except Exception:
            pass

        # App is ready if both critical services are available
        ready = checks["database"] and checks["redis"]

        response = {"ready": ready, "checks": checks}

        status_code = 200 if ready else 503
        return JsonResponse(response, status=status_code)


class LivenessCheckView(View):
    """Liveness check for Kubernetes deployment."""

    def get(self, request):
        """Check if the application is alive (basic functionality)."""
        # Simple liveness check - if we can respond, we're alive
        response = {"alive": True, "timestamp": int(time.time())}

        return JsonResponse(response, status=200)
