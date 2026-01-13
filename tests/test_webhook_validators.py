"""
Tests for webhook signature validation.
"""

import base64
import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest

from webhooks.validators import WebhookSignatureValidator


class TestWithingsSignatureValidation:
    """Tests for Withings webhook signature validation."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return WebhookSignatureValidator()

    @pytest.fixture
    def mock_request(self):
        """Create a mock Django request."""
        request = MagicMock()
        request.body = b'{"userid": 12345, "appli": 1}'
        request.META = {}
        return request

    def test_valid_withings_signature(self, validator, mock_request):
        """Test validation with correct HMAC-SHA256 signature."""
        secret = "test_webhook_secret"
        expected_sig = hmac.new(secret.encode(), mock_request.body, hashlib.sha256).hexdigest()
        mock_request.META["HTTP_X_WITHINGS_SIGNATURE"] = expected_sig

        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.WITHINGS_WEBHOOK_SECRET = secret
            result = validator.validate_withings_signature(mock_request)

        assert result is True

    def test_valid_withings_signature_with_prefix(self, validator, mock_request):
        """Test validation with sha256= prefix in signature."""
        secret = "test_webhook_secret"
        expected_sig = hmac.new(secret.encode(), mock_request.body, hashlib.sha256).hexdigest()
        mock_request.META["HTTP_X_WITHINGS_SIGNATURE"] = f"sha256={expected_sig}"

        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.WITHINGS_WEBHOOK_SECRET = secret
            result = validator.validate_withings_signature(mock_request)

        assert result is True

    def test_invalid_withings_signature(self, validator, mock_request):
        """Test validation fails with incorrect signature."""
        mock_request.META["HTTP_X_WITHINGS_SIGNATURE"] = "invalid_signature"

        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.WITHINGS_WEBHOOK_SECRET = "test_secret"
            result = validator.validate_withings_signature(mock_request)

        assert result is False

    def test_missing_withings_signature_header(self, validator, mock_request):
        """Test validation fails when signature header is missing."""
        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.WITHINGS_WEBHOOK_SECRET = "test_secret"
            result = validator.validate_withings_signature(mock_request)

        assert result is False

    def test_withings_validation_skipped_without_secret(self, validator, mock_request):
        """Test validation is skipped when secret is not configured."""
        with patch("webhooks.validators.settings") as mock_settings:
            # No secret configured
            del mock_settings.WITHINGS_WEBHOOK_SECRET
            mock_settings.configure_mock(WITHINGS_WEBHOOK_SECRET=None)
            result = validator.validate_withings_signature(mock_request)

        # Should return True (skip validation in dev)
        assert result is True

    def test_withings_validation_handles_exception(self, validator, mock_request):
        """Test validation handles unexpected exceptions gracefully."""
        mock_request.body = None  # Will cause exception when processing

        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.WITHINGS_WEBHOOK_SECRET = "test_secret"
            mock_request.META["HTTP_X_WITHINGS_SIGNATURE"] = "some_sig"
            result = validator.validate_withings_signature(mock_request)

        assert result is False


class TestFitbitSignatureValidation:
    """Tests for Fitbit webhook signature validation."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return WebhookSignatureValidator()

    @pytest.fixture
    def mock_request(self):
        """Create a mock Django request."""
        request = MagicMock()
        request.body = b'[{"collectionType": "activities", "date": "2023-01-15", "ownerId": "ABC123"}]'
        request.META = {}
        return request

    def test_valid_fitbit_signature(self, validator, mock_request):
        """Test validation with correct HMAC-SHA1 base64 signature."""
        secret = "fitbit_client_secret"
        expected_sig = base64.b64encode(hmac.new(secret.encode(), mock_request.body, hashlib.sha1).digest()).decode()
        mock_request.META["HTTP_X_FITBIT_SIGNATURE"] = expected_sig

        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.SOCIAL_AUTH_FITBIT_SECRET = secret
            result = validator.validate_fitbit_signature(mock_request)

        assert result is True

    def test_invalid_fitbit_signature(self, validator, mock_request):
        """Test validation fails with incorrect signature."""
        mock_request.META["HTTP_X_FITBIT_SIGNATURE"] = "aW52YWxpZA=="  # base64 "invalid"

        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.SOCIAL_AUTH_FITBIT_SECRET = "test_secret"
            result = validator.validate_fitbit_signature(mock_request)

        assert result is False

    def test_missing_fitbit_signature_header(self, validator, mock_request):
        """Test validation fails when signature header is missing."""
        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.SOCIAL_AUTH_FITBIT_SECRET = "test_secret"
            result = validator.validate_fitbit_signature(mock_request)

        assert result is False

    def test_fitbit_validation_skipped_without_secret(self, validator, mock_request):
        """Test validation is skipped when secret is not configured."""
        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.configure_mock(SOCIAL_AUTH_FITBIT_SECRET=None)
            result = validator.validate_fitbit_signature(mock_request)

        # Should return True (skip validation in dev)
        assert result is True

    def test_fitbit_validation_handles_exception(self, validator, mock_request):
        """Test validation handles unexpected exceptions gracefully."""
        mock_request.body = None  # Will cause exception

        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.SOCIAL_AUTH_FITBIT_SECRET = "test_secret"
            mock_request.META["HTTP_X_FITBIT_SIGNATURE"] = "some_sig"
            result = validator.validate_fitbit_signature(mock_request)

        assert result is False


class TestGenericSignatureValidation:
    """Tests for generic webhook signature validation."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return WebhookSignatureValidator()

    @pytest.fixture
    def mock_request(self):
        """Create a mock Django request."""
        request = MagicMock()
        request.body = b'{"test": "data"}'
        request.META = {}
        return request

    def test_valid_generic_sha256_signature(self, validator, mock_request):
        """Test generic validation with SHA256."""
        secret = "generic_secret"
        expected_sig = hmac.new(secret.encode(), mock_request.body, hashlib.sha256).hexdigest()
        mock_request.META["HTTP_X_WEBHOOK_SIGNATURE"] = expected_sig

        result = validator.validate_generic_signature(mock_request, secret)
        assert result is True

    def test_valid_generic_sha1_signature(self, validator, mock_request):
        """Test generic validation with SHA1."""
        secret = "generic_secret"
        expected_sig = hmac.new(secret.encode(), mock_request.body, hashlib.sha1).hexdigest()
        mock_request.META["HTTP_X_WEBHOOK_SIGNATURE"] = expected_sig

        result = validator.validate_generic_signature(mock_request, secret, algorithm="sha1")
        assert result is True

    def test_valid_generic_signature_with_algorithm_prefix(self, validator, mock_request):
        """Test generic validation with algorithm prefix in signature."""
        secret = "generic_secret"
        expected_sig = hmac.new(secret.encode(), mock_request.body, hashlib.sha256).hexdigest()
        mock_request.META["HTTP_X_WEBHOOK_SIGNATURE"] = f"sha256={expected_sig}"

        result = validator.validate_generic_signature(mock_request, secret)
        assert result is True

    def test_invalid_generic_signature(self, validator, mock_request):
        """Test generic validation fails with incorrect signature."""
        mock_request.META["HTTP_X_WEBHOOK_SIGNATURE"] = "wrong_signature"

        result = validator.validate_generic_signature(mock_request, "secret")
        assert result is False

    def test_missing_generic_signature_header(self, validator, mock_request):
        """Test generic validation fails when header is missing."""
        result = validator.validate_generic_signature(mock_request, "secret")
        assert result is False

    def test_custom_header_name(self, validator, mock_request):
        """Test generic validation with custom header name."""
        secret = "generic_secret"
        expected_sig = hmac.new(secret.encode(), mock_request.body, hashlib.sha256).hexdigest()
        mock_request.META["HTTP_X_CUSTOM_SIG"] = expected_sig

        result = validator.validate_generic_signature(mock_request, secret, signature_header_name="HTTP_X_CUSTOM_SIG")
        assert result is True

    def test_unsupported_algorithm(self, validator, mock_request):
        """Test generic validation fails with unsupported algorithm."""
        mock_request.META["HTTP_X_WEBHOOK_SIGNATURE"] = "some_sig"

        result = validator.validate_generic_signature(mock_request, "secret", algorithm="unsupported")
        assert result is False

    def test_generic_validation_skipped_without_secret(self, validator, mock_request):
        """Test generic validation is skipped when no secret provided."""
        result = validator.validate_generic_signature(mock_request, "")
        assert result is True

        result = validator.validate_generic_signature(mock_request, None)
        assert result is True


class TestBearerTokenValidation:
    """Tests for Bearer token validation."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return WebhookSignatureValidator()

    @pytest.fixture
    def mock_request(self):
        """Create a mock Django request."""
        request = MagicMock()
        request.META = {}
        return request

    def test_valid_bearer_token(self, validator, mock_request):
        """Test validation with correct Bearer token."""
        expected_token = "valid_api_token_12345"
        mock_request.META["HTTP_AUTHORIZATION"] = f"Bearer {expected_token}"

        result = validator.validate_bearer_token(mock_request, expected_token)
        assert result is True

    def test_invalid_bearer_token(self, validator, mock_request):
        """Test validation fails with incorrect Bearer token."""
        mock_request.META["HTTP_AUTHORIZATION"] = "Bearer wrong_token"

        result = validator.validate_bearer_token(mock_request, "expected_token")
        assert result is False

    def test_missing_authorization_header(self, validator, mock_request):
        """Test validation fails when Authorization header is missing."""
        result = validator.validate_bearer_token(mock_request, "expected_token")
        assert result is False

    def test_non_bearer_authorization(self, validator, mock_request):
        """Test validation fails with non-Bearer authorization."""
        mock_request.META["HTTP_AUTHORIZATION"] = "Basic dXNlcjpwYXNz"  # Basic auth

        result = validator.validate_bearer_token(mock_request, "expected_token")
        assert result is False

    def test_bearer_validation_skipped_without_expected_token(self, validator, mock_request):
        """Test validation is skipped when no expected token provided."""
        result = validator.validate_bearer_token(mock_request, None)
        assert result is True

        result = validator.validate_bearer_token(mock_request, "")
        assert result is True


class TestValidationConfiguration:
    """Tests for validation configuration methods."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return WebhookSignatureValidator()

    def test_is_signature_validation_enabled_with_withings(self, validator):
        """Test validation is enabled when Withings secret is set."""
        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.WITHINGS_WEBHOOK_SECRET = "secret"
            mock_settings.configure_mock(SOCIAL_AUTH_FITBIT_SECRET=None, WEBHOOK_SIGNATURE_VALIDATION_ENABLED=False)

            result = validator.is_signature_validation_enabled()
            assert result is True

    def test_is_signature_validation_enabled_with_fitbit(self, validator):
        """Test validation is enabled when Fitbit secret is set."""
        with patch("webhooks.validators.settings") as mock_settings:
            # hasattr will return True
            mock_settings.SOCIAL_AUTH_FITBIT_SECRET = "secret"
            result = validator.is_signature_validation_enabled()
            assert result is True

    def test_get_validation_config(self, validator):
        """Test getting validation configuration."""
        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.WITHINGS_WEBHOOK_SECRET = "withings_secret"
            mock_settings.SOCIAL_AUTH_FITBIT_SECRET = "fitbit_secret"

            config = validator.get_validation_config()

            assert config["withings_secret_configured"] is True
            assert config["fitbit_secret_configured"] is True
            assert config["validation_enabled"] is True
            assert "sha256" in config["supported_algorithms"]
            assert "sha1" in config["supported_algorithms"]
            assert "md5" in config["supported_algorithms"]

    def test_get_validation_config_no_secrets(self, validator):
        """Test getting validation config when no secrets configured."""
        with patch("webhooks.validators.settings") as mock_settings:
            mock_settings.configure_mock(WITHINGS_WEBHOOK_SECRET=None, SOCIAL_AUTH_FITBIT_SECRET=None)

            config = validator.get_validation_config()

            assert config["withings_secret_configured"] is False
            assert config["fitbit_secret_configured"] is False


class TestTimingAttackPrevention:
    """Tests to verify timing attack prevention in signature comparison."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return WebhookSignatureValidator()

    def test_constant_time_comparison_used_withings(self, validator):
        """Verify hmac.compare_digest is used for Withings validation."""
        # This is more of a code review test - we verify the implementation
        # uses hmac.compare_digest by checking the source
        import inspect

        source = inspect.getsource(validator.validate_withings_signature)
        assert "hmac.compare_digest" in source

    def test_constant_time_comparison_used_fitbit(self, validator):
        """Verify hmac.compare_digest is used for Fitbit validation."""
        import inspect

        source = inspect.getsource(validator.validate_fitbit_signature)
        assert "hmac.compare_digest" in source

    def test_constant_time_comparison_used_bearer(self, validator):
        """Verify hmac.compare_digest is used for Bearer token validation."""
        import inspect

        source = inspect.getsource(validator.validate_bearer_token)
        assert "hmac.compare_digest" in source
