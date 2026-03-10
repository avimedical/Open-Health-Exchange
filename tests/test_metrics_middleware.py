"""
Tests for metrics middleware.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from metrics.middleware import MetricsMiddleware


class TestMetricsMiddlewareProcessRequest:
    """Tests for process_request method."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        return MetricsMiddleware(get_response=MagicMock())

    def test_sets_start_time_on_request(self, middleware):
        """Test sets _metrics_start_time attribute on request."""
        request = MagicMock(spec=[])

        before = time.time()
        middleware.process_request(request)
        after = time.time()

        assert hasattr(request, "_metrics_start_time")
        assert before <= request._metrics_start_time <= after

    def test_returns_none(self, middleware):
        """Test returns None to continue processing."""
        request = MagicMock(spec=[])

        result = middleware.process_request(request)

        assert result is None


class TestMetricsMiddlewareProcessResponse:
    """Tests for process_response method."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        return MetricsMiddleware(get_response=MagicMock())

    def test_records_api_request_with_duration(self, middleware):
        """Test records API request with calculated duration."""
        request = MagicMock()
        request.method = "GET"
        request.path = "/api/base/providers/"
        request._metrics_start_time = time.time() - 0.1  # 100ms ago
        response = MagicMock()
        response.status_code = 200

        with patch("metrics.middleware.metrics") as mock_metrics:
            result = middleware.process_response(request, response)

            mock_metrics.record_api_request.assert_called_once()
            call_kwargs = mock_metrics.record_api_request.call_args[1]
            assert call_kwargs["method"] == "GET"
            assert call_kwargs["endpoint"] == "api/base/providers"
            assert call_kwargs["status_code"] == 200
            assert call_kwargs["duration"] is not None
            assert call_kwargs["duration"] >= 0.1

        assert result == response

    def test_records_api_request_without_start_time(self, middleware):
        """Test records API request when start time not set."""
        request = MagicMock(spec=["method", "path"])
        request.method = "POST"
        request.path = "/webhooks/withings/"
        response = MagicMock()
        response.status_code = 204

        with patch("metrics.middleware.metrics") as mock_metrics:
            middleware.process_response(request, response)

            call_kwargs = mock_metrics.record_api_request.call_args[1]
            assert call_kwargs["duration"] is None

    def test_handles_exception_gracefully(self, middleware):
        """Test handles exception in metrics recording gracefully."""
        request = MagicMock()
        request.method = "GET"
        request.path = "/api/base/providers/"
        response = MagicMock()
        response.status_code = 200

        with patch("metrics.middleware.metrics") as mock_metrics:
            mock_metrics.record_api_request.side_effect = Exception("Metrics error")
            result = middleware.process_response(request, response)

        assert result == response

    def test_returns_response(self, middleware):
        """Test returns the response object."""
        request = MagicMock()
        request.method = "GET"
        request.path = "/"
        response = MagicMock()
        response.status_code = 200

        with patch("metrics.middleware.metrics"):
            result = middleware.process_response(request, response)

        assert result == response


class TestMetricsMiddlewareProcessException:
    """Tests for process_exception method."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        return MetricsMiddleware(get_response=MagicMock())

    def test_records_500_status_code(self, middleware):
        """Test records 500 status code for exceptions."""
        request = MagicMock()
        request.method = "GET"
        request.path = "/api/base/providers/"
        request._metrics_start_time = time.time() - 0.05
        exception = Exception("Test error")

        with patch("metrics.middleware.metrics") as mock_metrics:
            middleware.process_exception(request, exception)

            call_kwargs = mock_metrics.record_api_request.call_args[1]
            assert call_kwargs["status_code"] == 500

    def test_records_exception_without_start_time(self, middleware):
        """Test records exception when start time not set."""
        request = MagicMock(spec=["method", "path"])
        request.method = "POST"
        request.path = "/webhooks/fitbit/"
        exception = Exception("Test error")

        with patch("metrics.middleware.metrics") as mock_metrics:
            middleware.process_exception(request, exception)

            call_kwargs = mock_metrics.record_api_request.call_args[1]
            assert call_kwargs["duration"] is None

    def test_handles_metrics_exception_gracefully(self, middleware):
        """Test handles exception in metrics recording gracefully."""
        request = MagicMock()
        request.method = "GET"
        request.path = "/api/base/"
        exception = Exception("Original error")

        with patch("metrics.middleware.metrics") as mock_metrics:
            mock_metrics.record_api_request.side_effect = Exception("Metrics error")
            result = middleware.process_exception(request, exception)

        # Should not raise, just log warning
        assert result is None

    def test_returns_none(self, middleware):
        """Test returns None to let Django handle exception."""
        request = MagicMock()
        request.method = "GET"
        request.path = "/"
        exception = Exception("Test error")

        with patch("metrics.middleware.metrics"):
            result = middleware.process_exception(request, exception)

        assert result is None


class TestGetEndpointPattern:
    """Tests for _get_endpoint_pattern method."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        return MetricsMiddleware(get_response=MagicMock())

    def test_api_endpoint_three_parts(self, middleware):
        """Test API endpoint with three parts."""
        result = middleware._get_endpoint_pattern("/api/base/providers/")
        assert result == "api/base/providers"

    def test_api_endpoint_two_parts(self, middleware):
        """Test API endpoint with two parts."""
        result = middleware._get_endpoint_pattern("/api/metrics/")
        assert result == "api/metrics"

    def test_api_endpoint_more_than_three_parts(self, middleware):
        """Test API endpoint with more than three parts truncates."""
        result = middleware._get_endpoint_pattern("/api/base/providers/123/details/")
        assert result == "api/base/providers"

    def test_webhook_endpoint(self, middleware):
        """Test webhook endpoint normalization."""
        result = middleware._get_endpoint_pattern("/webhooks/withings/")
        assert result == "webhooks/withings"

    def test_webhook_endpoint_fitbit(self, middleware):
        """Test Fitbit webhook endpoint."""
        result = middleware._get_endpoint_pattern("/webhooks/fitbit/")
        assert result == "webhooks/fitbit"

    def test_health_endpoint(self, middleware):
        """Test health endpoint."""
        result = middleware._get_endpoint_pattern("/health/")
        assert result == "health"

    def test_health_endpoint_no_trailing_slash(self, middleware):
        """Test health endpoint without trailing slash."""
        result = middleware._get_endpoint_pattern("/health")
        assert result == "health"

    def test_admin_endpoint(self, middleware):
        """Test admin endpoint."""
        result = middleware._get_endpoint_pattern("/admin/")
        assert result == "admin"

    def test_metrics_endpoint(self, middleware):
        """Test metrics endpoint."""
        result = middleware._get_endpoint_pattern("/metrics/")
        assert result == "metrics"

    def test_root_path(self, middleware):
        """Test root path returns 'root'."""
        result = middleware._get_endpoint_pattern("/")
        assert result == "root"

    def test_empty_path(self, middleware):
        """Test empty path returns 'root'."""
        result = middleware._get_endpoint_pattern("")
        assert result == "root"

    def test_unknown_path(self, middleware):
        """Test unknown path returns as-is."""
        result = middleware._get_endpoint_pattern("/some/random/path/")
        assert result == "some/random/path"

    def test_strips_leading_trailing_slashes(self, middleware):
        """Test strips leading and trailing slashes."""
        result = middleware._get_endpoint_pattern("///path///")
        assert result == "path"


class TestMetricsMiddlewareIntegration:
    """Integration tests for metrics middleware."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        return MetricsMiddleware(get_response=MagicMock())

    def test_full_request_lifecycle(self, middleware):
        """Test full request lifecycle records correct metrics."""
        request = MagicMock()
        request.method = "GET"
        request.path = "/api/base/providers/"
        response = MagicMock()
        response.status_code = 200

        with patch("metrics.middleware.metrics") as mock_metrics:
            # Process request
            middleware.process_request(request)

            # Simulate some processing time
            time.sleep(0.01)

            # Process response
            middleware.process_response(request, response)

            mock_metrics.record_api_request.assert_called_once()
            call_kwargs = mock_metrics.record_api_request.call_args[1]
            assert call_kwargs["method"] == "GET"
            assert call_kwargs["status_code"] == 200
            assert call_kwargs["duration"] >= 0.01

    def test_request_with_exception(self, middleware):
        """Test request that raises exception records 500."""
        request = MagicMock()
        request.method = "POST"
        request.path = "/api/base/sync/"
        exception = ValueError("Invalid data")

        with patch("metrics.middleware.metrics") as mock_metrics:
            middleware.process_request(request)
            middleware.process_exception(request, exception)

            call_kwargs = mock_metrics.record_api_request.call_args[1]
            assert call_kwargs["status_code"] == 500
            assert call_kwargs["duration"] is not None
