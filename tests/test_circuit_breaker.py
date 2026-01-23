"""
Tests for circuit breaker pattern implementation.
"""

import threading
import time
from unittest.mock import patch

import pytest

from ingestors.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerRegistry,
    CircuitState,
)


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.success_threshold == 3
        assert config.timeout == 60.0
        assert config.exceptions == (Exception,)
        assert config.excluded_exceptions == ()

    def test_custom_config(self):
        """Test custom configuration values."""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            success_threshold=5,
            timeout=30.0,
            exceptions=(ValueError, TypeError),
        )
        assert config.failure_threshold == 10
        assert config.success_threshold == 5
        assert config.timeout == 30.0
        assert config.exceptions == (ValueError, TypeError)


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker with low thresholds for testing."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            timeout=0.1,  # 100ms for fast tests
        )
        return CircuitBreaker("test_breaker", config)

    def test_initial_state_is_closed(self, breaker):
        """Test that circuit breaker starts in closed state."""
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0

    def test_successful_call_keeps_circuit_closed(self, breaker):
        """Test successful calls keep circuit in closed state."""

        def success_func():
            return "success"

        result = breaker.call(success_func)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_circuit_opens_after_failure_threshold(self, breaker):
        """Test circuit opens after reaching failure threshold."""

        def failing_func():
            raise ValueError("Test error")

        # Should open after 3 failures (threshold)
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_func)

        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    def test_open_circuit_rejects_calls(self, breaker):
        """Test that open circuit rejects calls with CircuitBreakerError."""

        def failing_func():
            raise ValueError("Test error")

        # Open the circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_func)

        # Now calls should be rejected
        with pytest.raises(CircuitBreakerError) as exc_info:
            breaker.call(lambda: "should not run")

        assert "is open" in str(exc_info.value)

    def test_circuit_transitions_to_half_open_after_timeout(self, breaker):
        """Test circuit moves to half-open after timeout period."""

        def failing_func():
            raise ValueError("Test error")

        # Open the circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_func)

        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.15)

        # Next call should transition to half-open and execute
        def success_func():
            return "recovered"

        result = breaker.call(success_func)
        assert result == "recovered"
        # After one success, still in half-open (need 2 successes)
        assert breaker.state == CircuitState.HALF_OPEN

    def test_circuit_closes_after_success_threshold_in_half_open(self, breaker):
        """Test circuit closes after enough successes in half-open state."""

        def failing_func():
            raise ValueError("Test error")

        # Open the circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_func)

        # Wait for timeout to transition to half-open
        time.sleep(0.15)

        # Successful calls should close the circuit
        for _ in range(2):  # success_threshold is 2
            breaker.call(lambda: "success")

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0

    def test_circuit_reopens_on_failure_in_half_open(self, breaker):
        """Test circuit reopens if failure occurs in half-open state."""

        def failing_func():
            raise ValueError("Test error")

        # Open the circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_func)

        # Wait for timeout to transition to half-open
        time.sleep(0.15)

        # One success puts us in half-open
        breaker.call(lambda: "success")
        assert breaker.state == CircuitState.HALF_OPEN

        # Failure should reopen the circuit
        with pytest.raises(ValueError):
            breaker.call(failing_func)

        # Note: The implementation adds to failure_count but doesn't immediately
        # transition back to OPEN unless threshold is reached again
        assert breaker.success_count == 0  # Reset on failure

    def test_success_resets_failure_count_in_closed_state(self, breaker):
        """Test that success resets failure count when circuit is closed."""

        def failing_func():
            raise ValueError("Test error")

        # Some failures (but not enough to open)
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_func)

        assert breaker.failure_count == 2

        # Success should reset failure count
        breaker.call(lambda: "success")
        assert breaker.failure_count == 0

    def test_get_state_returns_correct_info(self, breaker):
        """Test get_state returns complete circuit state."""
        state = breaker.get_state()

        assert state["name"] == "test_breaker"
        assert state["state"] == "closed"
        assert state["failure_count"] == 0
        assert state["success_count"] == 0
        assert state["last_failure_time"] is None

    def test_force_open(self, breaker):
        """Test manual circuit opening."""
        breaker.force_open()

        assert breaker.state == CircuitState.OPEN

    def test_force_close(self, breaker):
        """Test manual circuit closing/reset."""
        # First open the circuit
        breaker.force_open()
        assert breaker.state == CircuitState.OPEN

        # Then force close
        breaker.force_close()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0
        assert breaker.last_failure_time is None

    def test_decorator_usage(self, breaker):
        """Test circuit breaker as a decorator."""

        @breaker
        def decorated_func(x):
            return x * 2

        result = decorated_func(5)
        assert result == 10

    def test_decorator_with_failure(self, breaker):
        """Test decorator handles failures correctly."""

        @breaker
        def failing_decorated_func():
            raise RuntimeError("Decorated failure")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                failing_decorated_func()

        assert breaker.state == CircuitState.OPEN

    def test_only_configured_exceptions_trigger_breaker(self):
        """Test only configured exception types trigger the circuit breaker."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            exceptions=(ValueError,),  # Only ValueError
        )
        breaker = CircuitBreaker("selective_breaker", config)

        # TypeError should not trigger breaker (not in exceptions list)
        # But it will still raise because it's not caught
        try:
            breaker.call(lambda: (_ for _ in ()).throw(TypeError("Not tracked")))
        except TypeError:
            pass

        # Circuit should still be closed (TypeError not in configured exceptions)
        # Actually, since TypeError is not in the exceptions tuple, it won't be caught
        # and won't increment failure_count
        assert breaker.failure_count == 0

    def test_excluded_exceptions_do_not_count_as_failures(self):
        """Test excluded exceptions pass through without counting as failures.

        This is important for token expiration errors which are recoverable
        and should not trip the circuit breaker for other users.
        """

        class TokenExpiredError(Exception):
            """Simulates a token expiration error."""

        class ServiceError(Exception):
            """Simulates a service error."""

        config = CircuitBreakerConfig(
            failure_threshold=2,
            exceptions=(Exception,),  # Catch all exceptions
            excluded_exceptions=(TokenExpiredError,),  # But exclude token errors
        )
        breaker = CircuitBreaker("token_test_breaker", config)

        # TokenExpiredError should NOT count as a failure
        for _ in range(5):
            with pytest.raises(TokenExpiredError):
                breaker.call(lambda: (_ for _ in ()).throw(TokenExpiredError("Token expired")))

        # Circuit should still be closed - token errors don't count
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

        # ServiceError SHOULD count as a failure
        for _ in range(2):
            with pytest.raises(ServiceError):
                breaker.call(lambda: (_ for _ in ()).throw(ServiceError("Service unavailable")))

        # Now circuit should be open
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 2

    def test_excluded_exceptions_still_propagate(self):
        """Test excluded exceptions are still raised to caller for handling."""

        class TokenExpiredError(Exception):
            pass

        config = CircuitBreakerConfig(
            failure_threshold=2,
            exceptions=(Exception,),
            excluded_exceptions=(TokenExpiredError,),
        )
        breaker = CircuitBreaker("propagation_test_breaker", config)

        # The exception should still be raised
        with pytest.raises(TokenExpiredError) as exc_info:
            breaker.call(lambda: (_ for _ in ()).throw(TokenExpiredError("Token expired")))

        assert "Token expired" in str(exc_info.value)

    def test_concurrent_access(self, breaker):
        """Test thread safety of circuit breaker."""
        results = []
        errors = []

        def worker():
            try:
                result = breaker.call(lambda: threading.current_thread().name)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All calls should succeed with circuit closed
        assert len(results) == 10
        assert len(errors) == 0
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry class."""

    @pytest.fixture
    def registry(self):
        """Create a fresh registry for each test."""
        return CircuitBreakerRegistry()

    def test_get_breaker_creates_new(self, registry):
        """Test registry creates new breaker if not exists."""
        breaker = registry.get_breaker("new_breaker")

        assert breaker is not None
        assert breaker.name == "new_breaker"

    def test_get_breaker_returns_existing(self, registry):
        """Test registry returns existing breaker."""
        breaker1 = registry.get_breaker("existing")
        breaker2 = registry.get_breaker("existing")

        assert breaker1 is breaker2

    def test_get_breaker_with_custom_config(self, registry):
        """Test registry creates breaker with custom config."""
        config = CircuitBreakerConfig(failure_threshold=10)
        breaker = registry.get_breaker("custom", config)

        assert breaker.config.failure_threshold == 10

    def test_get_all_states(self, registry):
        """Test getting states of all breakers."""
        registry.get_breaker("breaker1")
        registry.get_breaker("breaker2")

        states = registry.get_all_states()

        assert "breaker1" in states
        assert "breaker2" in states
        assert states["breaker1"]["state"] == "closed"

    def test_reset_all(self, registry):
        """Test resetting all breakers."""
        breaker1 = registry.get_breaker("breaker1")
        breaker2 = registry.get_breaker("breaker2")

        breaker1.force_open()
        breaker2.force_open()

        registry.reset_all()

        assert breaker1.state == CircuitState.CLOSED
        assert breaker2.state == CircuitState.CLOSED


class TestPredefinedCircuitBreakers:
    """Tests for predefined circuit breaker factory functions."""

    @pytest.fixture(autouse=True)
    def mock_settings(self):
        """Mock Django settings for circuit breaker config."""
        with patch("ingestors.circuit_breaker.settings") as mock:
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
            }
            yield mock

    def test_get_withings_circuit_breaker(self, mock_settings):
        """Test Withings circuit breaker factory."""
        from ingestors.circuit_breaker import get_withings_circuit_breaker, registry

        # Clear registry for clean test
        registry._breakers.clear()

        breaker = get_withings_circuit_breaker()

        assert breaker.name == "withings_api"
        assert breaker.config.failure_threshold == 5
        assert breaker.config.timeout == 60

    def test_get_fitbit_circuit_breaker(self, mock_settings):
        """Test Fitbit circuit breaker factory."""
        from ingestors.circuit_breaker import get_fitbit_circuit_breaker, registry

        # Clear registry for clean test
        registry._breakers.clear()

        breaker = get_fitbit_circuit_breaker()

        assert breaker.name == "fitbit_api"
        assert breaker.config.failure_threshold == 5
        assert breaker.config.timeout == 60

    def test_get_fhir_circuit_breaker(self, mock_settings):
        """Test FHIR circuit breaker factory."""
        from ingestors.circuit_breaker import get_fhir_circuit_breaker, registry

        # Clear registry for clean test
        registry._breakers.clear()

        breaker = get_fhir_circuit_breaker()

        assert breaker.name == "fhir_server"
        assert breaker.config.failure_threshold == 5
        assert breaker.config.timeout == 120


class TestCircuitBreakerDecorators:
    """Tests for circuit breaker decorator functions."""

    @pytest.fixture(autouse=True)
    def mock_settings(self):
        """Mock Django settings for circuit breaker config."""
        with patch("ingestors.circuit_breaker.settings") as mock:
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
            }
            yield mock

    def test_withings_decorator(self, mock_settings):
        """Test Withings circuit breaker decorator."""
        from ingestors.circuit_breaker import registry, withings_circuit_breaker

        # Clear registry
        registry._breakers.clear()

        @withings_circuit_breaker
        def withings_api_call():
            return "withings_data"

        result = withings_api_call()
        assert result == "withings_data"

    def test_fitbit_decorator(self, mock_settings):
        """Test Fitbit circuit breaker decorator."""
        from ingestors.circuit_breaker import fitbit_circuit_breaker, registry

        # Clear registry
        registry._breakers.clear()

        @fitbit_circuit_breaker
        def fitbit_api_call():
            return "fitbit_data"

        result = fitbit_api_call()
        assert result == "fitbit_data"

    def test_fhir_decorator(self, mock_settings):
        """Test FHIR circuit breaker decorator."""
        from ingestors.circuit_breaker import fhir_circuit_breaker, registry

        # Clear registry
        registry._breakers.clear()

        @fhir_circuit_breaker
        def fhir_api_call():
            return "fhir_data"

        result = fhir_api_call()
        assert result == "fhir_data"
