"""
Prometheus metrics collectors for Open Health Exchange.
"""
import time
from typing import Dict, Any, Optional
from prometheus_client import Counter, Histogram, Gauge, Info, CollectorRegistry, REGISTRY
from django.db import connection
from django.core.cache import cache
import redis
import logging

logger = logging.getLogger(__name__)

# Custom registry for application metrics
app_registry = CollectorRegistry()

# Health data sync metrics
SYNC_OPERATIONS_TOTAL = Counter(
    'ohe_sync_operations_total',
    'Total number of health data sync operations',
    ['provider', 'operation_type', 'status'],
    registry=app_registry
)

SYNC_DURATION = Histogram(
    'ohe_sync_duration_seconds',
    'Time spent on health data sync operations',
    ['provider', 'operation_type'],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
    registry=app_registry
)

DATA_POINTS_PROCESSED = Counter(
    'ohe_data_points_processed_total',
    'Total number of health data points processed',
    ['provider', 'data_type'],
    registry=app_registry
)

# FHIR operations metrics
FHIR_OPERATIONS_TOTAL = Counter(
    'ohe_fhir_operations_total',
    'Total number of FHIR server operations',
    ['operation', 'resource_type', 'status'],
    registry=app_registry
)

FHIR_RESPONSE_TIME = Histogram(
    'ohe_fhir_response_time_seconds',
    'FHIR server response times',
    ['operation', 'resource_type'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=app_registry
)

# API metrics
API_REQUESTS_TOTAL = Counter(
    'ohe_api_requests_total',
    'Total number of API requests',
    ['method', 'endpoint', 'status_code'],
    registry=app_registry
)

API_REQUEST_DURATION = Histogram(
    'ohe_api_request_duration_seconds',
    'API request duration',
    ['method', 'endpoint'],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
    registry=app_registry
)

# Webhook metrics
WEBHOOK_REQUESTS_TOTAL = Counter(
    'ohe_webhook_requests_total',
    'Total number of webhook requests received',
    ['provider', 'status'],
    registry=app_registry
)

WEBHOOK_PROCESSING_TIME = Histogram(
    'ohe_webhook_processing_time_seconds',
    'Webhook processing time',
    ['provider'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
    registry=app_registry
)

# System health metrics
DATABASE_CONNECTIONS = Gauge(
    'ohe_database_connections',
    'Number of active database connections',
    registry=app_registry
)

REDIS_CONNECTIONS = Gauge(
    'ohe_redis_connections',
    'Number of active Redis connections',
    registry=app_registry
)

HUEY_QUEUE_SIZE = Gauge(
    'ohe_huey_queue_size',
    'Number of tasks in Huey queue',
    registry=app_registry
)

# Provider API health metrics
PROVIDER_API_ERRORS = Counter(
    'ohe_provider_api_errors_total',
    'Total number of provider API errors',
    ['provider', 'error_type'],
    registry=app_registry
)

PROVIDER_API_RATE_LIMITS = Counter(
    'ohe_provider_api_rate_limits_total',
    'Total number of provider API rate limit hits',
    ['provider'],
    registry=app_registry
)

# Application info
APPLICATION_INFO = Info(
    'ohe_application_info',
    'Application information',
    registry=app_registry
)


class MetricsCollector:
    """Centralized metrics collection."""

    def __init__(self):
        self.start_time = time.time()

    def record_sync_operation(self, provider: str, operation_type: str, status: str, duration: Optional[float] = None):
        """Record a health data sync operation."""
        SYNC_OPERATIONS_TOTAL.labels(
            provider=provider,
            operation_type=operation_type,
            status=status
        ).inc()

        if duration:
            SYNC_DURATION.labels(
                provider=provider,
                operation_type=operation_type
            ).observe(duration)

    def record_data_points(self, provider: str, data_type: str, count: int):
        """Record processed data points."""
        DATA_POINTS_PROCESSED.labels(
            provider=provider,
            data_type=data_type
        ).inc(count)

    def record_fhir_operation(self, operation: str, resource_type: str, status: str, duration: Optional[float] = None):
        """Record a FHIR server operation."""
        FHIR_OPERATIONS_TOTAL.labels(
            operation=operation,
            resource_type=resource_type,
            status=status
        ).inc()

        if duration:
            FHIR_RESPONSE_TIME.labels(
                operation=operation,
                resource_type=resource_type
            ).observe(duration)

    def record_api_request(self, method: str, endpoint: str, status_code: int, duration: Optional[float] = None):
        """Record an API request."""
        API_REQUESTS_TOTAL.labels(
            method=method,
            endpoint=endpoint,
            status_code=str(status_code)
        ).inc()

        if duration:
            API_REQUEST_DURATION.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration)

    def record_webhook(self, provider: str, status: str, processing_time: Optional[float] = None):
        """Record a webhook request."""
        WEBHOOK_REQUESTS_TOTAL.labels(
            provider=provider,
            status=status
        ).inc()

        if processing_time:
            WEBHOOK_PROCESSING_TIME.labels(provider=provider).observe(processing_time)

    def record_provider_api_error(self, provider: str, error_type: str):
        """Record a provider API error."""
        PROVIDER_API_ERRORS.labels(
            provider=provider,
            error_type=error_type
        ).inc()

    def record_rate_limit(self, provider: str):
        """Record a rate limit hit."""
        PROVIDER_API_RATE_LIMITS.labels(provider=provider).inc()

    def update_system_metrics(self):
        """Update system health metrics."""
        try:
            # Database connections
            db_connections = len(connection.queries) if hasattr(connection, 'queries') else 0
            DATABASE_CONNECTIONS.set(db_connections)

            # Redis connections (if available)
            try:
                redis_info = cache._cache.get_client().info()
                REDIS_CONNECTIONS.set(redis_info.get('connected_clients', 0))
            except Exception:
                pass

            # Huey queue size (approximation via Redis)
            try:
                from django.conf import settings
                redis_client = redis.Redis(connection_pool=settings.HUEY.storage.conn)
                queue_size = redis_client.llen('huey.default')
                HUEY_QUEUE_SIZE.set(queue_size)
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"Failed to update system metrics: {e}")


# Global metrics collector instance
metrics = MetricsCollector()


def initialize_metrics():
    """Initialize application metrics."""
    try:
        from django.conf import settings

        # Set application info
        APPLICATION_INFO.info({
            'version': getattr(settings, 'APPLICATION_VERSION', 'unknown'),
            'environment': getattr(settings, 'ENVIRONMENT', 'development'),
            'debug': str(getattr(settings, 'DEBUG', False)),
        })

        logger.info("Metrics collection initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize metrics: {e}")


def get_registry():
    """Get the metrics registry."""
    return app_registry