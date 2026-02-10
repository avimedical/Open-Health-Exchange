"""
Tests for metrics collectors and health check views.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory

from metrics.collectors import (
    MetricsCollector,
    get_registry,
    initialize_metrics,
    metrics,
)
from metrics.views import (
    HealthCheckView,
    LivenessCheckView,
    MetricsView,
    ReadinessCheckView,
)


class TestMetricsCollector:
    """Tests for MetricsCollector class."""

    @pytest.fixture
    def collector(self):
        """Create a new MetricsCollector instance."""
        return MetricsCollector()

    def test_collector_initialization(self, collector):
        """Test collector initializes with start time."""
        assert collector.start_time is not None
        assert collector.start_time <= time.time()

    def test_record_sync_operation(self, collector):
        """Test recording sync operations."""
        # Should not raise any exceptions
        collector.record_sync_operation(
            provider="withings",
            operation_type="heart_rate_fetch",
            status="success",
            duration=1.5,
        )

    def test_record_sync_operation_without_duration(self, collector):
        """Test recording sync operation without duration."""
        collector.record_sync_operation(
            provider="fitbit",
            operation_type="steps_fetch",
            status="error",
        )

    def test_record_data_points(self, collector):
        """Test recording data points processed."""
        collector.record_data_points(provider="withings", data_type="heart_rate", count=100)

    def test_record_fhir_operation(self, collector):
        """Test recording FHIR operations."""
        collector.record_fhir_operation(
            operation="create",
            resource_type="Observation",
            status="success",
            duration=0.5,
        )

    def test_record_fhir_operation_without_duration(self, collector):
        """Test recording FHIR operation without duration."""
        collector.record_fhir_operation(
            operation="search",
            resource_type="Device",
            status="success",
        )

    def test_record_api_request(self, collector):
        """Test recording API requests."""
        collector.record_api_request(
            method="GET",
            endpoint="/api/base/providers/",
            status_code=200,
            duration=0.1,
        )

    def test_record_api_request_without_duration(self, collector):
        """Test recording API request without duration."""
        collector.record_api_request(
            method="POST",
            endpoint="/webhooks/withings/",
            status_code=202,
        )

    def test_record_webhook(self, collector):
        """Test recording webhook requests."""
        collector.record_webhook(
            provider="withings",
            status="accepted",
            processing_time=0.05,
        )

    def test_record_webhook_without_processing_time(self, collector):
        """Test recording webhook without processing time."""
        collector.record_webhook(provider="fitbit", status="rejected")

    def test_record_provider_api_error(self, collector):
        """Test recording provider API errors."""
        collector.record_provider_api_error(provider="withings", error_type="rate_limit")

    def test_record_rate_limit(self, collector):
        """Test recording rate limit hits."""
        collector.record_rate_limit(provider="fitbit")

    def test_update_system_metrics(self, collector):
        """Test updating system metrics doesn't raise errors."""
        with patch("django_redis.get_redis_connection"):
            with patch("metrics.collectors.redis"):
                collector.update_system_metrics()


class TestGlobalMetrics:
    """Tests for global metrics instance."""

    def test_global_metrics_instance_exists(self):
        """Test global metrics instance is available."""
        assert metrics is not None
        assert isinstance(metrics, MetricsCollector)

    def test_get_registry_returns_collector_registry(self):
        """Test get_registry returns the app registry."""
        registry = get_registry()
        assert registry is not None


class TestInitializeMetrics:
    """Tests for metrics initialization."""

    def test_initialize_metrics_with_settings(self):
        """Test metrics initialization with application settings."""
        with patch("django.conf.settings") as mock_settings:
            mock_settings.APPLICATION_VERSION = "1.0.0"
            mock_settings.ENVIRONMENT = "test"
            mock_settings.DEBUG = False

            # Should not raise any exceptions
            initialize_metrics()

    def test_initialize_metrics_handles_missing_settings(self):
        """Test metrics initialization handles missing settings gracefully."""
        # Should not raise even when settings are missing (uses getattr defaults)
        initialize_metrics()


class TestMetricsView:
    """Tests for Prometheus metrics endpoint."""

    @pytest.fixture
    def request_factory(self):
        """Create request factory."""
        return RequestFactory()

    def test_metrics_view_returns_prometheus_format(self, request_factory):
        """Test metrics endpoint returns Prometheus format."""
        request = request_factory.get("/api/metrics/metrics/")
        view = MetricsView()

        with patch.object(metrics, "update_system_metrics"):
            response = view.get(request)

        assert response.status_code == 200
        assert "text/plain" in response["Content-Type"]

    def test_metrics_view_handles_error(self, request_factory):
        """Test metrics endpoint handles errors gracefully."""
        request = request_factory.get("/api/metrics/metrics/")
        view = MetricsView()

        with patch("metrics.views.get_registry", side_effect=Exception("Registry error")):
            response = view.get(request)

        assert response.status_code == 500


class TestHealthCheckView:
    """Tests for health check endpoint."""

    @pytest.fixture
    def request_factory(self):
        """Create request factory."""
        return RequestFactory()

    def test_health_check_healthy(self, request_factory):
        """Test health check returns healthy when all services are up."""
        request = request_factory.get("/api/metrics/health/")
        view = HealthCheckView()

        with patch("metrics.views.connection") as mock_connection:
            mock_cursor = MagicMock()
            mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

            with patch("metrics.views.cache") as mock_cache:
                mock_cache.set.return_value = None
                mock_cache.get.return_value = "ok"

                with patch("redis.Redis") as mock_redis:
                    mock_client = MagicMock()
                    mock_redis.return_value = mock_client
                    mock_client.ping.return_value = True

                    with patch("django.conf.settings") as mock_settings:
                        mock_settings.HUEY = MagicMock()
                        mock_settings.HUEY.storage.conn = MagicMock()

                        response = view.get(request)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["status"] == "healthy"
        assert "checks" in data
        assert "database" in data["checks"]
        assert "redis" in data["checks"]

    def test_health_check_database_unhealthy(self, request_factory):
        """Test health check returns unhealthy when database is down."""
        request = request_factory.get("/api/metrics/health/")
        view = HealthCheckView()

        with patch("metrics.views.connection") as mock_connection:
            mock_connection.cursor.return_value.__enter__.return_value.execute.side_effect = Exception("DB error")

            with patch("metrics.views.cache") as mock_cache:
                mock_cache.set.return_value = None
                mock_cache.get.return_value = "ok"

                with patch("redis.Redis"):
                    with patch("django.conf.settings") as mock_settings:
                        mock_settings.HUEY = MagicMock()
                        mock_settings.HUEY.storage.conn = MagicMock()

                        response = view.get(request)

        assert response.status_code == 503
        data = json.loads(response.content)
        assert data["status"] == "unhealthy"
        assert data["checks"]["database"]["status"] == "unhealthy"

    def test_health_check_redis_unhealthy(self, request_factory):
        """Test health check returns unhealthy when Redis is down."""
        request = request_factory.get("/api/metrics/health/")
        view = HealthCheckView()

        with patch("metrics.views.connection") as mock_connection:
            mock_cursor = MagicMock()
            mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

            with patch("metrics.views.cache") as mock_cache:
                mock_cache.set.side_effect = Exception("Redis error")

                with patch("redis.Redis"):
                    with patch("django.conf.settings") as mock_settings:
                        mock_settings.HUEY = MagicMock()
                        mock_settings.HUEY.storage.conn = MagicMock()

                        response = view.get(request)

        assert response.status_code == 503
        data = json.loads(response.content)
        assert data["status"] == "unhealthy"
        assert data["checks"]["redis"]["status"] == "unhealthy"


class TestReadinessCheckView:
    """Tests for Kubernetes readiness probe."""

    @pytest.fixture
    def request_factory(self):
        """Create request factory."""
        return RequestFactory()

    def test_readiness_check_ready(self, request_factory):
        """Test readiness check when app is ready."""
        request = request_factory.get("/api/metrics/ready/")
        view = ReadinessCheckView()

        with patch("metrics.views.connection") as mock_connection:
            mock_cursor = MagicMock()
            mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

            with patch("metrics.views.cache") as mock_cache:
                mock_cache.get.return_value = None

                response = view.get(request)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["ready"] is True
        assert data["checks"]["database"] is True
        assert data["checks"]["redis"] is True

    def test_readiness_check_not_ready_database(self, request_factory):
        """Test readiness check when database is unavailable."""
        request = request_factory.get("/api/metrics/ready/")
        view = ReadinessCheckView()

        with patch("metrics.views.connection") as mock_connection:
            mock_connection.cursor.return_value.__enter__.return_value.execute.side_effect = Exception("DB error")

            with patch("metrics.views.cache") as mock_cache:
                mock_cache.get.return_value = None

                response = view.get(request)

        assert response.status_code == 503
        data = json.loads(response.content)
        assert data["ready"] is False
        assert data["checks"]["database"] is False

    def test_readiness_check_not_ready_redis(self, request_factory):
        """Test readiness check when Redis is unavailable."""
        request = request_factory.get("/api/metrics/ready/")
        view = ReadinessCheckView()

        with patch("metrics.views.connection") as mock_connection:
            mock_cursor = MagicMock()
            mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

            with patch("metrics.views.cache") as mock_cache:
                mock_cache.get.side_effect = Exception("Redis error")

                response = view.get(request)

        assert response.status_code == 503
        data = json.loads(response.content)
        assert data["ready"] is False
        assert data["checks"]["redis"] is False


class TestLivenessCheckView:
    """Tests for Kubernetes liveness probe."""

    @pytest.fixture
    def request_factory(self):
        """Create request factory."""
        return RequestFactory()

    def test_liveness_check_always_alive(self, request_factory):
        """Test liveness check always returns alive."""
        request = request_factory.get("/api/metrics/live/")
        view = LivenessCheckView()

        response = view.get(request)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["alive"] is True
        assert "timestamp" in data

    def test_liveness_check_timestamp_is_current(self, request_factory):
        """Test liveness check timestamp is approximately current."""
        request = request_factory.get("/api/metrics/live/")
        view = LivenessCheckView()

        before = int(time.time())
        response = view.get(request)
        after = int(time.time())

        data = json.loads(response.content)
        assert before <= data["timestamp"] <= after
