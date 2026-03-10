"""
Production-ready error handling for health data operations.
"""

import logging
import time
import traceback
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import Any

from metrics.collectors import metrics

logger = logging.getLogger(__name__)


class ErrorType(Enum):
    """Types of errors that can occur."""

    API_ERROR = "api_error"
    AUTH_ERROR = "auth_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    NETWORK_ERROR = "network_error"
    VALIDATION_ERROR = "validation_error"
    UNKNOWN_ERROR = "unknown_error"


class HealthDataError(Exception):
    """Base exception for health data operations."""

    def __init__(self, message: str, error_type: ErrorType, provider: str | None = None, **kwargs):
        super().__init__(message)
        self.error_type = error_type
        self.provider = provider
        self.details = kwargs


def error_handler(provider: str, operation: str):
    """
    Decorator for comprehensive error handling with metrics and logging.

    Args:
        provider: Provider name (e.g., 'withings', 'fitbit')
        operation: Operation name (e.g., 'heart_rate_fetch', 'device_sync')
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            error_type = None
            error_message = None

            try:
                result = func(*args, **kwargs)

                # Record success metrics
                duration = time.time() - start_time
                metrics.record_sync_operation(
                    provider=provider, operation_type=operation, status="success", duration=duration
                )

                return result

            except Exception as e:
                duration = time.time() - start_time
                error_message = str(e)

                # Classify error type
                error_type = _classify_error(e)

                # Record error metrics
                metrics.record_sync_operation(
                    provider=provider, operation_type=operation, status="error", duration=duration
                )
                metrics.record_provider_api_error(provider, error_type.value)

                # Log error with context
                logger.error(
                    "Operation failed",
                    extra={
                        "provider": provider,
                        "operation": operation,
                        "error_type": error_type.value,
                        "error_message": error_message,
                        "duration": duration,
                        "traceback": traceback.format_exc(),
                    },
                )

                # Handle specific error types
                if error_type == ErrorType.RATE_LIMIT_ERROR:
                    metrics.record_rate_limit(provider)
                    raise HealthDataError(
                        f"Rate limit exceeded for {provider}", error_type, provider=provider, original_error=e
                    )
                elif error_type == ErrorType.AUTH_ERROR:
                    raise HealthDataError(
                        f"Authentication failed for {provider}", error_type, provider=provider, original_error=e
                    )
                else:
                    raise HealthDataError(
                        f"Operation {operation} failed for {provider}: {error_message}",
                        error_type,
                        provider=provider,
                        original_error=e,
                    )

        return wrapper

    return decorator


def _classify_error(exception: Exception) -> ErrorType:
    """Classify exception into error types."""
    error_str = str(exception).lower()

    # Rate limit errors
    if "rate limit" in error_str or "429" in error_str or "too many requests" in error_str:
        return ErrorType.RATE_LIMIT_ERROR

    # Authentication errors
    if any(auth_term in error_str for auth_term in ["401", "unauthorized", "auth", "token", "forbidden", "403"]):
        return ErrorType.AUTH_ERROR

    # Network errors
    if any(net_term in error_str for net_term in ["timeout", "connection", "network", "dns", "502", "503", "504"]):
        return ErrorType.NETWORK_ERROR

    # Validation errors
    if any(val_term in error_str for val_term in ["validation", "invalid", "bad request", "400"]):
        return ErrorType.VALIDATION_ERROR

    # API errors
    if any(api_term in error_str for api_term in ["api", "500", "internal server error"]):
        return ErrorType.API_ERROR

    return ErrorType.UNKNOWN_ERROR


class RetryHandler:
    """Configurable retry handler with exponential backoff."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        retryable_errors: tuple = (ErrorType.NETWORK_ERROR, ErrorType.API_ERROR),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.retryable_errors = retryable_errors

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(self.max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except HealthDataError as e:
                    last_exception = e

                    # Don't retry non-retryable errors
                    if e.error_type not in self.retryable_errors:
                        raise

                    # Don't retry on last attempt
                    if attempt == self.max_retries:
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(self.base_delay * (self.backoff_factor**attempt), self.max_delay)

                    logger.warning(
                        f"Attempt {attempt + 1} failed, retrying in {delay}s",
                        extra={
                            "attempt": attempt + 1,
                            "max_retries": self.max_retries,
                            "delay": delay,
                            "error": str(e),
                        },
                    )

                    time.sleep(delay)

                except Exception as e:
                    # Convert non-HealthDataError exceptions
                    error_type = _classify_error(e)
                    health_error = HealthDataError(str(e), error_type, original_error=e)
                    last_exception = health_error

                    if error_type not in self.retryable_errors or attempt == self.max_retries:
                        raise health_error

                    delay = min(self.base_delay * (self.backoff_factor**attempt), self.max_delay)

                    logger.warning(
                        f"Attempt {attempt + 1} failed, retrying in {delay}s",
                        extra={
                            "attempt": attempt + 1,
                            "max_retries": self.max_retries,
                            "delay": delay,
                            "error": str(e),
                        },
                    )

                    time.sleep(delay)

            # This should never be reached, but just in case
            raise last_exception or Exception("Retry handler failed unexpectedly")

        return wrapper


# Predefined retry handlers
default_retry = RetryHandler()
aggressive_retry = RetryHandler(max_retries=5, base_delay=0.5)
conservative_retry = RetryHandler(max_retries=2, base_delay=2.0)
