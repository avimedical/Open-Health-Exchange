"""
Tests for webhook subscription management.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import responses

from ingestors.health_data_constants import Provider
from webhooks.subscriptions import (
    WebhookSubscription,
    WebhookSubscriptionError,
    WebhookSubscriptionManager,
)


class TestWebhookSubscription:
    """Tests for WebhookSubscription dataclass."""

    def test_create_subscription_minimal(self):
        """Test creating subscription with minimal fields."""
        subscription = WebhookSubscription(
            provider=Provider.WITHINGS,
            user_id="test-user",
        )

        assert subscription.provider == Provider.WITHINGS
        assert subscription.user_id == "test-user"
        assert subscription.subscription_id is None
        assert subscription.callback_url is None
        assert subscription.data_types is None
        assert subscription.is_active is True
        assert subscription.created_at is None
        assert subscription.updated_at is None

    def test_create_subscription_full(self):
        """Test creating subscription with all fields."""
        now = datetime.now(tz=UTC)
        subscription = WebhookSubscription(
            provider=Provider.FITBIT,
            user_id="test-user",
            subscription_id="sub-123",
            callback_url="https://example.com/webhook",
            data_types=["activities", "sleep"],
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        assert subscription.provider == Provider.FITBIT
        assert subscription.subscription_id == "sub-123"
        assert subscription.callback_url == "https://example.com/webhook"
        assert subscription.data_types == ["activities", "sleep"]
        assert subscription.created_at == now


class TestWebhookSubscriptionError:
    """Tests for WebhookSubscriptionError exception."""

    def test_error_message(self):
        """Test exception message."""
        error = WebhookSubscriptionError("Subscription failed")
        assert str(error) == "Subscription failed"
        assert isinstance(error, Exception)


class TestWebhookSubscriptionManager:
    """Tests for WebhookSubscriptionManager class."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.subscriptions.settings") as mock:
            mock.WEBHOOK_BASE_URL = "https://example.com/webhooks/"
            mock.WEBHOOK_CONFIG = {"TIMEOUT": 30}
            mock.FITBIT_SUBSCRIBER_ID = "123"
            yield mock

    @pytest.fixture
    def manager(self, mock_settings):
        """Create manager instance."""
        return WebhookSubscriptionManager()

    @pytest.fixture
    def mock_social_auth(self):
        """Create mock social auth."""
        mock_auth = MagicMock()
        mock_auth.access_token = "test_access_token"
        mock_auth.extra_data = {
            "access_token": "test_access_token",
            "user_id": "fitbit-user-123",
        }
        return mock_auth


class TestWithingsSubscriptions:
    """Tests for Withings subscription management."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.subscriptions.settings") as mock:
            mock.WEBHOOK_BASE_URL = "https://example.com/webhooks/"
            mock.WEBHOOK_CONFIG = {"TIMEOUT": 30}
            yield mock

    @pytest.fixture
    def manager(self, mock_settings):
        """Create manager instance."""
        return WebhookSubscriptionManager()

    @pytest.fixture
    def mock_social_auth(self):
        """Create mock social auth."""
        mock_auth = MagicMock()
        mock_auth.access_token = "test_access_token"
        return mock_auth

    @responses.activate
    def test_create_withings_subscription_success(self, manager, mock_social_auth):
        """Test successful Withings subscription creation."""
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/notify",
            json={"status": 0},
            status=200,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            with patch("ingestors.provider_mappings.validate_data_types") as mock_validate:
                mock_validate.return_value = (["heart_rate"], [])
                with patch("ingestors.provider_mappings.resolve_subscription_categories") as mock_resolve:
                    mock_resolve.return_value = ["4"]

                    subscription = manager.create_withings_subscription(
                        user_id="test-user",
                        data_types=["heart_rate"],
                    )

        assert subscription.provider == Provider.WITHINGS
        assert subscription.user_id == "test-user"
        assert subscription.callback_url == "https://example.com/webhooks/withings/"

    @responses.activate
    def test_create_withings_subscription_failure(self, manager, mock_social_auth):
        """Test Withings subscription creation failure."""
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/notify",
            json={"status": 401, "error": "Unauthorized"},
            status=200,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            with patch("ingestors.provider_mappings.validate_data_types") as mock_validate:
                mock_validate.return_value = (["heart_rate"], [])
                with patch("ingestors.provider_mappings.resolve_subscription_categories") as mock_resolve:
                    mock_resolve.return_value = ["4"]

                    with pytest.raises(WebhookSubscriptionError):
                        manager.create_withings_subscription(
                            user_id="test-user",
                            data_types=["heart_rate"],
                        )

    def test_create_withings_subscription_no_supported_types(self, manager, mock_social_auth):
        """Test Withings subscription with no supported data types."""
        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            with patch("ingestors.provider_mappings.validate_data_types") as mock_validate:
                mock_validate.return_value = ([], ["unsupported_type"])

                with pytest.raises(WebhookSubscriptionError, match="No supported data types"):
                    manager.create_withings_subscription(
                        user_id="test-user",
                        data_types=["unsupported_type"],
                    )

    @responses.activate
    def test_create_withings_subscription_multiple_appli_types(self, manager, mock_social_auth):
        """Test creating subscriptions for multiple appli types."""
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/notify",
            json={"status": 0},
            status=200,
        )
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/notify",
            json={"status": 0},
            status=200,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            with patch("ingestors.provider_mappings.validate_data_types") as mock_validate:
                mock_validate.return_value = (["heart_rate", "weight"], [])
                with patch("ingestors.provider_mappings.resolve_subscription_categories") as mock_resolve:
                    mock_resolve.return_value = ["4", "1"]

                    subscription = manager.create_withings_subscription(
                        user_id="test-user",
                        data_types=["heart_rate", "weight"],
                    )

        assert subscription is not None
        assert len(responses.calls) == 2

    @responses.activate
    def test_delete_withings_subscription_success(self, manager, mock_social_auth):
        """Test successful Withings subscription deletion."""
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/notify",
            json={"status": 0},
            status=200,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            result = manager.delete_withings_subscription(user_id="test-user", appli=4)

        assert result is True

    @responses.activate
    def test_delete_withings_subscription_failure(self, manager, mock_social_auth):
        """Test Withings subscription deletion failure."""
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/notify",
            json={"status": 401, "error": "Unauthorized"},
            status=200,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            result = manager.delete_withings_subscription(user_id="test-user", appli=4)

        assert result is False

    def test_delete_withings_subscription_exception(self, manager, mock_social_auth):
        """Test Withings subscription deletion with exception."""
        with patch.object(manager, "_get_user_social_auth", side_effect=Exception("Connection error")):
            result = manager.delete_withings_subscription(user_id="test-user", appli=4)

        assert result is False


class TestFitbitSubscriptions:
    """Tests for Fitbit subscription management."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.subscriptions.settings") as mock:
            mock.WEBHOOK_BASE_URL = "https://example.com/webhooks/"
            mock.WEBHOOK_CONFIG = {"TIMEOUT": 30}
            mock.FITBIT_SUBSCRIBER_ID = "subscriber-123"
            yield mock

    @pytest.fixture
    def manager(self, mock_settings):
        """Create manager instance."""
        return WebhookSubscriptionManager()

    @pytest.fixture
    def mock_social_auth(self):
        """Create mock social auth."""
        mock_auth = MagicMock()
        mock_auth.access_token = "test_access_token"
        mock_auth.extra_data = {
            "access_token": "test_access_token",
            "user_id": "fitbit-user-123",
        }
        return mock_auth

    @responses.activate
    def test_create_fitbit_subscription_success(self, manager, mock_social_auth):
        """Test successful Fitbit subscription creation."""
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/activities/apiSubscriptions/test-user.json",
            json={},
            status=201,
        )
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/sleep/apiSubscriptions/test-user.json",
            json={},
            status=201,
        )
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/body/apiSubscriptions/test-user.json",
            json={},
            status=201,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            subscription = manager.create_fitbit_subscription(user_id="test-user")

        assert subscription.provider == Provider.FITBIT
        assert subscription.user_id == "test-user"

    @responses.activate
    def test_create_fitbit_subscription_already_exists(self, manager, mock_social_auth):
        """Test Fitbit subscription when already exists (409)."""
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/activities/apiSubscriptions/test-user.json",
            json={},
            status=409,  # Conflict - already exists
        )
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/sleep/apiSubscriptions/test-user.json",
            json={},
            status=409,
        )
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/body/apiSubscriptions/test-user.json",
            json={},
            status=409,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            subscription = manager.create_fitbit_subscription(user_id="test-user")

        assert subscription is not None

    @responses.activate
    def test_create_fitbit_subscription_failure(self, manager, mock_social_auth):
        """Test Fitbit subscription creation failure."""
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/activities/apiSubscriptions/test-user.json",
            json={"error": "Bad request"},
            status=400,
        )
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/sleep/apiSubscriptions/test-user.json",
            json={"error": "Bad request"},
            status=400,
        )
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/body/apiSubscriptions/test-user.json",
            json={"error": "Bad request"},
            status=400,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            with pytest.raises(WebhookSubscriptionError, match="Failed to create any Fitbit"):
                manager.create_fitbit_subscription(user_id="test-user")

    @responses.activate
    def test_create_fitbit_subscription_custom_collections(self, manager, mock_social_auth):
        """Test Fitbit subscription with custom collection types."""
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/activities/apiSubscriptions/test-user.json",
            json={},
            status=201,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            subscription = manager.create_fitbit_subscription(
                user_id="test-user",
                collection_types=["activities"],
            )

        assert subscription is not None
        assert len(responses.calls) == 1

    @responses.activate
    def test_create_fitbit_subscription_with_custom_id(self, manager, mock_social_auth):
        """Test Fitbit subscription with custom subscription ID."""
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/activities/apiSubscriptions/custom-sub-123.json",
            json={},
            status=201,
        )
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/sleep/apiSubscriptions/custom-sub-123.json",
            json={},
            status=201,
        )
        responses.add(
            responses.POST,
            "https://api.fitbit.com/1/user/fitbit-user-123/body/apiSubscriptions/custom-sub-123.json",
            json={},
            status=201,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            subscription = manager.create_fitbit_subscription(
                user_id="test-user",
                subscription_id="custom-sub-123",
            )

        assert subscription.subscription_id == "custom-sub-123"

    @responses.activate
    def test_delete_fitbit_subscription_success(self, manager, mock_social_auth):
        """Test successful Fitbit subscription deletion."""
        responses.add(
            responses.DELETE,
            "https://api.fitbit.com/1/user/fitbit-user-123/activities/apiSubscriptions/sub-123.json",
            status=204,  # No Content
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            result = manager.delete_fitbit_subscription(
                user_id="test-user",
                subscription_id="sub-123",
                collection_type="activities",
            )

        assert result is True

    @responses.activate
    def test_delete_fitbit_subscription_failure(self, manager, mock_social_auth):
        """Test Fitbit subscription deletion failure."""
        responses.add(
            responses.DELETE,
            "https://api.fitbit.com/1/user/fitbit-user-123/activities/apiSubscriptions/sub-123.json",
            json={"error": "Not found"},
            status=404,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            result = manager.delete_fitbit_subscription(
                user_id="test-user",
                subscription_id="sub-123",
                collection_type="activities",
            )

        assert result is False

    def test_delete_fitbit_subscription_exception(self, manager, mock_social_auth):
        """Test Fitbit subscription deletion with exception."""
        with patch.object(manager, "_get_user_social_auth", side_effect=Exception("Connection error")):
            result = manager.delete_fitbit_subscription(
                user_id="test-user",
                subscription_id="sub-123",
            )

        assert result is False


class TestListSubscriptions:
    """Tests for listing subscriptions."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.subscriptions.settings") as mock:
            mock.WEBHOOK_BASE_URL = "https://example.com/webhooks/"
            mock.WEBHOOK_CONFIG = {"TIMEOUT": 30}
            yield mock

    @pytest.fixture
    def manager(self, mock_settings):
        """Create manager instance."""
        return WebhookSubscriptionManager()

    @pytest.fixture
    def mock_social_auth(self):
        """Create mock social auth."""
        mock_auth = MagicMock()
        mock_auth.access_token = "test_access_token"
        mock_auth.extra_data = {
            "user_id": "fitbit-user-123",
        }
        return mock_auth

    @responses.activate
    def test_list_user_subscriptions_with_withings_and_fitbit(self, manager, mock_social_auth):
        """Test listing user subscriptions from both Withings and Fitbit."""
        # Mock Withings Notify List API
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/notify",
            json={
                "status": 0,
                "body": {
                    "profiles": [
                        {"callbackurl": "https://example.com/webhooks/withings/", "appli": 4},
                        {"callbackurl": "https://example.com/webhooks/withings/", "appli": 1},
                    ]
                },
            },
            status=200,
        )
        # Mock Fitbit subscriptions API
        responses.add(
            responses.GET,
            "https://api.fitbit.com/1/user/fitbit-user-123/apiSubscriptions.json",
            json={
                "apiSubscriptions": [
                    {"subscriptionId": "sub-1", "collectionType": "activities"},
                    {"subscriptionId": "sub-2", "collectionType": "sleep"},
                ]
            },
            status=200,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            subscriptions = manager.list_user_subscriptions(user_id="test-user")

        # 2 Withings + 2 Fitbit = 4 total
        assert len(subscriptions) == 4
        withings_subs = [s for s in subscriptions if s.provider == Provider.WITHINGS]
        fitbit_subs = [s for s in subscriptions if s.provider == Provider.FITBIT]
        assert len(withings_subs) == 2
        assert len(fitbit_subs) == 2

    @responses.activate
    def test_list_user_subscriptions_fitbit_only(self, manager, mock_social_auth):
        """Test listing subscriptions when user only has Fitbit."""
        # Withings lookup fails (user not connected)
        withings_error = WebhookSubscriptionError("not connected to withings")

        # Mock Fitbit subscriptions API
        responses.add(
            responses.GET,
            "https://api.fitbit.com/1/user/fitbit-user-123/apiSubscriptions.json",
            json={
                "apiSubscriptions": [
                    {"subscriptionId": "sub-1", "collectionType": "activities"},
                ]
            },
            status=200,
        )

        def side_effect(user_id, provider):
            if provider == Provider.WITHINGS:
                raise withings_error
            return mock_social_auth

        with patch.object(manager, "_get_user_social_auth", side_effect=side_effect):
            subscriptions = manager.list_user_subscriptions(user_id="test-user")

        assert len(subscriptions) == 1
        assert subscriptions[0].provider == Provider.FITBIT

    @responses.activate
    def test_list_user_subscriptions_empty(self, manager, mock_social_auth):
        """Test listing subscriptions when none exist."""
        # Empty Withings
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/notify",
            json={"status": 0, "body": {"profiles": []}},
            status=200,
        )
        # Empty Fitbit
        responses.add(
            responses.GET,
            "https://api.fitbit.com/1/user/fitbit-user-123/apiSubscriptions.json",
            json={"apiSubscriptions": []},
            status=200,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            subscriptions = manager.list_user_subscriptions(user_id="test-user")

        assert len(subscriptions) == 0

    @responses.activate
    def test_list_user_subscriptions_api_failure(self, manager, mock_social_auth):
        """Test listing subscriptions when APIs fail."""
        # Withings fails
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/notify",
            json={"status": 401, "error": "Unauthorized"},
            status=200,
        )
        # Fitbit fails
        responses.add(
            responses.GET,
            "https://api.fitbit.com/1/user/fitbit-user-123/apiSubscriptions.json",
            json={"error": "Unauthorized"},
            status=401,
        )

        with patch.object(manager, "_get_user_social_auth", return_value=mock_social_auth):
            subscriptions = manager.list_user_subscriptions(user_id="test-user")

        # Should return empty list on failure
        assert len(subscriptions) == 0


class TestGetUserSocialAuth:
    """Tests for _get_user_social_auth helper."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("webhooks.subscriptions.settings") as mock:
            mock.WEBHOOK_BASE_URL = "https://example.com/webhooks/"
            mock.WEBHOOK_CONFIG = {"TIMEOUT": 30}
            yield mock

    @pytest.fixture
    def manager(self, mock_settings):
        """Create manager instance."""
        return WebhookSubscriptionManager()

    def test_get_user_social_auth_success(self, manager):
        """Test getting social auth successfully - verifies method signature."""
        # Since the method makes direct database calls, we test it raises
        # the appropriate error when the user doesn't exist
        with pytest.raises(WebhookSubscriptionError, match="not connected"):
            manager._get_user_social_auth("nonexistent-user-xyz", Provider.WITHINGS)

    def test_get_user_social_auth_user_not_found(self, manager):
        """Test getting social auth when user not found."""
        with patch("django.contrib.auth.get_user_model") as mock_get_user:
            mock_user_model = MagicMock()
            mock_user_model.DoesNotExist = Exception
            mock_user_model.objects.get.side_effect = Exception("User not found")
            mock_get_user.return_value = mock_user_model

            with pytest.raises(WebhookSubscriptionError, match="not connected"):
                manager._get_user_social_auth("nonexistent-user", Provider.WITHINGS)
