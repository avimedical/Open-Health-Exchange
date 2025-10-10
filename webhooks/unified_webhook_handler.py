"""
Modern unified webhook handlers - Provider-agnostic, type-safe
Replaces separate provider webhook handlers with unified operations
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ingestors.health_data_constants import Provider
from ingestors.health_data_tasks import sync_user_health_data_realtime
from .processors import WebhookPayloadProcessor, WebhookValidationError
from .validators import WebhookSignatureValidator

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class WebhookQuery:
    """Immutable webhook query for batch operations"""
    provider: Provider
    request_method: str
    payload: Dict[str, Any] | None
    request: HttpRequest

    @property
    def cache_key(self) -> str:
        """Generate cache key for this webhook query"""
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        return f"webhook:{self.provider.value}:{self.request_method}:{timestamp}"


class WebhookMetrics:
    """Simple metrics tracking for webhooks"""

    def __init__(self):
        self.webhook_counts = {}
        self.error_counts = {}

    def increment_webhook(self, provider: str):
        self.webhook_counts[provider] = self.webhook_counts.get(provider, 0) + 1

    def increment_error(self, provider: str):
        self.error_counts[provider] = self.error_counts.get(provider, 0) + 1

    def get_stats(self) -> Dict[str, Any]:
        return {
            'webhook_counts': self.webhook_counts,
            'error_counts': self.error_counts
        }


# Global metrics instance
webhook_metrics = WebhookMetrics()


class UnifiedWebhookHandler:
    """
    Modern webhook handler using unified operations

    All webhook operations go through a single core method for consistency
    Provider-agnostic design using settings configuration
    Unified error handling, signature validation, and task queuing
    """

    def __init__(self) -> None:
        self.config = settings.API_CLIENT_CONFIG
        self.processor = WebhookPayloadProcessor()
        self.validator = WebhookSignatureValidator()
        self.logger = logging.getLogger(__name__)

    def handle_webhook(self, provider: Provider, request: HttpRequest) -> HttpResponse:
        """
        Handle webhook for any provider
        Single source of truth for all webhook processing
        """
        try:
            webhook_metrics.increment_webhook(provider.value)

            # Handle different HTTP methods using match statement
            match request.method:
                case 'GET':
                    return self._handle_verification_request(provider, request)
                case 'HEAD':
                    return self._handle_health_check(provider, request)
                case 'POST':
                    return self._handle_notification_request(provider, request)
                case _:
                    return HttpResponseBadRequest(f"Method {request.method} not allowed")

        except Exception as e:
            self.logger.error(f"Webhook handler error for {provider.value}: {e}")
            webhook_metrics.increment_error(provider.value)
            return HttpResponse("Internal Server Error", status=500)

    def _handle_verification_request(self, provider: Provider, request: HttpRequest) -> HttpResponse:
        """Handle GET verification requests from providers"""
        match provider:
            case Provider.WITHINGS:
                challenge = request.GET.get('challenge')
                if challenge:
                    self.logger.info("Withings webhook verification request received")
                    return HttpResponse(challenge, content_type='text/plain')
                else:
                    return HttpResponseBadRequest("Missing challenge parameter")

            case Provider.FITBIT:
                verify = request.GET.get('verify')
                if verify:
                    self.logger.info("Fitbit webhook verification request received")
                    return HttpResponse(verify, content_type='text/plain', status=204)
                else:
                    return HttpResponseBadRequest("Missing verify parameter")

            case _:
                return HttpResponseBadRequest(f"Unknown provider: {provider.value}")

    def _handle_health_check(self, provider: Provider, request: HttpRequest) -> HttpResponse:
        """Handle HEAD requests for health checks"""
        self.logger.info(f"{provider.value} webhook HEAD request received")
        return HttpResponse(status=200)

    def _handle_notification_request(self, provider: Provider, request: HttpRequest) -> Response:
        """Handle POST notification requests from providers"""
        try:
            # Validate signature first
            if not self._validate_signature(provider, request):
                self.logger.warning(f"Invalid {provider.value} webhook signature")
                webhook_metrics.increment_error(provider.value)
                return HttpResponseForbidden("Invalid signature")

            # Parse and validate payload
            payload = self._parse_request_payload(provider, request)
            if payload is None:
                webhook_metrics.increment_error(provider.value)
                return HttpResponseBadRequest("Invalid JSON payload")

            # Process webhook payload using unified processor
            sync_requests = self._process_webhook_payload(provider, payload)

            # Queue background sync tasks
            queued_tasks = self._queue_sync_tasks(provider, sync_requests)

            # Return unified success response
            response_data = {
                'status': 'accepted',
                'provider': provider.value,
                'queued_tasks': len(queued_tasks),
                'tasks': queued_tasks,
                'timestamp': datetime.utcnow().isoformat(),
                'message': f'Successfully queued {len(queued_tasks)} health data sync tasks'
            }

            self.logger.info(f"{provider.value} webhook processed successfully: {len(queued_tasks)} tasks queued")
            return Response(response_data, status=status.HTTP_202_ACCEPTED)

        except WebhookValidationError as e:
            self.logger.error(f"Invalid {provider.value} webhook payload: {e}")
            webhook_metrics.increment_error(provider.value)
            return HttpResponseBadRequest(f"Invalid payload: {e}")

        except Exception as e:
            self.logger.error(f"Error processing {provider.value} webhook: {e}")
            webhook_metrics.increment_error(provider.value)
            return HttpResponse("Internal Server Error", status=500)

    def _validate_signature(self, provider: Provider, request: HttpRequest) -> bool:
        """Validate webhook signature using provider-specific method"""
        match provider:
            case Provider.WITHINGS:
                return self.validator.validate_withings_signature(request)
            case Provider.FITBIT:
                return self.validator.validate_fitbit_signature(request)
            case _:
                self.logger.error(f"No signature validation for provider: {provider.value}")
                return False

    def _parse_request_payload(self, provider: Provider, request: HttpRequest) -> Dict[str, Any] | List[Dict[str, Any]] | None:
        """Parse request body into JSON payload"""
        try:
            body_content = request.body.decode('utf-8') if request.body else ''
            self.logger.debug(f"{provider.value} webhook body content: {body_content[:200]}...")

            if not body_content.strip():
                self.logger.warning(f"{provider.value} webhook received empty body")
                return None

            return json.loads(body_content)

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in {provider.value} webhook: {e}")
            self.logger.error(f"Raw body content: {request.body[:500]}")
            return None

    def _process_webhook_payload(self, provider: Provider, payload: Any) -> List[Dict[str, Any]]:
        """Process webhook payload using provider-specific processor method"""
        match provider:
            case Provider.WITHINGS:
                return self.processor.process_withings_webhook(payload)
            case Provider.FITBIT:
                return self.processor.process_fitbit_webhook(payload)
            case _:
                raise WebhookValidationError(f"No processor for provider: {provider.value}")

    def _queue_sync_tasks(self, provider: Provider, sync_requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Queue background sync tasks for webhook notifications"""
        queued_tasks = []

        for sync_request in sync_requests:
            try:
                task_result = sync_user_health_data_realtime.delay(
                    user_id=sync_request['user_id'],
                    provider_name=sync_request['provider'],
                    data_types=sync_request['data_types'],
                    trigger_type='webhook',
                    date_range=sync_request.get('date_range')
                )

                queued_tasks.append({
                    'task_id': task_result.id,
                    'user_id': sync_request['user_id'],
                    'data_types': sync_request['data_types']
                })

                self.logger.info(f"Queued {provider.value} sync task {task_result.id} for user {sync_request['user_id']}")

            except Exception as e:
                self.logger.error(f"Failed to queue {provider.value} sync task: {e}")
                webhook_metrics.increment_error(provider.value)

        return queued_tasks

    def get_webhook_stats(self) -> Dict[str, Any]:
        """Get webhook handler statistics"""
        return {
            'supported_providers': [Provider.WITHINGS.value, Provider.FITBIT.value],
            'metrics': webhook_metrics.get_stats()
        }


# Global service instance
_unified_handler: UnifiedWebhookHandler | None = None


def get_unified_webhook_handler() -> UnifiedWebhookHandler:
    """Lazy singleton for global webhook handler instance"""
    global _unified_handler
    if _unified_handler is None:
        _unified_handler = UnifiedWebhookHandler()
    return _unified_handler


# Provider-specific endpoint functions that delegate to unified handler
@csrf_exempt
@require_http_methods(["POST", "GET", "HEAD"])
@api_view(['POST', 'GET', 'HEAD'])
@permission_classes([AllowAny])
def withings_webhook_handler(request):
    """
    Unified Withings webhook handler
    Delegates to UnifiedWebhookHandler for consistent processing
    """
    handler = get_unified_webhook_handler()
    return handler.handle_webhook(Provider.WITHINGS, request)


@csrf_exempt
@require_http_methods(["POST", "GET", "HEAD"])
@api_view(['POST', 'GET', 'HEAD'])
@permission_classes([AllowAny])
def fitbit_webhook_handler(request):
    """
    Unified Fitbit webhook handler
    Delegates to UnifiedWebhookHandler for consistent processing
    """
    handler = get_unified_webhook_handler()
    return handler.handle_webhook(Provider.FITBIT, request)


@csrf_exempt
def webhook_health_check(request):
    """Health check endpoint for webhook infrastructure"""
    handler = get_unified_webhook_handler()
    stats = handler.get_webhook_stats()

    response_data = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'webhook_system': stats
    }

    return HttpResponse(
        json.dumps(response_data, indent=2),
        content_type='application/json'
    )


@csrf_exempt
def webhook_metrics_endpoint(request):
    """Metrics endpoint for webhook monitoring"""
    stats = webhook_metrics.get_stats()

    response_data = {
        'webhook_metrics': stats,
        'timestamp': datetime.utcnow().isoformat()
    }

    return HttpResponse(
        json.dumps(response_data, indent=2),
        content_type='application/json'
    )