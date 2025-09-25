"""
Circuit breaker pattern implementation for external API calls.
"""
import time
import logging
from typing import Callable, Any, Optional, Dict
from enum import Enum
from dataclasses import dataclass
from threading import Lock
from functools import wraps
from django.conf import settings

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5      # Number of failures before opening
    success_threshold: int = 3      # Number of successes to close from half-open
    timeout: float = 60.0           # Seconds before trying half-open
    exceptions: tuple = (Exception,)  # Exceptions that trigger circuit breaker


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """Circuit breaker implementation."""

    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.lock = Lock()

    def __call__(self, func: Callable) -> Callable:
        """Decorator to wrap functions with circuit breaker."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)
        return wrapper

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        with self.lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    logger.info(f"Circuit breaker {self.name} moved to HALF_OPEN")
                else:
                    logger.warning(f"Circuit breaker {self.name} is OPEN - rejecting call")
                    raise CircuitBreakerError(f"Circuit breaker {self.name} is open")

        # Execute the function
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result

        except self.config.exceptions as e:
            self._on_failure()
            logger.error(f"Circuit breaker {self.name} recorded failure: {e}")
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.config.timeout

    def _on_success(self):
        """Handle successful execution."""
        with self.lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self._reset()
                    logger.info(f"Circuit breaker {self.name} reset to CLOSED")
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0  # Reset failure count on success

    def _on_failure(self):
        """Handle failed execution."""
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            self.success_count = 0  # Reset success count on failure

            if self.failure_count >= self.config.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(f"Circuit breaker {self.name} opened after {self.failure_count} failures")

    def _reset(self):
        """Reset circuit breaker to closed state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None

    def get_state(self) -> dict:
        """Get current circuit breaker state."""
        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'last_failure_time': self.last_failure_time,
        }

    def force_open(self):
        """Manually open the circuit breaker."""
        with self.lock:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker {self.name} manually opened")

    def force_close(self):
        """Manually close the circuit breaker."""
        with self.lock:
            self._reset()
            logger.info(f"Circuit breaker {self.name} manually closed")


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = Lock()

    def get_breaker(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
        """Get or create a circuit breaker."""
        with self._lock:
            if name not in self._breakers:
                if config is None:
                    config = CircuitBreakerConfig()
                self._breakers[name] = CircuitBreaker(name, config)
            return self._breakers[name]

    def get_all_states(self) -> Dict[str, dict]:
        """Get states of all circuit breakers."""
        return {name: breaker.get_state() for name, breaker in self._breakers.items()}

    def reset_all(self):
        """Reset all circuit breakers."""
        for breaker in self._breakers.values():
            breaker.force_close()


# Global registry
registry = CircuitBreakerRegistry()


# Predefined circuit breakers for common services
def get_withings_circuit_breaker() -> CircuitBreaker:
    """Get circuit breaker for Withings API."""
    config = CircuitBreakerConfig(
        failure_threshold=settings.CIRCUIT_BREAKER_CONFIG['FAILURE_THRESHOLD'],
        success_threshold=2,  # Default success threshold
        timeout=settings.CIRCUIT_BREAKER_CONFIG['PROVIDER_TIMEOUT'],
        exceptions=(Exception,)
    )
    return registry.get_breaker("withings_api", config)


def get_fitbit_circuit_breaker() -> CircuitBreaker:
    """Get circuit breaker for Fitbit API."""
    config = CircuitBreakerConfig(
        failure_threshold=settings.CIRCUIT_BREAKER_CONFIG['FAILURE_THRESHOLD'],
        success_threshold=2,  # Default success threshold
        timeout=settings.CIRCUIT_BREAKER_CONFIG['PROVIDER_TIMEOUT'],
        exceptions=(Exception,)
    )
    return registry.get_breaker("fitbit_api", config)


def get_fhir_circuit_breaker() -> CircuitBreaker:
    """Get circuit breaker for FHIR server."""
    config = CircuitBreakerConfig(
        failure_threshold=5,  # Higher threshold for FHIR server
        success_threshold=3,  # Higher success threshold for FHIR
        timeout=settings.CIRCUIT_BREAKER_CONFIG['FHIR_TIMEOUT'],
        exceptions=(Exception,)
    )
    return registry.get_breaker("fhir_server", config)


# Decorator functions for easy use
def withings_circuit_breaker(func: Callable) -> Callable:
    """Decorator for Withings API calls."""
    breaker = get_withings_circuit_breaker()
    return breaker(func)


def fitbit_circuit_breaker(func: Callable) -> Callable:
    """Decorator for Fitbit API calls."""
    breaker = get_fitbit_circuit_breaker()
    return breaker(func)


def fhir_circuit_breaker(func: Callable) -> Callable:
    """Decorator for FHIR server calls."""
    breaker = get_fhir_circuit_breaker()
    return breaker(func)