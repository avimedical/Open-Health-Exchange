"""
Tests for webhook payload processors.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from ingestors.health_data_constants import HealthDataType, Provider
from webhooks.processors import WebhookPayloadProcessor, WebhookValidationError


class TestWithingsWebhookProcessor:
    """Tests for Withings webhook payload processing."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        return WebhookPayloadProcessor()

    @pytest.fixture
    def mock_ehr_user_lookup(self):
        """Mock the _lookup_ehr_user_id function."""
        with patch("webhooks.processors._lookup_ehr_user_id") as mock:
            mock.return_value = "ehr-user-123"
            yield mock

    @pytest.fixture
    def mock_provider_mappings(self):
        """Mock the provider mappings."""
        with patch("ingestors.provider_mappings.get_category_to_data_types_mapping") as mock:
            mock.return_value = {
                "1": ["weight"],
                "4": ["steps", "heart_rate"],
                "16": ["sleep"],
                "44": ["heart_rate", "rr_intervals"],
                "46": ["blood_pressure"],
                "54": ["ecg"],
            }
            yield mock

    def test_process_weight_webhook(self, processor, mock_ehr_user_lookup, mock_provider_mappings):
        """Test processing Withings weight (appli=1) webhook."""
        payload = {
            "userid": 12345,
            "appli": 1,
            "startdate": 1704067200,  # 2024-01-01 00:00:00 UTC
            "enddate": 1704153600,  # 2024-01-02 00:00:00 UTC
        }

        result = processor.process_withings_webhook(payload)

        assert len(result) == 1
        assert result[0]["user_id"] == "ehr-user-123"
        assert result[0]["provider"] == "withings"
        assert "weight" in result[0]["data_types"]
        assert result[0]["trigger"] == "webhook"
        assert result[0]["appli_type"] == 1
        mock_ehr_user_lookup.assert_called_once_with("12345", Provider.WITHINGS)

    def test_process_activity_webhook(self, processor, mock_ehr_user_lookup, mock_provider_mappings):
        """Test processing Withings activity (appli=4) webhook."""
        payload = {
            "userid": 12345,
            "appli": 4,
            "startdate": 1704067200,
            "enddate": 1704153600,
        }

        result = processor.process_withings_webhook(payload)

        assert len(result) == 1
        assert "steps" in result[0]["data_types"]
        assert "heart_rate" in result[0]["data_types"]

    def test_process_heart_rate_webhook(self, processor, mock_ehr_user_lookup, mock_provider_mappings):
        """Test processing Withings heart rate (appli=44) webhook."""
        payload = {
            "userid": 12345,
            "appli": 44,
        }

        result = processor.process_withings_webhook(payload)

        assert len(result) == 1
        assert "heart_rate" in result[0]["data_types"]
        assert "rr_intervals" in result[0]["data_types"]

    def test_process_blood_pressure_webhook(self, processor, mock_ehr_user_lookup, mock_provider_mappings):
        """Test processing Withings blood pressure (appli=46) webhook."""
        payload = {
            "userid": 12345,
            "appli": 46,
        }

        result = processor.process_withings_webhook(payload)

        assert len(result) == 1
        assert "blood_pressure" in result[0]["data_types"]

    def test_process_ecg_webhook(self, processor, mock_ehr_user_lookup, mock_provider_mappings):
        """Test processing Withings ECG (appli=54) webhook."""
        payload = {
            "userid": 12345,
            "appli": 54,
        }

        result = processor.process_withings_webhook(payload)

        assert len(result) == 1
        assert "ecg" in result[0]["data_types"]

    def test_missing_userid_field(self, processor):
        """Test validation fails when userid is missing."""
        payload = {"appli": 1}

        with pytest.raises(WebhookValidationError) as exc_info:
            processor.process_withings_webhook(payload)

        assert "Missing required field: userid" in str(exc_info.value)

    def test_missing_appli_field(self, processor):
        """Test validation fails when appli is missing."""
        payload = {"userid": 12345}

        with pytest.raises(WebhookValidationError) as exc_info:
            processor.process_withings_webhook(payload)

        assert "Missing required field: appli" in str(exc_info.value)

    def test_unknown_user_returns_empty(self, processor, mock_provider_mappings):
        """Test processing returns empty when user not found."""
        with patch("webhooks.processors._lookup_ehr_user_id") as mock:
            mock.return_value = None
            payload = {"userid": 99999, "appli": 1}

            result = processor.process_withings_webhook(payload)

            assert result == []

    def test_unsupported_appli_type(self, processor, mock_ehr_user_lookup, mock_provider_mappings):
        """Test processing returns empty for unsupported appli type."""
        mock_provider_mappings.return_value = {"1": ["weight"]}  # 999 not supported
        payload = {"userid": 12345, "appli": 999}

        result = processor.process_withings_webhook(payload)

        assert result == []

    def test_date_range_extraction(self, processor, mock_ehr_user_lookup, mock_provider_mappings):
        """Test date range is correctly extracted from payload."""
        payload = {
            "userid": 12345,
            "appli": 1,
            "startdate": 1704067200,  # 2024-01-01 00:00:00 UTC
            "enddate": 1704153600,  # 2024-01-02 00:00:00 UTC
        }

        result = processor.process_withings_webhook(payload)

        assert result[0]["date_range"]["start"] == "2024-01-01T00:00:00+00:00"
        assert result[0]["date_range"]["end"] == "2024-01-02T00:00:00+00:00"

    def test_default_date_range_when_not_provided(self, processor, mock_ehr_user_lookup, mock_provider_mappings):
        """Test default date range when not in payload."""
        payload = {"userid": 12345, "appli": 1}

        with patch("webhooks.processors.timezone") as mock_tz:
            mock_now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
            mock_tz.now.return_value = mock_now

            result = processor.process_withings_webhook(payload)

            assert result[0]["date_range"] is not None
            assert "start" in result[0]["date_range"]
            assert "end" in result[0]["date_range"]

    def test_optional_fields_included(self, processor, mock_ehr_user_lookup, mock_provider_mappings):
        """Test optional fields are included in result."""
        payload = {
            "userid": 12345,
            "appli": 1,
            "callbackurl": "https://example.com/callback",
            "comment": "test_comment",
        }

        result = processor.process_withings_webhook(payload)

        assert result[0]["callback_url"] == "https://example.com/callback"
        assert result[0]["comment"] == "test_comment"
        assert result[0]["external_user_id"] == "12345"


class TestFitbitWebhookProcessor:
    """Tests for Fitbit webhook payload processing."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        return WebhookPayloadProcessor()

    @pytest.fixture
    def mock_ehr_user_lookup(self):
        """Mock the _lookup_ehr_user_id function."""
        with patch("webhooks.processors._lookup_ehr_user_id") as mock:
            mock.return_value = "ehr-user-456"
            yield mock

    def test_process_activities_webhook(self, processor, mock_ehr_user_lookup):
        """Test processing Fitbit activities webhook."""
        payload = [
            {
                "collectionType": "activities",
                "date": "2024-01-15",
                "ownerId": "ABC123",
                "ownerType": "user",
                "subscriptionId": "1",
            }
        ]

        result = processor.process_fitbit_webhook(payload)

        assert len(result) == 1
        assert result[0]["user_id"] == "ehr-user-456"
        assert result[0]["provider"] == "fitbit"
        assert HealthDataType.STEPS.value in result[0]["data_types"]
        assert HealthDataType.HEART_RATE.value in result[0]["data_types"]
        assert result[0]["trigger"] == "webhook"
        assert result[0]["collection_type"] == "activities"
        mock_ehr_user_lookup.assert_called_with("ABC123", Provider.FITBIT)

    def test_process_body_webhook(self, processor, mock_ehr_user_lookup):
        """Test processing Fitbit body (weight) webhook."""
        payload = [
            {
                "collectionType": "body",
                "date": "2024-01-15",
                "ownerId": "ABC123",
            }
        ]

        result = processor.process_fitbit_webhook(payload)

        assert len(result) == 1
        assert HealthDataType.WEIGHT.value in result[0]["data_types"]

    def test_process_multiple_notifications(self, processor, mock_ehr_user_lookup):
        """Test processing multiple Fitbit notifications in one webhook."""
        payload = [
            {"collectionType": "activities", "date": "2024-01-15", "ownerId": "ABC123"},
            {"collectionType": "body", "date": "2024-01-15", "ownerId": "ABC123"},
        ]

        result = processor.process_fitbit_webhook(payload)

        assert len(result) == 2

    def test_invalid_payload_not_array(self, processor):
        """Test validation fails when payload is not an array."""
        payload = {"collectionType": "activities", "date": "2024-01-15", "ownerId": "ABC123"}

        with pytest.raises(WebhookValidationError) as exc_info:
            processor.process_fitbit_webhook(payload)

        assert "must be an array" in str(exc_info.value)

    def test_missing_required_field_in_notification(self, processor, mock_ehr_user_lookup):
        """Test processing continues when one notification is invalid."""
        payload = [
            {"collectionType": "activities", "date": "2024-01-15"},  # Missing ownerId
            {"collectionType": "body", "date": "2024-01-15", "ownerId": "ABC123"},  # Valid
        ]

        result = processor.process_fitbit_webhook(payload)

        # Should process the valid notification only
        assert len(result) == 1
        assert HealthDataType.WEIGHT.value in result[0]["data_types"]

    def test_user_revoked_access(self, processor, mock_ehr_user_lookup):
        """Test handling of userRevokedAccess notification."""
        payload = [
            {
                "collectionType": "userRevokedAccess",
                "date": "2024-01-15",
                "ownerId": "ABC123",
            }
        ]

        result = processor.process_fitbit_webhook(payload)

        # Should be skipped (access revocation handled separately)
        assert len(result) == 0

    def test_unknown_user_skipped(self, processor):
        """Test notification is skipped when user not found."""
        with patch("webhooks.processors._lookup_ehr_user_id") as mock:
            mock.return_value = None
            payload = [{"collectionType": "activities", "date": "2024-01-15", "ownerId": "UNKNOWN"}]

            result = processor.process_fitbit_webhook(payload)

            assert len(result) == 0

    def test_unsupported_collection_type(self, processor, mock_ehr_user_lookup):
        """Test notification is skipped for unsupported collection type."""
        payload = [{"collectionType": "foods", "date": "2024-01-15", "ownerId": "ABC123"}]

        result = processor.process_fitbit_webhook(payload)

        # Foods is not implemented, should be skipped
        assert len(result) == 0

    def test_date_parsing(self, processor, mock_ehr_user_lookup):
        """Test date is correctly parsed into date range."""
        payload = [{"collectionType": "activities", "date": "2024-01-15", "ownerId": "ABC123"}]

        result = processor.process_fitbit_webhook(payload)

        # Date range should span the full day
        assert "2024-01-15" in result[0]["date_range"]["start"]
        assert "2024-01-16" in result[0]["date_range"]["end"]

    def test_optional_fields_included(self, processor, mock_ehr_user_lookup):
        """Test optional fields are included in result."""
        payload = [
            {
                "collectionType": "activities",
                "date": "2024-01-15",
                "ownerId": "ABC123",
                "ownerType": "user",
                "subscriptionId": "sub-123",
            }
        ]

        result = processor.process_fitbit_webhook(payload)

        assert result[0]["subscription_id"] == "sub-123"
        assert result[0]["owner_type"] == "user"
        assert result[0]["external_user_id"] == "ABC123"


class TestGenericWebhookProcessor:
    """Tests for generic webhook payload processing."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        return WebhookPayloadProcessor()

    def test_process_generic_webhook(self, processor):
        """Test processing generic webhook payload."""
        payload = {
            "user_id": "user-123",
            "data_types": ["heart_rate", "steps"],
            "start_date": "2024-01-15T00:00:00Z",
            "end_date": "2024-01-15T23:59:59Z",
        }

        result = processor.process_generic_webhook(payload, "generic_provider")

        assert len(result) == 1
        assert result[0]["user_id"] == "user-123"
        assert result[0]["provider"] == "generic_provider"
        assert "heart_rate" in result[0]["data_types"]
        assert "steps" in result[0]["data_types"]

    def test_missing_user_id(self, processor):
        """Test validation fails when user_id is missing."""
        payload = {"data_types": ["heart_rate"]}

        with pytest.raises(WebhookValidationError) as exc_info:
            processor.process_generic_webhook(payload, "provider")

        assert "Missing required field: user_id" in str(exc_info.value)

    def test_missing_data_types(self, processor):
        """Test validation fails when data_types is missing."""
        payload = {"user_id": "user-123"}

        with pytest.raises(WebhookValidationError) as exc_info:
            processor.process_generic_webhook(payload, "provider")

        assert "Missing required field: data_types" in str(exc_info.value)

    def test_invalid_data_types_filtered(self, processor):
        """Test invalid data types are filtered out."""
        payload = {
            "user_id": "user-123",
            "data_types": ["heart_rate", "invalid_type", "steps"],
        }

        result = processor.process_generic_webhook(payload, "provider")

        assert "heart_rate" in result[0]["data_types"]
        assert "steps" in result[0]["data_types"]
        assert "invalid_type" not in result[0]["data_types"]

    def test_all_invalid_data_types(self, processor):
        """Test validation fails when all data types are invalid."""
        payload = {
            "user_id": "user-123",
            "data_types": ["invalid1", "invalid2"],
        }

        with pytest.raises(WebhookValidationError) as exc_info:
            processor.process_generic_webhook(payload, "provider")

        assert "No valid data types found" in str(exc_info.value)

    def test_default_date_range(self, processor):
        """Test default date range when not provided."""
        payload = {"user_id": "user-123", "data_types": ["heart_rate"]}

        with patch("webhooks.processors.timezone") as mock_tz:
            mock_now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
            mock_tz.now.return_value = mock_now

            result = processor.process_generic_webhook(payload, "provider")

            assert result[0]["date_range"] is not None


class TestEHRUserLookup:
    """Tests for EHR user lookup function."""

    def test_lookup_existing_user(self):
        """Test looking up an existing user."""
        with patch("webhooks.processors.ProviderLink") as mock_model:
            mock_link = MagicMock()
            mock_link.user.ehr_user_id = "ehr-123"
            mock_model.objects.select_related.return_value.get.return_value = mock_link

            from webhooks.processors import _lookup_ehr_user_id

            result = _lookup_ehr_user_id("external-123", Provider.WITHINGS)

            assert result == "ehr-123"

    def test_lookup_nonexistent_user(self):
        """Test looking up a user that doesn't exist."""
        with patch("webhooks.processors.ProviderLink") as mock_model:
            from base.models import ProviderLink

            mock_model.DoesNotExist = ProviderLink.DoesNotExist
            mock_model.objects.select_related.return_value.get.side_effect = ProviderLink.DoesNotExist

            from webhooks.processors import _lookup_ehr_user_id

            result = _lookup_ehr_user_id("unknown-user", Provider.WITHINGS)

            assert result is None

    def test_lookup_multiple_users_returns_first(self):
        """Test handling when multiple ProviderLinks exist."""
        with patch("webhooks.processors.ProviderLink") as mock_model:
            from base.models import ProviderLink

            mock_model.DoesNotExist = ProviderLink.DoesNotExist
            mock_model.MultipleObjectsReturned = ProviderLink.MultipleObjectsReturned

            # First call raises MultipleObjectsReturned
            mock_model.objects.select_related.return_value.get.side_effect = ProviderLink.MultipleObjectsReturned

            # Then filter().first() returns the first link
            mock_link = MagicMock()
            mock_link.user.ehr_user_id = "ehr-first"
            mock_model.objects.select_related.return_value.filter.return_value.first.return_value = mock_link

            from webhooks.processors import _lookup_ehr_user_id

            result = _lookup_ehr_user_id("multi-user", Provider.WITHINGS)

            assert result == "ehr-first"
