"""
Tests for error handling utilities.
"""

from unittest.mock import patch

import pytest

from ingestors.error_handling import (
    ErrorType,
    HealthDataError,
    RetryHandler,
    _classify_error,
    aggressive_retry,
    conservative_retry,
    default_retry,
    error_handler,
)


class TestErrorType:
    """Tests for ErrorType enum."""

    def test_error_type_values(self):
        """Test error type enum values."""
        assert ErrorType.API_ERROR.value == "api_error"
        assert ErrorType.AUTH_ERROR.value == "auth_error"
        assert ErrorType.RATE_LIMIT_ERROR.value == "rate_limit_error"
        assert ErrorType.NETWORK_ERROR.value == "network_error"
        assert ErrorType.VALIDATION_ERROR.value == "validation_error"
        assert ErrorType.UNKNOWN_ERROR.value == "unknown_error"


class TestHealthDataError:
    """Tests for HealthDataError exception class."""

    def test_basic_exception(self):
        """Test creating basic exception."""
        error = HealthDataError("Test error", ErrorType.API_ERROR)

        assert str(error) == "Test error"
        assert error.error_type == ErrorType.API_ERROR
        assert error.provider is None

    def test_exception_with_provider(self):
        """Test creating exception with provider."""
        error = HealthDataError("Rate limit exceeded", ErrorType.RATE_LIMIT_ERROR, provider="withings")

        assert error.provider == "withings"
        assert error.error_type == ErrorType.RATE_LIMIT_ERROR

    def test_exception_with_extra_details(self):
        """Test creating exception with additional details."""
        error = HealthDataError(
            "Auth failed",
            ErrorType.AUTH_ERROR,
            provider="fitbit",
            status_code=401,
            response_body="Unauthorized",
        )

        assert error.details["status_code"] == 401
        assert error.details["response_body"] == "Unauthorized"


class TestClassifyError:
    """Tests for _classify_error function."""

    def test_classify_rate_limit_errors(self):
        """Test classification of rate limit errors."""
        rate_limit_errors = [
            Exception("Rate limit exceeded"),
            Exception("429 Too Many Requests"),
            Exception("too many requests"),
        ]

        for error in rate_limit_errors:
            assert _classify_error(error) == ErrorType.RATE_LIMIT_ERROR

    def test_classify_auth_errors(self):
        """Test classification of authentication errors."""
        auth_errors = [
            Exception("401 Unauthorized"),
            Exception("Authentication failed"),
            Exception("Invalid token"),
            Exception("403 Forbidden"),
        ]

        for error in auth_errors:
            assert _classify_error(error) == ErrorType.AUTH_ERROR

    def test_classify_network_errors(self):
        """Test classification of network errors."""
        network_errors = [
            Exception("Connection timeout"),
            Exception("Network error occurred"),
            Exception("DNS resolution failed"),
            Exception("502 Bad Gateway"),
            Exception("503 Service Unavailable"),
            Exception("504 Gateway Timeout"),
        ]

        for error in network_errors:
            assert _classify_error(error) == ErrorType.NETWORK_ERROR

    def test_classify_validation_errors(self):
        """Test classification of validation errors."""
        validation_errors = [
            Exception("Validation failed"),
            Exception("Invalid parameter"),
            Exception("400 Bad Request"),
        ]

        for error in validation_errors:
            assert _classify_error(error) == ErrorType.VALIDATION_ERROR

    def test_classify_api_errors(self):
        """Test classification of API errors."""
        api_errors = [
            Exception("API error occurred"),
            Exception("500 Internal Server Error"),
        ]

        for error in api_errors:
            assert _classify_error(error) == ErrorType.API_ERROR

    def test_classify_unknown_errors(self):
        """Test classification of unknown errors."""
        unknown_errors = [
            Exception("Something went wrong"),
            Exception("Unexpected error"),
            Exception(""),
        ]

        for error in unknown_errors:
            assert _classify_error(error) == ErrorType.UNKNOWN_ERROR


class TestErrorHandler:
    """Tests for error_handler decorator."""

    def test_success_records_metrics(self):
        """Test successful execution records metrics."""
        with patch("ingestors.error_handling.metrics") as mock_metrics:

            @error_handler("withings", "heart_rate_fetch")
            def successful_operation():
                return "success"

            result = successful_operation()

            assert result == "success"
            mock_metrics.record_sync_operation.assert_called_once()
            call_args = mock_metrics.record_sync_operation.call_args
            assert call_args.kwargs["provider"] == "withings"
            assert call_args.kwargs["operation_type"] == "heart_rate_fetch"
            assert call_args.kwargs["status"] == "success"

    def test_error_records_metrics_and_raises(self):
        """Test error records metrics and re-raises."""
        with patch("ingestors.error_handling.metrics") as mock_metrics:

            @error_handler("fitbit", "device_sync")
            def failing_operation():
                raise Exception("Connection timeout")

            with pytest.raises(HealthDataError) as exc_info:
                failing_operation()

            assert exc_info.value.error_type == ErrorType.NETWORK_ERROR
            assert mock_metrics.record_sync_operation.called
            assert mock_metrics.record_provider_api_error.called

    def test_rate_limit_error_records_rate_limit_metric(self):
        """Test rate limit errors record specific metric."""
        with patch("ingestors.error_handling.metrics") as mock_metrics:

            @error_handler("withings", "fetch_data")
            def rate_limited_operation():
                raise Exception("429 Too Many Requests")

            with pytest.raises(HealthDataError) as exc_info:
                rate_limited_operation()

            assert exc_info.value.error_type == ErrorType.RATE_LIMIT_ERROR
            mock_metrics.record_rate_limit.assert_called_once_with("withings")

    def test_auth_error_wraps_correctly(self):
        """Test auth errors are wrapped correctly."""
        with patch("ingestors.error_handling.metrics"):

            @error_handler("fitbit", "refresh_token")
            def auth_failing_operation():
                raise Exception("401 Unauthorized")

            with pytest.raises(HealthDataError) as exc_info:
                auth_failing_operation()

            assert exc_info.value.error_type == ErrorType.AUTH_ERROR
            assert "Authentication failed" in str(exc_info.value)


class TestRetryHandler:
    """Tests for RetryHandler class."""

    def test_success_on_first_try(self):
        """Test successful execution doesn't retry."""
        handler = RetryHandler(max_retries=3)
        call_count = 0

        @handler
        def successful_operation():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_operation()

        assert result == "success"
        assert call_count == 1

    def test_retry_on_retryable_error(self):
        """Test retry on retryable error."""
        handler = RetryHandler(max_retries=3, base_delay=0.01)  # Very short delay
        call_count = 0

        @handler
        def eventually_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise HealthDataError("Network error", ErrorType.NETWORK_ERROR)
            return "success"

        result = eventually_succeeds()

        assert result == "success"
        assert call_count == 3

    def test_no_retry_on_non_retryable_error(self):
        """Test no retry on non-retryable errors."""
        handler = RetryHandler(
            max_retries=3,
            base_delay=0.01,
            retryable_errors=(ErrorType.NETWORK_ERROR,),
        )
        call_count = 0

        @handler
        def auth_failing():
            nonlocal call_count
            call_count += 1
            raise HealthDataError("Auth failed", ErrorType.AUTH_ERROR)

        with pytest.raises(HealthDataError) as exc_info:
            auth_failing()

        assert exc_info.value.error_type == ErrorType.AUTH_ERROR
        assert call_count == 1  # No retry

    def test_exhausts_retries(self):
        """Test handler raises after exhausting retries."""
        handler = RetryHandler(max_retries=2, base_delay=0.01)
        call_count = 0

        @handler
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise HealthDataError("Network failure", ErrorType.NETWORK_ERROR)

        with pytest.raises(HealthDataError):
            always_fails()

        assert call_count == 3  # Initial + 2 retries

    def test_exponential_backoff(self):
        """Test exponential backoff calculation."""
        handler = RetryHandler(
            max_retries=3,
            base_delay=1.0,
            backoff_factor=2.0,
            max_delay=10.0,
        )

        # Test delay calculation: base_delay * (backoff_factor ** attempt)
        # Attempt 0: 1.0 * (2.0 ** 0) = 1.0
        # Attempt 1: 1.0 * (2.0 ** 1) = 2.0
        # Attempt 2: 1.0 * (2.0 ** 2) = 4.0
        # Max delay caps at 10.0

        delays = []
        with patch("time.sleep") as mock_sleep:

            @handler
            def failing_op():
                raise HealthDataError("Error", ErrorType.NETWORK_ERROR)

            try:
                failing_op()
            except HealthDataError:
                pass

            # Collect delays from sleep calls
            delays = [call.args[0] for call in mock_sleep.call_args_list]

        # Should have 3 sleep calls (for retries 1, 2, 3)
        assert len(delays) == 3
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0

    def test_max_delay_cap(self):
        """Test max delay caps the backoff."""
        handler = RetryHandler(
            max_retries=5,
            base_delay=10.0,
            backoff_factor=3.0,
            max_delay=20.0,
        )

        delays = []
        with patch("time.sleep") as mock_sleep:

            @handler
            def failing_op():
                raise HealthDataError("Error", ErrorType.NETWORK_ERROR)

            try:
                failing_op()
            except HealthDataError:
                pass

            delays = [call.args[0] for call in mock_sleep.call_args_list]

        # All delays should be capped at max_delay (20.0)
        for delay in delays:
            assert delay <= 20.0

    def test_converts_regular_exceptions_to_health_data_error(self):
        """Test regular exceptions are converted to HealthDataError."""
        handler = RetryHandler(max_retries=0, base_delay=0.01)

        @handler
        def raises_regular_exception():
            raise Exception("Some validation error occurred")

        with pytest.raises(HealthDataError) as exc_info:
            raises_regular_exception()

        assert exc_info.value.error_type == ErrorType.VALIDATION_ERROR

    def test_custom_retryable_errors(self):
        """Test custom retryable error types."""
        handler = RetryHandler(
            max_retries=2,
            base_delay=0.01,
            retryable_errors=(ErrorType.VALIDATION_ERROR,),  # Only validation errors
        )
        call_count = 0

        @handler
        def validation_failing():
            nonlocal call_count
            call_count += 1
            raise HealthDataError("Invalid data", ErrorType.VALIDATION_ERROR)

        with pytest.raises(HealthDataError):
            validation_failing()

        assert call_count == 3  # Retried for validation errors


class TestPredefinedRetryHandlers:
    """Tests for predefined retry handlers."""

    def test_default_retry_configuration(self):
        """Test default retry handler configuration."""
        assert default_retry.max_retries == 3
        assert default_retry.base_delay == 1.0
        assert default_retry.max_delay == 60.0
        assert default_retry.backoff_factor == 2.0

    def test_aggressive_retry_configuration(self):
        """Test aggressive retry handler configuration."""
        assert aggressive_retry.max_retries == 5
        assert aggressive_retry.base_delay == 0.5

    def test_conservative_retry_configuration(self):
        """Test conservative retry handler configuration."""
        assert conservative_retry.max_retries == 2
        assert conservative_retry.base_delay == 2.0

    def test_predefined_handlers_are_callable(self):
        """Test predefined handlers work as decorators."""
        call_count = 0

        @default_retry
        def test_operation():
            nonlocal call_count
            call_count += 1
            return "success"

        result = test_operation()
        assert result == "success"
        assert call_count == 1
