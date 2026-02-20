"""
Tests for unified webhook handler.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory
from rest_framework.response import Response

from ingestors.health_data_constants import Provider
from webhooks.unified_webhook_handler import (
    UnifiedWebhookHandler,
    WebhookMetrics,
    WebhookQuery,
    get_unified_webhook_handler,
)


class TestWebhookQuery:
    """Tests for WebhookQuery dataclass."""

    def test_query_creation(self):
        """Test creating a WebhookQuery."""
        request = MagicMock()
        query = WebhookQuery(
            provider=Provider.WITHINGS,
            request_method="POST",
            payload={"data": "test"},
            request=request,
        )

        assert query.provider == Provider.WITHINGS
        assert query.request_method == "POST"
        assert query.payload == {"data": "test"}
        assert query.request == request

    def test_cache_key_generation(self):
        """Test cache key generation."""
        request = MagicMock()
        query = WebhookQuery(
            provider=Provider.WITHINGS,
            request_method="POST",
            payload={},
            request=request,
        )

        cache_key = query.cache_key
        assert "webhook:" in cache_key
        assert "withings" in cache_key
        assert "POST" in cache_key


class TestWebhookMetrics:
    """Tests for WebhookMetrics class."""

    def test_initialization(self):
        """Test metrics initialization."""
        metrics = WebhookMetrics()
        assert metrics.webhook_counts == {}
        assert metrics.error_counts == {}

    def test_increment_webhook(self):
        """Test incrementing webhook count."""
        metrics = WebhookMetrics()
        metrics.increment_webhook("withings")
        metrics.increment_webhook("withings")
        metrics.increment_webhook("fitbit")

        assert metrics.webhook_counts["withings"] == 2
        assert metrics.webhook_counts["fitbit"] == 1

    def test_increment_error(self):
        """Test incrementing error count."""
        metrics = WebhookMetrics()
        metrics.increment_error("withings")
        metrics.increment_error("fitbit")
        metrics.increment_error("fitbit")

        assert metrics.error_counts["withings"] == 1
        assert metrics.error_counts["fitbit"] == 2

    def test_get_stats(self):
        """Test getting stats."""
        metrics = WebhookMetrics()
        metrics.increment_webhook("withings")
        metrics.increment_error("withings")

        stats = metrics.get_stats()

        assert "webhook_counts" in stats
        assert "error_counts" in stats
        assert stats["webhook_counts"]["withings"] == 1
        assert stats["error_counts"]["withings"] == 1


class TestUnifiedWebhookHandler:
    """Tests for UnifiedWebhookHandler class."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    @pytest.fixture
    def mock_processor(self):
        """Create mock processor."""
        return MagicMock()

    @pytest.fixture
    def mock_validator(self):
        """Create mock validator."""
        return MagicMock()

    @pytest.fixture
    def handler(self, mock_settings, mock_processor, mock_validator):
        """Create handler instance."""
        with patch("webhooks.unified_webhook_handler.WebhookPayloadProcessor", return_value=mock_processor):
            with patch("webhooks.unified_webhook_handler.WebhookSignatureValidator", return_value=mock_validator):
                return UnifiedWebhookHandler()

    @pytest.fixture
    def request_factory(self):
        """Create Django request factory."""
        return RequestFactory()

    def test_initialization(self, handler):
        """Test handler initialization."""
        assert handler.processor is not None
        assert handler.validator is not None


class TestHandleWebhookMethods:
    """Tests for handle_webhook method with different HTTP methods."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    @pytest.fixture
    def handler(self, mock_settings):
        """Create handler instance."""
        with patch("webhooks.unified_webhook_handler.WebhookPayloadProcessor"):
            with patch("webhooks.unified_webhook_handler.WebhookSignatureValidator"):
                return UnifiedWebhookHandler()

    @pytest.fixture
    def request_factory(self):
        """Create Django request factory."""
        return RequestFactory()

    def test_handle_get_withings_with_challenge(self, handler, request_factory):
        """Test handling GET request with Withings challenge."""
        request = request_factory.get("/webhook/withings/?challenge=test_challenge_123")

        response = handler.handle_webhook(Provider.WITHINGS, request)

        assert response.status_code == 200
        assert response.content.decode() == "test_challenge_123"

    def test_handle_get_withings_without_challenge(self, handler, request_factory):
        """Test handling GET request without Withings challenge."""
        request = request_factory.get("/webhook/withings/")

        response = handler.handle_webhook(Provider.WITHINGS, request)

        assert response.status_code == 400

    def test_handle_get_fitbit_with_verify(self, handler, request_factory):
        """Test handling GET request with Fitbit verify."""
        request = request_factory.get("/webhook/fitbit/?verify=test_verify_code")

        response = handler.handle_webhook(Provider.FITBIT, request)

        assert response.status_code == 204

    def test_handle_get_fitbit_without_verify(self, handler, request_factory):
        """Test handling GET request without Fitbit verify."""
        request = request_factory.get("/webhook/fitbit/")

        response = handler.handle_webhook(Provider.FITBIT, request)

        assert response.status_code == 400

    def test_handle_head_request(self, handler, request_factory):
        """Test handling HEAD request."""
        request = request_factory.head("/webhook/withings/")

        response = handler.handle_webhook(Provider.WITHINGS, request)

        assert response.status_code == 200

    def test_handle_unsupported_method(self, handler, request_factory):
        """Test handling unsupported HTTP method."""
        request = request_factory.delete("/webhook/withings/")

        response = handler.handle_webhook(Provider.WITHINGS, request)

        assert response.status_code == 400


class TestHandleNotificationRequest:
    """Tests for _handle_notification_request method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    @pytest.fixture
    def mock_validator(self):
        """Create mock validator."""
        validator = MagicMock()
        validator.validate_withings_signature.return_value = True
        validator.validate_fitbit_signature.return_value = True
        return validator

    @pytest.fixture
    def mock_processor(self):
        """Create mock processor."""
        processor = MagicMock()
        processor.process_withings_webhook.return_value = [
            {"user_id": "test-user", "provider": "withings", "data_types": ["heart_rate"]}
        ]
        processor.process_fitbit_webhook.return_value = [
            {"user_id": "test-user", "provider": "fitbit", "data_types": ["activities"]}
        ]
        return processor

    @pytest.fixture
    def handler(self, mock_settings, mock_validator, mock_processor):
        """Create handler instance."""
        handler = UnifiedWebhookHandler.__new__(UnifiedWebhookHandler)
        handler.config = {}
        handler.processor = mock_processor
        handler.validator = mock_validator
        handler.logger = MagicMock()
        return handler

    @pytest.fixture
    def request_factory(self):
        """Create Django request factory."""
        return RequestFactory()

    def test_handle_post_invalid_signature(self, handler, request_factory):
        """Test handling POST with invalid signature."""
        handler.validator.validate_withings_signature.return_value = False

        request = request_factory.post(
            "/webhook/withings/",
            data=json.dumps({"test": "data"}),
            content_type="application/json",
        )

        response = handler._handle_notification_request(Provider.WITHINGS, request)

        assert response.status_code == 403

    def test_handle_post_empty_body(self, handler, request_factory):
        """Test handling POST with empty body."""
        request = request_factory.post(
            "/webhook/withings/",
            data="",
            content_type="application/json",
        )

        response = handler._handle_notification_request(Provider.WITHINGS, request)

        assert response.status_code == 400

    def test_handle_post_invalid_json(self, handler, request_factory):
        """Test handling POST with invalid JSON."""
        request = request_factory.post(
            "/webhook/withings/",
            data="not valid json",
            content_type="application/json",
        )

        response = handler._handle_notification_request(Provider.WITHINGS, request)

        assert response.status_code == 400

    def test_handle_post_success_withings(self, handler, request_factory):
        """Test successful POST handling for Withings."""
        request = request_factory.post(
            "/webhook/withings/",
            data=json.dumps({"userid": 123, "appli": 4}),
            content_type="application/json",
        )

        with patch("webhooks.unified_webhook_handler.sync_user_health_data_realtime") as mock_task:
            mock_task.return_value = MagicMock(id="task-123")

            response = handler._handle_notification_request(Provider.WITHINGS, request)

            assert isinstance(response, Response)
            assert response.status_code == 202
            assert response.data["status"] == "accepted"
            assert response.data["provider"] == "withings"

    def test_handle_post_success_fitbit(self, handler, request_factory):
        """Test successful POST handling for Fitbit."""
        request = request_factory.post(
            "/webhook/fitbit/",
            data=json.dumps([{"collectionType": "activities", "ownerType": "user"}]),
            content_type="application/json",
        )

        with patch("webhooks.unified_webhook_handler.sync_user_health_data_realtime") as mock_task:
            mock_task.return_value = MagicMock(id="task-456")

            response = handler._handle_notification_request(Provider.FITBIT, request)

            assert isinstance(response, Response)
            assert response.status_code == 202


class TestValidateSignature:
    """Tests for _validate_signature method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    @pytest.fixture
    def handler(self, mock_settings):
        """Create handler instance."""
        with patch("webhooks.unified_webhook_handler.WebhookPayloadProcessor"):
            with patch("webhooks.unified_webhook_handler.WebhookSignatureValidator") as mock_validator_cls:
                handler = UnifiedWebhookHandler()
                handler.validator = mock_validator_cls.return_value
                return handler

    def test_validate_withings_signature(self, handler):
        """Test validating Withings signature."""
        handler.validator.validate_withings_signature.return_value = True
        request = MagicMock()

        result = handler._validate_signature(Provider.WITHINGS, request)

        assert result is True
        handler.validator.validate_withings_signature.assert_called_once_with(request)

    def test_validate_fitbit_signature(self, handler):
        """Test validating Fitbit signature."""
        handler.validator.validate_fitbit_signature.return_value = True
        request = MagicMock()

        result = handler._validate_signature(Provider.FITBIT, request)

        assert result is True
        handler.validator.validate_fitbit_signature.assert_called_once_with(request)


class TestParseRequestPayload:
    """Tests for _parse_request_payload method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    @pytest.fixture
    def handler(self, mock_settings):
        """Create handler instance."""
        with patch("webhooks.unified_webhook_handler.WebhookPayloadProcessor"):
            with patch("webhooks.unified_webhook_handler.WebhookSignatureValidator"):
                return UnifiedWebhookHandler()

    @pytest.fixture
    def request_factory(self):
        """Create Django request factory."""
        return RequestFactory()

    def test_parse_valid_json(self, handler, request_factory):
        """Test parsing valid JSON payload."""
        request = request_factory.post(
            "/webhook/",
            data=json.dumps({"test": "data"}),
            content_type="application/json",
        )

        result = handler._parse_request_payload(Provider.WITHINGS, request)

        assert result == {"test": "data"}

    def test_parse_valid_json_array(self, handler, request_factory):
        """Test parsing valid JSON array payload."""
        request = request_factory.post(
            "/webhook/",
            data=json.dumps([{"item": 1}, {"item": 2}]),
            content_type="application/json",
        )

        result = handler._parse_request_payload(Provider.FITBIT, request)

        assert result == [{"item": 1}, {"item": 2}]

    def test_parse_empty_body(self, handler, request_factory):
        """Test parsing empty body."""
        request = request_factory.post(
            "/webhook/",
            data="",
            content_type="application/json",
        )

        result = handler._parse_request_payload(Provider.WITHINGS, request)

        assert result is None

    def test_parse_invalid_json(self, handler, request_factory):
        """Test parsing invalid JSON."""
        request = request_factory.post(
            "/webhook/",
            data="not valid json",
            content_type="application/json",
        )

        result = handler._parse_request_payload(Provider.WITHINGS, request)

        assert result is None


class TestProcessWebhookPayload:
    """Tests for _process_webhook_payload method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    @pytest.fixture
    def mock_processor(self):
        """Create mock processor."""
        return MagicMock()

    @pytest.fixture
    def handler(self, mock_settings, mock_processor):
        """Create handler instance."""
        handler = UnifiedWebhookHandler.__new__(UnifiedWebhookHandler)
        handler.config = {}
        handler.processor = mock_processor
        handler.logger = MagicMock()
        return handler

    def test_process_withings_payload(self, handler, mock_processor):
        """Test processing Withings payload."""
        mock_processor.process_withings_webhook.return_value = [{"user_id": "test"}]
        payload = {"userid": 123}

        result = handler._process_webhook_payload(Provider.WITHINGS, payload)

        assert result == [{"user_id": "test"}]
        mock_processor.process_withings_webhook.assert_called_once_with(payload)

    def test_process_fitbit_payload(self, handler, mock_processor):
        """Test processing Fitbit payload."""
        mock_processor.process_fitbit_webhook.return_value = [{"user_id": "test"}]
        payload = [{"collectionType": "activities"}]

        result = handler._process_webhook_payload(Provider.FITBIT, payload)

        assert result == [{"user_id": "test"}]
        mock_processor.process_fitbit_webhook.assert_called_once_with(payload)


class TestQueueSyncTasks:
    """Tests for _queue_sync_tasks method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    @pytest.fixture
    def handler(self, mock_settings):
        """Create handler instance."""
        handler = UnifiedWebhookHandler.__new__(UnifiedWebhookHandler)
        handler.config = {}
        handler.logger = MagicMock()
        return handler

    def test_queue_single_task(self, handler):
        """Test queuing a single sync task."""
        sync_requests = [{"user_id": "test-user", "provider": "withings", "data_types": ["heart_rate"]}]

        with patch("webhooks.unified_webhook_handler.sync_user_health_data_realtime") as mock_task:
            mock_task.return_value = MagicMock(id="task-123")

            result = handler._queue_sync_tasks(Provider.WITHINGS, sync_requests)

            assert len(result) == 1
            assert result[0]["task_id"] == "task-123"
            assert result[0]["user_id"] == "test-user"

    def test_queue_multiple_tasks(self, handler):
        """Test queuing multiple sync tasks."""
        sync_requests = [
            {"user_id": "user-1", "provider": "withings", "data_types": ["heart_rate"]},
            {"user_id": "user-2", "provider": "withings", "data_types": ["weight"]},
        ]

        with patch("webhooks.unified_webhook_handler.sync_user_health_data_realtime") as mock_task:
            mock_task.side_effect = [MagicMock(id="task-1"), MagicMock(id="task-2")]

            result = handler._queue_sync_tasks(Provider.WITHINGS, sync_requests)

            assert len(result) == 2
            assert result[0]["task_id"] == "task-1"
            assert result[1]["task_id"] == "task-2"

    def test_queue_task_error_handling(self, handler):
        """Test error handling when queuing fails."""
        sync_requests = [{"user_id": "test-user", "provider": "withings", "data_types": ["heart_rate"]}]

        with patch("webhooks.unified_webhook_handler.sync_user_health_data_realtime") as mock_task:
            mock_task.side_effect = Exception("Queue error")

            result = handler._queue_sync_tasks(Provider.WITHINGS, sync_requests)

            assert len(result) == 0


class TestGetWebhookStats:
    """Tests for get_webhook_stats method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    @pytest.fixture
    def handler(self, mock_settings):
        """Create handler instance."""
        with patch("webhooks.unified_webhook_handler.WebhookPayloadProcessor"):
            with patch("webhooks.unified_webhook_handler.WebhookSignatureValidator"):
                return UnifiedWebhookHandler()

    def test_get_webhook_stats(self, handler):
        """Test getting webhook stats."""
        stats = handler.get_webhook_stats()

        assert "supported_providers" in stats
        assert "withings" in stats["supported_providers"]
        assert "fitbit" in stats["supported_providers"]
        assert "metrics" in stats


class TestGlobalFunctions:
    """Tests for global functions and endpoints."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    def test_get_unified_webhook_handler_singleton(self, mock_settings):
        """Test that get_unified_webhook_handler returns singleton."""
        import webhooks.unified_webhook_handler as module

        module._unified_handler = None

        with patch.object(module, "WebhookPayloadProcessor"):
            with patch.object(module, "WebhookSignatureValidator"):
                handler1 = get_unified_webhook_handler()
                handler2 = get_unified_webhook_handler()

                assert handler1 is handler2


class TestHandleWebhookHTTPMethods:
    """Tests for handle_webhook with different HTTP methods."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    @pytest.fixture
    def handler(self, mock_settings):
        """Create handler instance."""
        with patch("webhooks.unified_webhook_handler.WebhookPayloadProcessor"):
            with patch("webhooks.unified_webhook_handler.WebhookSignatureValidator") as mock_validator_cls:
                handler = UnifiedWebhookHandler()
                handler.validator = mock_validator_cls.return_value
                return handler

    @pytest.fixture
    def request_factory(self):
        """Create Django request factory."""
        return RequestFactory()

    def test_handle_head_request_health_check(self, handler, request_factory):
        """Test handling HEAD request returns health check response."""
        request = request_factory.head("/webhook/withings/")

        response = handler.handle_webhook(Provider.WITHINGS, request)

        assert response.status_code == 200

    def test_handle_unknown_method_returns_400(self, handler, request_factory):
        """Test handling unknown HTTP method returns 400."""
        request = request_factory.delete("/webhook/withings/")

        response = handler.handle_webhook(Provider.WITHINGS, request)

        assert response.status_code == 400
        assert b"not allowed" in response.content

    def test_handle_put_method_returns_400(self, handler, request_factory):
        """Test handling PUT method returns 400."""
        request = request_factory.put("/webhook/fitbit/", data="{}")

        response = handler.handle_webhook(Provider.FITBIT, request)

        assert response.status_code == 400

    def test_handle_webhook_exception_returns_500(self, handler, request_factory):
        """Test exception during webhook handling returns 500."""
        request = request_factory.get("/webhook/withings/")

        # Force an exception in the verification handler
        with patch.object(handler, "_handle_verification_request", side_effect=RuntimeError("Test error")):
            response = handler.handle_webhook(Provider.WITHINGS, request)

        assert response.status_code == 500
        assert b"Internal Server Error" in response.content


class TestHandleNotificationEdgeCases:
    """Tests for notification handling edge cases."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.unified_webhook_handler.settings") as mock:
            mock.API_CLIENT_CONFIG = {}
            yield mock

    @pytest.fixture
    def handler(self, mock_settings):
        """Create handler instance."""
        with patch("webhooks.unified_webhook_handler.WebhookPayloadProcessor"):
            with patch("webhooks.unified_webhook_handler.WebhookSignatureValidator") as mock_validator_cls:
                handler = UnifiedWebhookHandler()
                handler.validator = mock_validator_cls.return_value
                handler.validator.validate_withings_signature.return_value = True
                handler.validator.validate_fitbit_signature.return_value = True
                return handler

    @pytest.fixture
    def request_factory(self):
        """Create Django request factory."""
        return RequestFactory()

    def test_notification_with_no_tasks_queued(self, handler, request_factory):
        """Test notification that results in no tasks being queued."""
        request = request_factory.post(
            "/webhook/withings/",
            data=json.dumps({"userid": 123, "appli": 4}),
            content_type="application/json",
        )

        # Mock processor to return empty list
        handler.processor.process_withings_webhook.return_value = []

        with patch("webhooks.unified_webhook_handler.sync_user_health_data_realtime"):
            response = handler._handle_notification_request(Provider.WITHINGS, request)

        assert response.status_code == 202

    def test_notification_processor_exception(self, handler, request_factory):
        """Test notification when processor raises exception."""
        request = request_factory.post(
            "/webhook/withings/",
            data=json.dumps({"userid": 123, "appli": 4}),
            content_type="application/json",
        )

        # Mock processor to raise exception
        handler.processor.process_withings_webhook.side_effect = ValueError("Invalid payload")

        response = handler._handle_notification_request(Provider.WITHINGS, request)

        assert response.status_code == 500

    def test_notification_validation_error(self, handler, request_factory):
        """Test notification when processor raises WebhookValidationError."""
        from webhooks.processors import WebhookValidationError

        request = request_factory.post(
            "/webhook/withings/",
            data=json.dumps({"userid": 123, "appli": 4}),
            content_type="application/json",
        )

        handler.processor.process_withings_webhook.side_effect = WebhookValidationError("Missing field")

        response = handler._handle_notification_request(Provider.WITHINGS, request)

        assert response.status_code == 400

    def test_handle_unknown_method_returns_400(self, handler, request_factory):
        """Test handling unknown HTTP method returns 400."""
        request = request_factory.delete("/webhook/withings/")

        response = handler.handle_webhook(Provider.WITHINGS, request)

        assert response.status_code == 400

    def test_handle_webhook_exception_returns_500(self, handler, request_factory):
        """Test exception during webhook handling returns 500."""
        request = request_factory.get("/webhook/withings/")

        with patch.object(handler, "_handle_verification_request", side_effect=RuntimeError("Test error")):
            response = handler.handle_webhook(Provider.WITHINGS, request)

        assert response.status_code == 500
