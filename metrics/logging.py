"""
Structured JSON logging formatter for production environments.
"""

import json
import logging
import traceback
from datetime import datetime
from typing import Any

from django.utils import timezone


class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "message": record.getMessage(),
            "process_id": record.process,
            "thread_id": record.thread,
            "pathname": record.pathname,
            "line_number": record.lineno,
            "function_name": record.funcName,
        }

        # Add extra fields if present
        if hasattr(record, "user_id"):
            log_entry["user_id"] = record.user_id

        if hasattr(record, "provider"):
            log_entry["provider"] = record.provider

        if hasattr(record, "operation"):
            log_entry["operation"] = record.operation

        if hasattr(record, "duration"):
            log_entry["duration"] = record.duration

        if hasattr(record, "status_code"):
            log_entry["status_code"] = record.status_code

        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id

        # Add exception details if present
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            log_entry["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "traceback": traceback.format_exception(exc_type, exc_value, exc_traceback),
            }

        return json.dumps(log_entry, ensure_ascii=False)
