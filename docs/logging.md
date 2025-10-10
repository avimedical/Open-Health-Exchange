# Logging

Open Health Exchange uses Python's standard logging configured through Django settings for structured, leveled output.

## Current State

- Root logger level: INFO (development can elevate to DEBUG via DJANGO_LOG_LEVEL)
- Structured JSON logging (*Planned* for production) – current output is plain text unless LOG_JSON=true is set
- Separate loggers per app: `base`, `ingestors`, `publishers`, `transformers`, `metrics`
- Huey task logging inherits from root logger

## Configuration Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DJANGO_LOG_LEVEL | Minimum log level (DEBUG, INFO, WARNING, ERROR) | INFO |
| LOG_JSON | Enable JSON formatting (*Planned* default for prod) | False |
| LOG_SLOW_QUERY_THRESHOLD_MS | If set, logs DB queries slower than threshold | (unset) |

## Adding a Logger

```python
import logging
logger = logging.getLogger(__name__)

def example():
    logger.info("Starting example operation", extra={"operation": "example"})
```

## Correlation IDs (*Planned*)

Future production deployments will inject a `correlation_id` per request (via middleware) cascaded to Huey tasks for traceability.

## Huey Task Logging

Huey tasks automatically inherit the project logging configuration. Run the worker in verbose mode during development:

```
python manage.py run_huey -V
```

## Recommended Next Steps (*Planned*)

1. Implement request ID middleware
2. Switch default prod formatter to JSON
3. Add log shipping (e.g., OpenTelemetry / Loki)
4. Define PII scrubbing filters for provider payloads
