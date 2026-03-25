"""
Tests for webhook view handlers (Withings and Fitbit webhook endpoints).
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIRequestFactory

from webhooks.views import (
    WebhookMetrics,
    debug_withings_subscriptions,
    fitbit_webhook_handler,
    webhook_health_check,
    webhook_metrics_endpoint,
    withings_webhook_handler,
)


class TestWebhookMetrics:
    """Tests for WebhookMetrics class."""

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
        """Test getting stats dictionary."""
        metrics = WebhookMetrics()
        metrics.increment_webhook("withings")
        metrics.increment_error("fitbit")

        stats = metrics.get_stats()

        assert "webhook_counts" in stats
        assert "error_counts" in stats
        assert stats["webhook_counts"]["withings"] == 1
        assert stats["error_counts"]["fitbit"] == 1


class TestWithingsWebhookHandler:
    """Tests for Withings webhook handler."""

    @pytest.fixture
    def factory(self):
        """Create API request factory."""
        return APIRequestFactory()

    def test_get_verification_with_challenge(self, factory):
        """Test GET request with challenge parameter returns challenge."""
        request = factory.get("/webhooks/withings/?challenge=test-challenge-123")

        response = withings_webhook_handler(request)

        assert response.status_code == 200
        assert response.content.decode() == "test-challenge-123"

    def test_get_verification_without_challenge(self, factory):
        """Test GET request without challenge returns error."""
        request = factory.get("/webhooks/withings/")

        response = withings_webhook_handler(request)

        assert response.status_code == 400

    def test_head_request_returns_200(self, factory):
        """Test HEAD request returns 200 OK."""
        request = factory.head("/webhooks/withings/")

        response = withings_webhook_handler(request)

        assert response.status_code == 200

    def test_post_invalid_signature(self, factory):
        """Test POST with invalid signature returns 403."""
        request = factory.post(
            "/webhooks/withings/", data=json.dumps({"userid": "123", "appli": 1}), content_type="application/json"
        )

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_withings_signature.return_value = False
            mock_validator.return_value = mock_instance

            response = withings_webhook_handler(request)

        assert response.status_code == 403

    def test_post_empty_body(self, factory):
        """Test POST with empty body returns error."""
        request = factory.post("/webhooks/withings/", data="", content_type="application/json")

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_withings_signature.return_value = True
            mock_validator.return_value = mock_instance

            response = withings_webhook_handler(request)

        assert response.status_code == 400

    def test_post_valid_json_payload(self, factory):
        """Test POST with valid JSON payload processes successfully."""
        payload = {"userid": "123456", "appli": 1, "startdate": 1700000000, "enddate": 1700086400}
        request = factory.post("/webhooks/withings/", data=json.dumps(payload), content_type="application/json")

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_withings_signature.return_value = True
            mock_validator.return_value = mock_instance

            with patch("webhooks.views.WebhookPayloadProcessor") as mock_processor:
                mock_proc_instance = MagicMock()
                mock_proc_instance.process_withings_webhook.return_value = [
                    {
                        "user_id": "ehr-123",
                        "provider": "withings",
                        "data_types": ["weight"],
                        "date_range": {"start": "2024-01-01", "end": "2024-01-02"},
                    }
                ]
                mock_processor.return_value = mock_proc_instance

                with patch("webhooks.views.sync_user_health_data_realtime") as mock_sync:
                    mock_task = MagicMock()
                    mock_task.id = "task-123"
                    mock_sync.return_value = mock_task

                    response = withings_webhook_handler(request)

        assert response.status_code == 202
        assert response.data["status"] == "accepted"
        assert response.data["queued_tasks"] == 1

    def test_post_form_encoded_payload(self, factory):
        """Test POST with form-encoded payload processes successfully."""
        # Withings sometimes sends form-encoded data
        request = factory.post(
            "/webhooks/withings/",
            data="userid=123456&appli=1&startdate=1700000000&enddate=1700086400",
            content_type="application/x-www-form-urlencoded",
        )

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_withings_signature.return_value = True
            mock_validator.return_value = mock_instance

            with patch("webhooks.views.WebhookPayloadProcessor") as mock_processor:
                mock_proc_instance = MagicMock()
                mock_proc_instance.process_withings_webhook.return_value = []
                mock_processor.return_value = mock_proc_instance

                response = withings_webhook_handler(request)

        assert response.status_code == 202

    def test_post_validation_error(self, factory):
        """Test POST with invalid payload returns 400."""
        from webhooks.processors import WebhookValidationError

        payload = {"invalid": "data"}
        request = factory.post("/webhooks/withings/", data=json.dumps(payload), content_type="application/json")

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_withings_signature.return_value = True
            mock_validator.return_value = mock_instance

            with patch("webhooks.views.WebhookPayloadProcessor") as mock_processor:
                mock_proc_instance = MagicMock()
                mock_proc_instance.process_withings_webhook.side_effect = WebhookValidationError(
                    "Missing required field"
                )
                mock_processor.return_value = mock_proc_instance

                response = withings_webhook_handler(request)

        assert response.status_code == 400

    def test_post_task_queueing_error(self, factory):
        """Test POST continues when task queueing fails."""
        payload = {"userid": "123456", "appli": 1}
        request = factory.post("/webhooks/withings/", data=json.dumps(payload), content_type="application/json")

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_withings_signature.return_value = True
            mock_validator.return_value = mock_instance

            with patch("webhooks.views.WebhookPayloadProcessor") as mock_processor:
                mock_proc_instance = MagicMock()
                mock_proc_instance.process_withings_webhook.return_value = [
                    {"user_id": "ehr-123", "provider": "withings", "data_types": ["weight"]}
                ]
                mock_processor.return_value = mock_proc_instance

                with patch("webhooks.views.sync_user_health_data_realtime") as mock_sync:
                    mock_sync.side_effect = Exception("Task queue error")

                    response = withings_webhook_handler(request)

        # Should still return 202 even if task queueing fails
        assert response.status_code == 202
        assert response.data["queued_tasks"] == 0


class TestFitbitWebhookHandler:
    """Tests for Fitbit webhook handler."""

    @pytest.fixture
    def factory(self):
        """Create API request factory."""
        return APIRequestFactory()

    def test_get_verification_with_matching_code(self, factory):
        """Test GET request with matching verification code returns 204."""
        request = factory.get("/webhooks/fitbit/?verify=test-verify-code")

        with patch("webhooks.views.settings") as mock_settings:
            mock_settings.FITBIT_VERIFICATION_CODE = "test-verify-code"

            response = fitbit_webhook_handler(request)

        assert response.status_code == 204

    def test_get_verification_with_mismatched_code(self, factory):
        """Test GET request with mismatched verification code returns 404."""
        request = factory.get("/webhooks/fitbit/?verify=wrong-code")

        with patch("webhooks.views.settings") as mock_settings:
            mock_settings.FITBIT_VERIFICATION_CODE = "correct-code"

            response = fitbit_webhook_handler(request)

        assert response.status_code == 404

    def test_get_verification_no_configured_code(self, factory):
        """Test GET verification in dev mode accepts any code."""
        request = factory.get("/webhooks/fitbit/?verify=any-code")

        with patch("webhooks.views.settings") as mock_settings:
            mock_settings.FITBIT_VERIFICATION_CODE = ""

            response = fitbit_webhook_handler(request)

        assert response.status_code == 204

    def test_get_without_verify_param(self, factory):
        """Test GET without verify parameter returns error."""
        request = factory.get("/webhooks/fitbit/")

        response = fitbit_webhook_handler(request)

        assert response.status_code == 400

    def test_head_request_returns_200(self, factory):
        """Test HEAD request returns 200 OK."""
        request = factory.head("/webhooks/fitbit/")

        response = fitbit_webhook_handler(request)

        assert response.status_code == 200

    def test_post_invalid_signature(self, factory):
        """Test POST with invalid signature returns 403."""
        request = factory.post(
            "/webhooks/fitbit/",
            data=json.dumps([{"ownerId": "123", "collectionType": "activities"}]),
            content_type="application/json",
        )

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_fitbit_signature.return_value = False
            mock_validator.return_value = mock_instance

            response = fitbit_webhook_handler(request)

        assert response.status_code == 403

    def test_post_empty_body(self, factory):
        """Test POST with empty body returns error."""
        request = factory.post("/webhooks/fitbit/", data="", content_type="application/json")

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_fitbit_signature.return_value = True
            mock_validator.return_value = mock_instance

            response = fitbit_webhook_handler(request)

        assert response.status_code == 400

    def test_post_invalid_json(self, factory):
        """Test POST with invalid JSON returns error."""
        request = factory.post("/webhooks/fitbit/", data="not-json", content_type="application/json")

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_fitbit_signature.return_value = True
            mock_validator.return_value = mock_instance

            response = fitbit_webhook_handler(request)

        assert response.status_code == 400

    def test_post_valid_payload(self, factory):
        """Test POST with valid payload processes successfully."""
        payload = [{"ownerId": "ABC123", "collectionType": "activities", "date": "2024-01-15"}]
        request = factory.post("/webhooks/fitbit/", data=json.dumps(payload), content_type="application/json")

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_fitbit_signature.return_value = True
            mock_validator.return_value = mock_instance

            with patch("webhooks.views.WebhookPayloadProcessor") as mock_processor:
                mock_proc_instance = MagicMock()
                mock_proc_instance.process_fitbit_webhook.return_value = [
                    {
                        "user_id": "ehr-123",
                        "provider": "fitbit",
                        "data_types": ["steps"],
                        "date_range": {"start": "2024-01-15", "end": "2024-01-15"},
                    }
                ]
                mock_processor.return_value = mock_proc_instance

                with patch("webhooks.views.sync_user_health_data_realtime") as mock_sync:
                    mock_task = MagicMock()
                    mock_task.id = "task-456"
                    mock_sync.return_value = mock_task

                    response = fitbit_webhook_handler(request)

        assert response.status_code == 202
        assert response.data["status"] == "accepted"
        assert response.data["queued_tasks"] == 1

    def test_post_validation_error(self, factory):
        """Test POST with invalid payload returns 400."""
        from webhooks.processors import WebhookValidationError

        payload = [{"invalid": "data"}]
        request = factory.post("/webhooks/fitbit/", data=json.dumps(payload), content_type="application/json")

        with patch("webhooks.views.WebhookSignatureValidator") as mock_validator:
            mock_instance = MagicMock()
            mock_instance.validate_fitbit_signature.return_value = True
            mock_validator.return_value = mock_instance

            with patch("webhooks.views.WebhookPayloadProcessor") as mock_processor:
                mock_proc_instance = MagicMock()
                mock_proc_instance.process_fitbit_webhook.side_effect = WebhookValidationError(
                    "Invalid Fitbit notification"
                )
                mock_processor.return_value = mock_proc_instance

                response = fitbit_webhook_handler(request)

        assert response.status_code == 400


class TestWebhookHealthCheck:
    """Tests for webhook health check endpoint."""

    @pytest.fixture
    def factory(self):
        """Create API request factory."""
        return APIRequestFactory()

    def test_health_check_healthy(self, factory):
        """Test health check returns healthy when services are up."""
        request = factory.get("/webhooks/health/")

        # cache is imported from django.core.cache inside the function
        with patch("django.core.cache.cache") as mock_cache:
            mock_cache.set.return_value = None
            mock_cache.get.return_value = "timestamp"

            with patch("django.conf.settings") as mock_settings:
                mock_settings.WEBHOOK_CONFIG = {"CACHE_TIMEOUT": 300}

                response = webhook_health_check(request)

        assert response.status_code == 200
        assert response.data["status"] == "healthy"
        assert "services" in response.data
        assert response.data["services"]["redis_cache"] == "online"

    def test_health_check_redis_offline(self, factory):
        """Test health check indicates Redis offline when cache fails."""
        request = factory.get("/webhooks/health/")

        # cache is imported from django.core.cache inside the function
        with patch("django.core.cache.cache") as mock_cache:
            mock_cache.set.return_value = None
            mock_cache.get.return_value = None  # Redis didn't store value

            with patch("django.conf.settings") as mock_settings:
                mock_settings.WEBHOOK_CONFIG = {"CACHE_TIMEOUT": 300}

                response = webhook_health_check(request)

        assert response.status_code == 200
        assert response.data["services"]["redis_cache"] == "offline"

    def test_health_check_error(self, factory):
        """Test health check returns 503 on exception."""
        request = factory.get("/webhooks/health/")

        # cache is imported from django.core.cache inside the function
        with patch("django.core.cache.cache") as mock_cache:
            mock_cache.set.side_effect = Exception("Redis connection error")

            response = webhook_health_check(request)

        assert response.status_code == 503
        assert response.data["status"] == "unhealthy"


class TestWebhookMetricsEndpoint:
    """Tests for webhook metrics endpoint."""

    @pytest.fixture
    def factory(self):
        """Create API request factory."""
        return APIRequestFactory()

    def test_metrics_endpoint_returns_data(self, factory):
        """Test metrics endpoint returns metrics data."""
        request = factory.get("/webhooks/metrics/")

        response = webhook_metrics_endpoint(request)

        assert response.status_code == 200
        assert "timestamp" in response.data
        assert "webhook_metrics" in response.data
        assert "endpoints" in response.data

    def test_metrics_endpoint_includes_endpoint_list(self, factory):
        """Test metrics endpoint includes list of endpoints."""
        request = factory.get("/webhooks/metrics/")

        response = webhook_metrics_endpoint(request)

        endpoints = response.data["endpoints"]
        assert "/webhooks/withings/" in endpoints.values()
        assert "/webhooks/fitbit/" in endpoints.values()


class TestDebugWithingsSubscriptions:
    """Tests for debug Withings subscriptions endpoint."""

    @pytest.fixture
    def factory(self):
        """Create API request factory."""
        return APIRequestFactory()

    def test_missing_user_id(self, factory):
        """Test endpoint returns error when user_id missing."""
        request = factory.get("/webhooks/debug/withings/subscriptions/")

        response = debug_withings_subscriptions(request)

        assert response.status_code == 400
        assert "user_id" in response.data["error"]

    def test_user_not_found(self, factory):
        """Test endpoint returns 404 for non-existent user."""
        request = factory.get("/webhooks/debug/withings/subscriptions/?user_id=nonexistent")

        # EHRUser is imported inside the function from base.models
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.side_effect = mock_ehr_user.DoesNotExist

            response = debug_withings_subscriptions(request)

        assert response.status_code == 404

    def test_user_not_connected_to_withings(self, factory):
        """Test endpoint returns 404 when user not connected to Withings."""
        request = factory.get("/webhooks/debug/withings/subscriptions/?user_id=test-user")

        mock_user = MagicMock()

        # EHRUser is imported inside the function from base.models
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            # UserSocialAuth is imported from social_django.models
            with patch("social_django.models.UserSocialAuth") as mock_social:
                mock_social.DoesNotExist = Exception
                mock_social.objects.filter.return_value.order_by.return_value.first.return_value = None

                response = debug_withings_subscriptions(request)

        assert response.status_code == 404
        assert response.data["withings_connected"] is False

    def test_returns_subscription_list(self, factory):
        """Test endpoint returns subscription list from Withings API."""
        request = factory.get("/webhooks/debug/withings/subscriptions/?user_id=test-user")

        mock_user = MagicMock()
        mock_social_auth = MagicMock()
        mock_social_auth.access_token = "test-token"
        mock_social_auth.extra_data = {"userid": "123456"}

        # EHRUser is imported inside the function from base.models
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            # UserSocialAuth is imported from social_django.models
            with patch("social_django.models.UserSocialAuth") as mock_social:
                mock_social.DoesNotExist = Exception
                mock_social.objects.filter.return_value.order_by.return_value.first.return_value = mock_social_auth

                # requests is imported inside the function
                with patch("requests.get") as mock_get:
                    mock_response = MagicMock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {
                        "status": 0,
                        "body": {
                            "profiles": [
                                {"appli": 1, "callbackurl": "https://example.com"},
                                {"appli": 4, "callbackurl": "https://example.com"},
                            ]
                        },
                    }
                    mock_response.raise_for_status = MagicMock()
                    mock_get.return_value = mock_response

                    response = debug_withings_subscriptions(request)

        assert response.status_code == 200
        assert response.data["subscription_count"] == 2
        assert response.data["withings_user_id"] == "123456"
        # Check that appli names are enriched
        assert response.data["subscriptions"][0]["appli_name"] is not None

    def test_withings_api_error(self, factory):
        """Test endpoint handles Withings API error."""
        request = factory.get("/webhooks/debug/withings/subscriptions/?user_id=test-user")

        mock_user = MagicMock()
        mock_social_auth = MagicMock()
        mock_social_auth.access_token = "test-token"
        mock_social_auth.extra_data = {}

        # EHRUser is imported inside the function from base.models
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            # UserSocialAuth is imported from social_django.models
            with patch("social_django.models.UserSocialAuth") as mock_social:
                mock_social.DoesNotExist = Exception
                mock_social.objects.filter.return_value.order_by.return_value.first.return_value = mock_social_auth

                # requests is imported inside the function
                with patch("requests.get") as mock_get:
                    mock_response = MagicMock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {"status": 401, "error": "unauthorized"}
                    mock_response.raise_for_status = MagicMock()
                    mock_get.return_value = mock_response

                    response = debug_withings_subscriptions(request)

        assert response.status_code == 500
        assert "Withings API returned error" in response.data["error"]

    def test_network_error(self, factory):
        """Test endpoint handles network error."""
        import requests as real_requests

        request = factory.get("/webhooks/debug/withings/subscriptions/?user_id=test-user")

        mock_user = MagicMock()
        mock_social_auth = MagicMock()
        mock_social_auth.access_token = "test-token"

        # EHRUser is imported inside the function from base.models
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            # UserSocialAuth is imported from social_django.models
            with patch("social_django.models.UserSocialAuth") as mock_social:
                mock_social.DoesNotExist = Exception
                mock_social.objects.filter.return_value.order_by.return_value.first.return_value = mock_social_auth

                # requests is imported inside the function
                with patch("requests.get") as mock_get:
                    mock_get.side_effect = real_requests.RequestException("Connection timeout")

                    response = debug_withings_subscriptions(request)

        assert response.status_code == 500
        assert "Failed to query Withings API" in response.data["error"]
