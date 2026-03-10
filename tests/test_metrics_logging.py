"""
Tests for structured JSON logging formatter.
"""

import json
import logging

import pytest

from metrics.logging import JsonFormatter


class TestJsonFormatter:
    """Tests for JsonFormatter class."""

    @pytest.fixture
    def formatter(self):
        """Create JsonFormatter instance."""
        return JsonFormatter()

    @pytest.fixture
    def logger(self):
        """Create a logger for testing."""
        test_logger = logging.getLogger("test_json_formatter")
        test_logger.setLevel(logging.DEBUG)
        return test_logger

    def test_formats_basic_log_record(self, formatter, logger):
        """Test formats basic log record as JSON."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test_logger"
        assert parsed["message"] == "Test message"
        assert "timestamp" in parsed
        assert parsed["timestamp"].endswith("Z")

    def test_includes_module_info(self, formatter, logger):
        """Test includes module information."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.DEBUG,
            fn="my_module.py",
            lno=42,
            msg="Debug message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "module" in parsed
        assert parsed["line_number"] == 42
        assert "function_name" in parsed

    def test_includes_process_and_thread_ids(self, formatter, logger):
        """Test includes process and thread IDs."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "process_id" in parsed
        assert "thread_id" in parsed
        assert parsed["process_id"] is not None
        assert parsed["thread_id"] is not None

    def test_includes_user_id_when_present(self, formatter, logger):
        """Test includes user_id when set on record."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="User action",
            args=(),
            exc_info=None,
        )
        record.user_id = "user-123"

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["user_id"] == "user-123"

    def test_includes_provider_when_present(self, formatter, logger):
        """Test includes provider when set on record."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Provider sync",
            args=(),
            exc_info=None,
        )
        record.provider = "withings"

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["provider"] == "withings"

    def test_includes_operation_when_present(self, formatter, logger):
        """Test includes operation when set on record."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Sync operation",
            args=(),
            exc_info=None,
        )
        record.operation = "fetch_health_data"

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["operation"] == "fetch_health_data"

    def test_includes_duration_when_present(self, formatter, logger):
        """Test includes duration when set on record."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Request completed",
            args=(),
            exc_info=None,
        )
        record.duration = 0.125

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["duration"] == 0.125

    def test_includes_status_code_when_present(self, formatter, logger):
        """Test includes status_code when set on record."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="API response",
            args=(),
            exc_info=None,
        )
        record.status_code = 200

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["status_code"] == 200

    def test_includes_request_id_when_present(self, formatter, logger):
        """Test includes request_id when set on record."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Processing request",
            args=(),
            exc_info=None,
        )
        record.request_id = "req-abc-123"

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["request_id"] == "req-abc-123"

    def test_includes_exception_details(self, formatter, logger):
        """Test includes exception details when present."""
        try:
            raise ValueError("Test error message")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logger.makeRecord(
            name="test_logger",
            level=logging.ERROR,
            fn="test.py",
            lno=1,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "exception" in parsed
        assert parsed["exception"]["type"] == "ValueError"
        assert parsed["exception"]["message"] == "Test error message"
        assert isinstance(parsed["exception"]["traceback"], list)
        assert len(parsed["exception"]["traceback"]) > 0

    def test_handles_message_with_args(self, formatter, logger):
        """Test handles message with format arguments."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="User %s performed %s",
            args=("user-123", "sync"),
            exc_info=None,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["message"] == "User user-123 performed sync"

    def test_handles_unicode_characters(self, formatter, logger):
        """Test handles unicode characters in message."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="User performed action: \u00e9\u00e8\u00ea",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "\u00e9\u00e8\u00ea" in parsed["message"]

    def test_all_log_levels(self, formatter, logger):
        """Test all log levels are correctly formatted."""
        levels = [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]

        for level_int, level_str in levels:
            record = logger.makeRecord(
                name="test_logger",
                level=level_int,
                fn="test.py",
                lno=1,
                msg="Test message",
                args=(),
                exc_info=None,
            )

            result = formatter.format(record)
            parsed = json.loads(result)

            assert parsed["level"] == level_str

    def test_returns_valid_json_string(self, formatter, logger):
        """Test returns a valid JSON string."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        # Should be a string
        assert isinstance(result, str)
        # Should be valid JSON
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_multiple_extra_fields(self, formatter, logger):
        """Test with multiple extra fields set."""
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Complex request",
            args=(),
            exc_info=None,
        )
        record.user_id = "user-456"
        record.provider = "fitbit"
        record.operation = "sync_health_data"
        record.duration = 1.5
        record.status_code = 200
        record.request_id = "req-xyz-789"

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["user_id"] == "user-456"
        assert parsed["provider"] == "fitbit"
        assert parsed["operation"] == "sync_health_data"
        assert parsed["duration"] == 1.5
        assert parsed["status_code"] == 200
        assert parsed["request_id"] == "req-xyz-789"
