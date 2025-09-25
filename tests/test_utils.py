"""
Unified test utilities - Eliminates Django setup duplication across all test files
Provides common test infrastructure and utilities
"""
import os
import sys
import logging
import django
from pathlib import Path


def setup_django_for_tests(log_level: int = logging.INFO) -> None:
    """
    Unified Django setup for all test files

    Eliminates the duplication of Django setup code across 26+ test files

    Args:
        log_level: Logging level for test execution
    """
    # Add project root to path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))

    # Configure Django settings
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'open_health_exchange.settings')
    django.setup()

    # Configure logging for tests
    logging.basicConfig(
        level=log_level,
        format='%(levelname)s %(asctime)s %(name)s %(message)s',
        force=True  # Override any existing logging configuration
    )


def get_test_logger(name: str) -> logging.Logger:
    """Get a logger configured for test output"""
    return logging.getLogger(f"test.{name}")


class TestMetrics:
    """Simple test metrics for tracking test execution"""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.start_time = None
        self.operations = []
        self.logger = get_test_logger(test_name)

    def start(self):
        """Start test metrics collection"""
        import time
        self.start_time = time.time()
        self.logger.info(f"🧪 Starting {self.test_name}")

    def operation(self, operation_name: str, status: str = "✅"):
        """Record a test operation"""
        self.operations.append({
            'operation': operation_name,
            'status': status
        })
        self.logger.info(f"{status} {operation_name}")

    def finish(self, success: bool = True) -> float:
        """Finish test and return duration"""
        import time
        if self.start_time:
            duration = time.time() - self.start_time
            status = "✅" if success else "❌"
            self.logger.info(f"{status} {self.test_name} completed in {duration:.2f}s")
            return duration
        return 0.0

    def summary(self):
        """Print test summary"""
        successful = len([op for op in self.operations if op['status'] == "✅"])
        total = len(self.operations)
        self.logger.info(f"📊 Test Summary: {successful}/{total} operations successful")


def run_test_with_django(test_function, test_name: str = None, log_level: int = logging.INFO):
    """
    Unified test runner that handles Django setup and metrics

    Args:
        test_function: The test function to execute
        test_name: Name of the test (defaults to function name)
        log_level: Logging level

    Returns:
        bool: Test success status
    """
    # Setup Django
    setup_django_for_tests(log_level)

    # Initialize metrics
    name = test_name or test_function.__name__
    metrics = TestMetrics(name)
    metrics.start()

    try:
        # Run the test
        result = test_function()
        success = result if isinstance(result, bool) else True

        duration = metrics.finish(success)
        metrics.summary()

        if success:
            print(f"\n✅ {name} completed successfully in {duration:.2f}s")
        else:
            print(f"\n❌ {name} failed after {duration:.2f}s")

        return success

    except Exception as e:
        duration = metrics.finish(False)
        print(f"\n❌ {name} failed after {duration:.2f}s: {e}")
        import traceback
        traceback.print_exc()
        return False


# Common test data factories
class TestDataFactory:
    """Factory for creating common test data objects"""

    @staticmethod
    def create_date_range():
        """Create a standard test date range"""
        from datetime import datetime, timezone
        from ingestors.health_data_constants import DateRange

        return DateRange(
            start=datetime(2024, 9, 1, tzinfo=timezone.utc),
            end=datetime(2024, 9, 25, tzinfo=timezone.utc)
        )

    @staticmethod
    def create_test_user_id() -> str:
        """Create a standard test user ID"""
        return "test-user-123"

    @staticmethod
    def create_test_device_id() -> str:
        """Create a standard test device ID"""
        import uuid
        return f"test-device-{uuid.uuid4().hex[:8]}"


# Common assertions
def assert_cache_key_format(cache_key: str, expected_prefix: str, expected_parts: int = None):
    """Assert cache key follows expected format"""
    assert cache_key.startswith(expected_prefix), f"Cache key should start with {expected_prefix}, got: {cache_key}"

    if expected_parts:
        parts = cache_key.split(':')
        assert len(parts) == expected_parts, f"Cache key should have {expected_parts} parts, got {len(parts)}: {cache_key}"


def assert_singleton_pattern(factory_function):
    """Assert that a factory function returns the same instance (singleton pattern)"""
    instance1 = factory_function()
    instance2 = factory_function()
    assert instance1 is instance2, "Singleton pattern not working - different instances returned"


def assert_dataclass_immutable(dataclass_instance):
    """Assert that a dataclass is frozen (immutable)"""
    import dataclasses
    assert dataclasses.is_dataclass(dataclass_instance), "Object is not a dataclass"

    # Try to modify a field - should raise FrozenInstanceError
    try:
        if hasattr(dataclass_instance, '__dataclass_fields__'):
            field_name = next(iter(dataclass_instance.__dataclass_fields__.keys()))
            setattr(dataclass_instance, field_name, 'modified')
            assert False, "Dataclass should be frozen but allowed modification"
    except (AttributeError, dataclasses.FrozenInstanceError):
        pass  # Expected behavior for frozen dataclass


# Test configuration constants
TEST_CONFIG = {
    'DEFAULT_TIMEOUT': 5.0,
    'DEFAULT_BATCH_SIZE': 10,
    'MOCK_USER_ID': 'test-user-123',
    'MOCK_DEVICE_ID': 'test-device-456',
    'EXPECTED_PROVIDERS': ['withings', 'fitbit'],
    'EXPECTED_CACHE_PREFIXES': {
        'device_mapping': 'device_mapping',
        'health_data': 'health_data',
        'webhook': 'webhook',
        'health_manager': 'health_manager'
    }
}