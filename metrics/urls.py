"""
Metrics and health check URL configuration.
"""

from django.urls import path

from .views import HealthCheckView, LivenessCheckView, MetricsView, ReadinessCheckView

app_name = "metrics"

urlpatterns = [
    path("metrics/", MetricsView.as_view(), name="prometheus-metrics"),
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("ready/", ReadinessCheckView.as_view(), name="readiness-check"),
    path("live/", LivenessCheckView.as_view(), name="liveness-check"),
]
