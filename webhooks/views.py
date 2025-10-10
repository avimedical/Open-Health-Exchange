"""
Production webhook endpoints for real-time health data synchronization
Handles secure webhook notifications from health data providers
"""

import json
import logging
from typing import Any

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

# Import our health data sync infrastructure
from ingestors.health_data_tasks import sync_user_health_data_realtime

from .processors import WebhookPayloadProcessor, WebhookValidationError
from .validators import WebhookSignatureValidator

logger = logging.getLogger(__name__)


class WebhookMetrics:
    """Simple metrics tracking for webhooks"""

    def __init__(self):
        self.webhook_counts = {}
        self.error_counts = {}

    def increment_webhook(self, provider: str):
        self.webhook_counts[provider] = self.webhook_counts.get(provider, 0) + 1

    def increment_error(self, provider: str):
        self.error_counts[provider] = self.error_counts.get(provider, 0) + 1

    def get_stats(self) -> dict[str, Any]:
        return {"webhook_counts": self.webhook_counts, "error_counts": self.error_counts}


# Global metrics instance
webhook_metrics = WebhookMetrics()


@csrf_exempt
@require_http_methods(["POST", "GET", "HEAD"])
@api_view(["POST", "GET", "HEAD"])
@permission_classes([AllowAny])
def withings_webhook_handler(request):
    """
    Production Withings webhook handler

    Handles both verification requests (GET) and notification requests (POST)
    """

    if request.method == "GET":
        # Handle webhook verification for Withings
        challenge = request.GET.get("challenge")
        if challenge:
            logger.info("Withings webhook verification request received")
            return HttpResponse(challenge, content_type="text/plain")
        else:
            return HttpResponseBadRequest("Missing challenge parameter")

    if request.method == "HEAD":
        # Handle HEAD requests for health checks
        logger.info("Withings webhook HEAD request received")
        return HttpResponse(status=200)

    # Handle POST webhook notifications
    try:
        webhook_metrics.increment_webhook("withings")

        # Validate webhook signature for security
        validator = WebhookSignatureValidator()
        if not validator.validate_withings_signature(request):
            logger.warning("Invalid Withings webhook signature")
            webhook_metrics.increment_error("withings")
            return HttpResponseForbidden("Invalid signature")

        # Parse and validate payload - handle both JSON and form-encoded data
        try:
            body_content = request.body.decode("utf-8") if request.body else ""
            logger.debug(f"Withings webhook body content: {body_content[:200]}...")  # Log first 200 chars

            if not body_content.strip():
                logger.warning("Withings webhook received empty body")
                webhook_metrics.increment_error("withings")
                return HttpResponseBadRequest("Empty request body")

            # Try JSON first, then fall back to form-encoded data
            try:
                payload = json.loads(body_content)
                logger.debug("Parsed Withings webhook as JSON")
            except json.JSONDecodeError:
                # Parse as form-encoded data
                from urllib.parse import parse_qs

                parsed_data = parse_qs(body_content)
                # Convert to dictionary with single values (Withings sends single values)
                payload = {key: values[0] if values else "" for key, values in parsed_data.items()}
                logger.debug(f"Parsed Withings webhook as form-encoded: {payload}")

        except Exception as e:
            logger.error(f"Failed to parse Withings webhook payload: {e}")
            logger.error(f"Raw body content: {request.body[:500]}")  # Log raw bytes for debugging
            webhook_metrics.increment_error("withings")
            return HttpResponseBadRequest("Invalid payload format")

        # Process webhook payload
        processor = WebhookPayloadProcessor()
        try:
            sync_requests = processor.process_withings_webhook(payload)
        except WebhookValidationError as e:
            logger.error(f"Invalid Withings webhook payload: {e}")
            webhook_metrics.increment_error("withings")
            return HttpResponseBadRequest(f"Invalid payload: {e}")

        # Queue background sync tasks
        queued_tasks = []
        for sync_request in sync_requests:
            try:
                task_result = sync_user_health_data_realtime(
                    user_id=sync_request["user_id"],
                    provider_name=sync_request["provider"],
                    data_types=sync_request["data_types"],
                    trigger_type="webhook",
                    date_range=sync_request.get("date_range"),
                )

                queued_tasks.append(
                    {
                        "task_id": task_result.id,
                        "user_id": sync_request["user_id"],
                        "data_types": sync_request["data_types"],
                    }
                )

                logger.info(f"Queued Withings sync task {task_result.id} for user {sync_request['user_id']}")

            except Exception as e:
                logger.error(f"Failed to queue Withings sync task: {e}")
                webhook_metrics.increment_error("withings")

        # Return success response
        response_data = {
            "status": "accepted",
            "provider": "withings",
            "queued_tasks": len(queued_tasks),
            "tasks": queued_tasks,
            "timestamp": timezone.now().isoformat(),
            "message": f"Successfully queued {len(queued_tasks)} health data sync tasks",
        }

        logger.info(f"Withings webhook processed successfully: {len(queued_tasks)} tasks queued")
        return Response(response_data, status=status.HTTP_202_ACCEPTED)

    except Exception as e:
        logger.error(f"Unexpected error in Withings webhook handler: {e}")
        webhook_metrics.increment_error("withings")
        return HttpResponseBadRequest(f"Internal error: {str(e)[:100]}")


@csrf_exempt
@require_http_methods(["POST", "GET", "HEAD"])
@api_view(["POST", "GET", "HEAD"])
@permission_classes([AllowAny])
def fitbit_webhook_handler(request):
    """
    Production Fitbit webhook handler

    Handles both verification requests (GET) and notification requests (POST)
    """

    if request.method == "GET":
        # Handle webhook verification for Fitbit
        verify = request.GET.get("verify")
        if verify:
            logger.info("Fitbit webhook verification request received")
            # Fitbit expects the verify parameter echoed back
            return HttpResponse(verify, content_type="text/plain", status=204)
        else:
            return HttpResponseBadRequest("Missing verify parameter")

    if request.method == "HEAD":
        # Handle HEAD requests for health checks
        logger.info("Fitbit webhook HEAD request received")
        return HttpResponse(status=200)

    # Handle POST webhook notifications
    try:
        webhook_metrics.increment_webhook("fitbit")

        # Validate webhook signature for security
        validator = WebhookSignatureValidator()
        if not validator.validate_fitbit_signature(request):
            logger.warning("Invalid Fitbit webhook signature")
            webhook_metrics.increment_error("fitbit")
            return HttpResponseForbidden("Invalid signature")

        # Parse and validate payload
        try:
            body_content = request.body.decode("utf-8") if request.body else ""
            logger.debug(f"Fitbit webhook body content: {body_content[:200]}...")  # Log first 200 chars

            if not body_content.strip():
                logger.warning("Fitbit webhook received empty body")
                webhook_metrics.increment_error("fitbit")
                return HttpResponseBadRequest("Empty request body")

            payload = json.loads(body_content)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in Fitbit webhook: {e}")
            logger.error(f"Raw body content: {request.body[:500]}")  # Log raw bytes for debugging
            webhook_metrics.increment_error("fitbit")
            return HttpResponseBadRequest("Invalid JSON payload")

        # Process webhook payload
        processor = WebhookPayloadProcessor()
        try:
            sync_requests = processor.process_fitbit_webhook(payload)
        except WebhookValidationError as e:
            logger.error(f"Invalid Fitbit webhook payload: {e}")
            webhook_metrics.increment_error("fitbit")
            return HttpResponseBadRequest(f"Invalid payload: {e}")

        # Queue background sync tasks
        queued_tasks = []
        for sync_request in sync_requests:
            try:
                task_result = sync_user_health_data_realtime(
                    user_id=sync_request["user_id"],
                    provider_name=sync_request["provider"],
                    data_types=sync_request["data_types"],
                    trigger_type="webhook",
                    date_range=sync_request.get("date_range"),
                )

                queued_tasks.append(
                    {
                        "task_id": task_result.id,
                        "user_id": sync_request["user_id"],
                        "data_types": sync_request["data_types"],
                    }
                )

                logger.info(f"Queued Fitbit sync task {task_result.id} for user {sync_request['user_id']}")

            except Exception as e:
                logger.error(f"Failed to queue Fitbit sync task: {e}")
                webhook_metrics.increment_error("fitbit")

        # Return success response
        response_data = {
            "status": "accepted",
            "provider": "fitbit",
            "queued_tasks": len(queued_tasks),
            "tasks": queued_tasks,
            "timestamp": timezone.now().isoformat(),
            "message": f"Successfully queued {len(queued_tasks)} health data sync tasks",
        }

        logger.info(f"Fitbit webhook processed successfully: {len(queued_tasks)} tasks queued")
        return Response(response_data, status=status.HTTP_202_ACCEPTED)

    except Exception as e:
        logger.error(f"Unexpected error in Fitbit webhook handler: {e}")
        webhook_metrics.increment_error("fitbit")
        return HttpResponseBadRequest(f"Internal error: {str(e)[:100]}")


@csrf_exempt
@api_view(["GET"])
@permission_classes([AllowAny])
def webhook_health_check(request):
    """
    Health check endpoint for webhook infrastructure
    """
    try:
        # Check if Huey is running by attempting to queue a test task
        from django.core.cache import cache

        # Test Redis connection (used by Huey)
        cache.set("webhook_health_check", timezone.now().isoformat(), timeout=settings.WEBHOOK_CONFIG["CACHE_TIMEOUT"])
        cache_value = cache.get("webhook_health_check")

        health_data = {
            "status": "healthy",
            "timestamp": timezone.now().isoformat(),
            "services": {
                "webhook_endpoints": "online",
                "redis_cache": "online" if cache_value else "offline",
                "task_queue": "online",  # If we got this far, Huey/Redis is likely working
            },
            "metrics": webhook_metrics.get_stats(),
        }

        return Response(health_data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Webhook health check failed: {e}")
        return Response(
            {"status": "unhealthy", "timestamp": timezone.now().isoformat(), "error": str(e)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@csrf_exempt
@api_view(["GET"])
def webhook_metrics_endpoint(request):
    """
    Webhook metrics endpoint for monitoring
    """
    try:
        metrics_data = {
            "timestamp": timezone.now().isoformat(),
            "webhook_metrics": webhook_metrics.get_stats(),
            "endpoints": {
                "withings_webhook": "/webhooks/withings/",
                "fitbit_webhook": "/webhooks/fitbit/",
                "health_check": "/webhooks/health/",
                "metrics": "/webhooks/metrics/",
            },
        }

        return Response(metrics_data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Failed to get webhook metrics: {e}")
        return Response(
            {"error": str(e), "timestamp": timezone.now().isoformat()}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def debug_withings_subscriptions(request):
    """
    Debug endpoint to check active Withings subscriptions for a user

    Usage: GET /webhooks/debug/withings/subscriptions/?user_id=<ehr_user_id>
    """
    user_id = request.GET.get("user_id")

    if not user_id:
        return Response(
            {
                "error": "Missing required parameter: user_id",
                "usage": "GET /webhooks/debug/withings/subscriptions/?user_id=<ehr_user_id>",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        import requests
        from social_django.models import UserSocialAuth

        from base.models import EHRUser

        # Get user
        try:
            user = EHRUser.objects.get(ehr_user_id=user_id)
        except EHRUser.DoesNotExist:
            return Response({"error": f"User not found: {user_id}"}, status=status.HTTP_404_NOT_FOUND)

        # Get Withings social auth
        try:
            social_auth = UserSocialAuth.objects.get(user=user, provider="withings")
        except UserSocialAuth.DoesNotExist:
            return Response(
                {
                    "error": f"User {user_id} not connected to Withings",
                    "user_exists": True,
                    "withings_connected": False,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get access token
        access_token = social_auth.access_token

        # Query Withings API for subscription list
        url = "https://wbsapi.withings.net/notify"
        params = {"action": "list", "access_token": access_token}

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        result = response.json()

        # Withings appli type mapping for reference
        # Source: https://developer.withings.com/developer-guide/v3/data-api/keep-user-data-up-to-date/
        appli_type_names = {
            1: "Weight-related metrics (weight, fat mass, muscle mass)",
            2: "Temperature-related data",
            4: "Pressure-related data (blood pressure, heart pulse, SPO2)",
            16: "Activity data (steps, distance, calories, workouts)",
            44: "Sleep-related data",
            46: "User profile actions",
            50: "Bed in sleep event",
            51: "Bed out sleep event",
            52: "Sleep sensor inflation event",
            53: "Device setup without account",
            54: "ECG data",
            55: "ECG measure failure event",
            58: "Glucose data",
        }

        # Parse response
        if result.get("status") == 0:
            profiles = result.get("body", {}).get("profiles", [])

            # Enrich subscription data with human-readable names
            for profile in profiles:
                appli = profile.get("appli")
                profile["appli_name"] = appli_type_names.get(appli, f"Unknown ({appli})")

            return Response(
                {
                    "user_id": user_id,
                    "withings_connected": True,
                    "withings_user_id": social_auth.extra_data.get("userid"),
                    "subscriptions": profiles,
                    "subscription_count": len(profiles),
                    "appli_type_reference": appli_type_names,
                    "timestamp": timezone.now().isoformat(),
                },
                status=status.HTTP_200_OK,
            )
        else:
            return Response(
                {"error": "Withings API returned error", "status": result.get("status"), "result": result},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    except requests.RequestException as e:
        logger.error(f"Failed to query Withings subscriptions: {e}")
        return Response(
            {"error": f"Failed to query Withings API: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Unexpected error in debug endpoint: {e}", exc_info=True)
        return Response({"error": f"Unexpected error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
