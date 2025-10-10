import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from base.models import EHRUser, Provider, ProviderLink
from base.serializers import (
    DeviceSyncRequestSerializer,
    DeviceSyncResultSerializer,
    HealthDataCapabilitiesSerializer,
    ProviderLinkSerializer,
    ProviderSerializer,
)

logger = logging.getLogger(__name__)


class ProviderViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing health data providers.
    Provides list and detail views for available providers.
    """

    queryset = Provider.objects.filter(active=True)
    serializer_class = ProviderSerializer
    permission_classes = [AllowAny]  # Public information
    throttle_classes = [UserRateThrottle, AnonRateThrottle]

    @action(detail=False, methods=["get"])
    def capabilities(self, request):
        """Get health data capabilities and supported features"""
        capabilities_data = {
            "supported_providers": ["withings", "fitbit"],
            "supported_data_types": ["heart_rate", "steps", "rr_intervals", "ecg", "blood_pressure", "weight"],
            "webhook_endpoints": {"withings": "/webhooks/withings/", "fitbit": "/webhooks/fitbit/"},
            "sync_frequencies": {
                "real_time": "Webhook-triggered (immediate)",
                "daily": "Daily at 06:00 UTC",
                "weekly": "Weekly on Sundays at 06:00 UTC",
            },
        }
        serializer = HealthDataCapabilitiesSerializer(capabilities_data)
        return Response(serializer.data)


class HealthSyncViewSet(viewsets.ViewSet):
    """
    ViewSet for health data synchronization operations.
    Provides status checking and sync management.
    """

    permission_classes = [AllowAny]  # Will validate EHR user in action methods
    throttle_classes = [UserRateThrottle, AnonRateThrottle]

    @action(detail=False, methods=["get"])
    def status(self, request):
        """Get synchronization status for a user and provider"""
        ehr_user_id = request.query_params.get("ehr_user_id")
        provider = request.query_params.get("provider")

        if not ehr_user_id:
            return Response({"error": "ehr_user_id parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            EHRUser.objects.get(ehr_user_id=ehr_user_id)
        except EHRUser.DoesNotExist:
            return Response({"error": f"User {ehr_user_id} not found"}, status=status.HTTP_404_NOT_FOUND)

        if provider:
            # Get status for specific provider
            cache_key = f"sync_status:{ehr_user_id}:{provider}"
            sync_status = cache.get(
                cache_key, {"status": "no_recent_sync", "last_sync": None, "records_synced": None, "errors": []}
            )

            status_data = {"ehr_user_id": ehr_user_id, "provider": provider, **sync_status}
        else:
            # Get status for all providers
            providers = ["withings", "fitbit"]
            all_statuses = {}

            for prov in providers:
                cache_key = f"sync_status:{ehr_user_id}:{prov}"
                prov_status = cache.get(
                    cache_key, {"status": "no_recent_sync", "last_sync": None, "records_synced": None, "errors": []}
                )
                all_statuses[prov] = prov_status

            status_data = {"ehr_user_id": ehr_user_id, "providers": all_statuses}

        return Response(status_data)

    @action(detail=False, methods=["get"])
    def providers(self, request):
        """Get connected providers for a user"""
        ehr_user_id = request.query_params.get("ehr_user_id")

        if not ehr_user_id:
            return Response({"error": "ehr_user_id parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = EHRUser.objects.get(ehr_user_id=ehr_user_id)
        except EHRUser.DoesNotExist:
            return Response({"error": f"User {ehr_user_id} not found"}, status=status.HTTP_404_NOT_FOUND)

        # Get provider links
        provider_links = ProviderLink.objects.filter(user=user)
        serializer = ProviderLinkSerializer(provider_links, many=True)

        return Response(
            {"ehr_user_id": ehr_user_id, "connected_providers": serializer.data, "total_providers": len(provider_links)}
        )

    @action(detail=False, methods=["post"])
    def trigger_device_sync(self, request):
        """Trigger device synchronization (for testing/admin use)"""
        serializer = DeviceSyncRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ehr_user_id = serializer.validated_data["ehr_user_id"]
        provider = serializer.validated_data["provider"]

        try:
            user = EHRUser.objects.get(ehr_user_id=ehr_user_id)
        except EHRUser.DoesNotExist:
            return Response({"error": f"User {ehr_user_id} not found"}, status=status.HTTP_404_NOT_FOUND)

        # Check provider connection
        provider_link = ProviderLink.objects.filter(
            user=user, provider__provider_type=provider, provider__active=True
        ).first()

        if not provider_link:
            return Response(
                {"error": f"No active {provider} connection found for user {ehr_user_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Queue device sync task (would use Huey in production)
        from ingestors.device_sync_service import MockDeviceSyncService

        device_sync_service = MockDeviceSyncService()

        try:
            result = device_sync_service.sync_user_devices(ehr_user_id, provider)

            # Cache result
            cache_key = f"device_sync_status:{ehr_user_id}:{provider}"
            cache.set(
                cache_key,
                {
                    "status": "completed" if result.success else "failed",
                    "timestamp": timezone.now().isoformat(),
                    "devices_processed": result.processed_devices,
                    "associations_created": result.processed_associations,
                    "errors": result.errors,
                },
                timeout=settings.HUEY_CONFIG["DEFAULT_TIMEOUT"],
            )

            response_data = {
                "message": "Device sync completed",
                "sync_id": f"device-sync-{timezone.now().strftime('%Y%m%d-%H%M%S')}",
                "ehr_user_id": ehr_user_id,
                "provider": provider,
                "devices_processed": result.processed_devices,
                "associations_created": result.processed_associations,
                "success": result.success,
                "errors": result.errors[:3] if result.errors else [],
            }

            response_serializer = DeviceSyncResultSerializer(response_data)
            return Response(response_serializer.data)

        except Exception as e:
            logger.error(f"Device sync error: {e}")
            return Response(
                {"error": "Device sync failed", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class InitiateProviderLinkingView(View):
    """
    View to initiate provider linking with proper user context.
    Stores the EHR user ID in session before redirecting to OAuth flow.
    """

    def get(self, request, provider):
        """
        Initiate provider linking for a specific EHR user.

        Expected usage:
        - Via query parameter: /api/base/link/{provider}/?ehr_user_id=12345
        - Via authenticated request: /api/base/link/{provider}/ (uses current user)
        """
        # Get EHR user ID from multiple sources
        ehr_user_id = None

        # 1. Check query parameter (for API-based linking)
        ehr_user_id = request.GET.get("ehr_user_id")

        # 2. Check if user is authenticated (for web-based linking)
        if not ehr_user_id and request.user.is_authenticated:
            ehr_user_id = getattr(request.user, "ehr_user_id", None)

        # 3. Check for bearer token and extract user (for JWT-based requests)
        if not ehr_user_id:
            auth_header = request.META.get("HTTP_AUTHORIZATION", "")
            if auth_header.startswith("Bearer "):
                try:
                    from mozilla_django_oidc.contrib.drf import get_oidc_backend

                    token = auth_header.split(" ")[1]
                    user = get_oidc_backend().get_or_create_user(token, None, None)
                    if user and hasattr(user, "ehr_user_id"):
                        ehr_user_id = user.ehr_user_id
                except Exception as e:
                    logger.warning(f"Could not extract user from bearer token: {e}")

        if not ehr_user_id:
            return JsonResponse(
                {
                    "error": "No EHR user ID provided",
                    "message": "Please provide ehr_user_id parameter or authenticate as a user",
                },
                status=400,
            )

        # Validate provider
        supported_providers = ["withings", "fitbit"]  # Add more as needed
        if provider not in supported_providers:
            return JsonResponse(
                {"error": f"Unsupported provider: {provider}", "supported_providers": supported_providers}, status=400
            )

        # Validate that the EHR user exists
        try:
            from base.models import EHRUser

            EHRUser.objects.get(ehr_user_id=ehr_user_id)
        except EHRUser.DoesNotExist:
            return JsonResponse({"error": f"EHR user {ehr_user_id} not found"}, status=404)

        # Get custom success/error URLs from query parameters (for mobile apps)
        success_url = request.GET.get("success_url")
        error_url = request.GET.get("error_url")

        # If not provided via query params, check provider configuration
        if not success_url or not error_url:
            try:
                provider_obj = Provider.objects.get(provider_type=provider, active=True)
                success_url = success_url or provider_obj.success_deeplink_url
                error_url = error_url or provider_obj.error_deeplink_url
            except Provider.DoesNotExist:
                logger.warning(f"Provider {provider} not found in database")

        # Store user context in session for the OAuth flow
        request.session["linking_ehr_user_id"] = ehr_user_id
        request.session["linking_provider"] = provider
        request.session["linking_timestamp"] = timezone.now().isoformat()

        # Store custom deeplink URLs if provided
        if success_url:
            request.session["linking_success_url"] = success_url
            logger.info(f"Using custom success URL: {success_url}")

        if error_url:
            request.session["linking_error_url"] = error_url
            logger.info(f"Using custom error URL: {error_url}")

        request.session.save()

        logger.info(f"Initiating {provider} OAuth linking for EHR user {ehr_user_id}")

        # Redirect to social auth URL
        social_auth_url = reverse("social:begin", args=[provider])
        return redirect(social_auth_url)


@api_view(["GET"])
@permission_classes([AllowAny])
def provider_linking_status(request, provider):
    """
    Check the status of provider linking for a user.
    Returns information about existing provider links.
    """
    # Get EHR user ID from query parameter or authenticated user
    ehr_user_id = request.GET.get("ehr_user_id")
    if not ehr_user_id and request.user.is_authenticated:
        ehr_user_id = getattr(request.user, "ehr_user_id", None)

    if not ehr_user_id:
        return Response({"error": "No EHR user ID provided"}, status=400)

    try:
        from base.models import EHRUser, ProviderLink

        target_user = EHRUser.objects.get(ehr_user_id=ehr_user_id)

        # Check for existing provider links
        provider_links = ProviderLink.objects.filter(user=target_user, provider__provider_type=provider)

        links_data = []
        for link in provider_links:
            links_data.append(
                {
                    "provider_name": link.provider.name,
                    "provider_type": link.provider.provider_type,
                    "external_user_id": link.external_user_id,
                    "active": link.provider.active,
                    "linked_at": link.linked_at.isoformat() if hasattr(link, "linked_at") and link.linked_at else None,
                }
            )

        return Response(
            {
                "ehr_user_id": ehr_user_id,
                "provider": provider,
                "linked": len(links_data) > 0,
                "links": links_data,
                "total_links": len(links_data),
            }
        )

    except EHRUser.DoesNotExist:
        return Response({"error": f"EHR user {ehr_user_id} not found"}, status=404)


class ProviderLinkSuccessView(View):
    """
    Success page shown after successful provider linking.
    Supports mobile app deeplinks for seamless integration.
    """

    def get(self, request):
        """
        Display success page or redirect to mobile app deeplink if configured.
        """
        # Get provider information from session (stored during OAuth flow)
        provider = request.session.get("linking_provider", "provider")
        ehr_user_id = request.session.get("linking_ehr_user_id")
        success_url = request.session.get("linking_success_url")

        # Clear the linking session data since we're done
        request.session.pop("linking_provider", None)
        request.session.pop("linking_ehr_user_id", None)
        request.session.pop("linking_timestamp", None)
        request.session.pop("linking_success_url", None)
        request.session.pop("linking_error_url", None)

        # If deeplink URL is configured, redirect to mobile app
        if success_url:
            from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

            # Parse the deeplink URL
            parsed = urlparse(success_url)

            # Add provider and user info as query parameters
            query_params = parse_qs(parsed.query)
            query_params["provider"] = [provider]
            if ehr_user_id:
                query_params["ehr_user_id"] = [ehr_user_id]
            query_params["status"] = ["success"]

            # Rebuild URL with updated query parameters
            new_query = urlencode(query_params, doseq=True)
            deeplink_url = urlunparse(
                (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
            )

            logger.info(f"Redirecting to mobile app success deeplink: {deeplink_url}")
            return HttpResponseRedirect(deeplink_url)

        # Otherwise, render the default success template
        return render(request, "base/provider_link_success.html", {"provider": provider})


@api_view(["POST"])
@permission_classes([AllowAny])
def trigger_device_sync(request, provider):
    """
    Manually trigger device synchronization for a provider.
    This will be used to test the device sync flow.
    """
    # Get EHR user ID
    ehr_user_id = request.data.get("ehr_user_id") or request.GET.get("ehr_user_id")
    if not ehr_user_id and request.user.is_authenticated:
        ehr_user_id = getattr(request.user, "ehr_user_id", None)

    if not ehr_user_id:
        return Response({"error": "No EHR user ID provided"}, status=400)

    try:
        from base.models import EHRUser, ProviderLink

        target_user = EHRUser.objects.get(ehr_user_id=ehr_user_id)

        # Find active provider link
        provider_link = ProviderLink.objects.filter(
            user=target_user, provider__provider_type=provider, provider__active=True
        ).first()

        if not provider_link:
            return Response({"error": f"No active {provider} provider link found for user {ehr_user_id}"}, status=404)

        # Queue device and health sync tasks in parallel
        try:
            # Get provider configuration
            from ingestors.constants import PROVIDER_CONFIGS, Provider

            try:
                provider_enum = Provider(provider)
                provider_config = PROVIDER_CONFIGS.get(provider_enum)
                if not provider_config:
                    return Response({"error": f"No configuration found for provider {provider}"}, status=400)
            except ValueError:
                return Response({"error": f"Unsupported provider: {provider}"}, status=400)

            # Get access token from provider link
            access_token = None
            if provider_link.extra_data and "access_token" in provider_link.extra_data:
                access_token = provider_link.extra_data["access_token"]

            if not access_token:
                return Response({"error": f"No access token found for {provider} provider link"}, status=400)

            # Get configured data types from database provider settings
            from base.models import Provider as ProviderModel

            try:
                provider_db = ProviderModel.objects.get(provider_type=provider, active=True)
                effective_data_types = provider_db.get_effective_data_types()
                webhook_enabled = provider_db.is_webhook_enabled()
            except ProviderModel.DoesNotExist:
                # Fallback to config defaults if provider not in database
                effective_data_types = provider_config.default_health_data_types
                webhook_enabled = provider_config.supports_webhooks
                logger.warning(f"Provider {provider} not found in database, using config defaults")

            from ingestors.health_data_tasks import sync_user_health_data_initial
            from ingestors.tasks import ensure_webhook_subscriptions, sync_user_devices

            # Queue device sync (high priority)
            sync_user_devices(target_user.ehr_user_id, provider)

            # Queue health data sync (low priority for initial sync)
            if effective_data_types:  # Only sync if data types are configured
                sync_user_health_data_initial(
                    target_user.ehr_user_id,
                    provider,
                    lookback_days=30,  # Initial sync covers last 30 days
                    data_types=effective_data_types,
                )

            # Queue webhook subscription creation (medium priority, async)
            if webhook_enabled and effective_data_types:
                ensure_webhook_subscriptions(target_user.ehr_user_id, provider, data_types=effective_data_types)
                logger.info(f"Queued webhook subscription creation for user {target_user.ehr_user_id}")
            else:
                logger.info(f"Webhooks disabled or no data types configured for {provider}")

        except Exception as e:
            logger.error(f"Error queuing device sync task: {e}")
            return Response({"error": f"Failed to queue device sync: {str(e)}"}, status=500)

        return Response(
            {
                "message": f"Device sync initiated for {provider}",
                "ehr_user_id": ehr_user_id,
                "provider": provider,
                "provider_link_id": provider_link.id,
            }
        )

    except EHRUser.DoesNotExist:
        return Response({"error": f"EHR user {ehr_user_id} not found"}, status=404)


class ProviderLinkErrorView(View):
    """
    Error page shown when provider linking fails.
    Supports mobile app deeplinks with error details.
    """

    def get(self, request):
        """
        Display error page or redirect to mobile app deeplink with error details.
        """
        # Get provider and error information from session/query params
        provider = request.session.get("linking_provider", "provider")
        ehr_user_id = request.session.get("linking_ehr_user_id")
        error_url = request.session.get("linking_error_url")

        # Get error details from query parameters (set by OAuth error handler)
        error_code = request.GET.get("error", "unknown_error")
        error_message = request.GET.get("error_description", "Provider linking failed")

        # If deeplink URL is configured, redirect to mobile app with error details
        if error_url:
            from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

            # Parse the deeplink URL
            parsed = urlparse(error_url)

            # Add provider, user info, and error details as query parameters
            query_params = parse_qs(parsed.query)
            query_params["provider"] = [provider]
            if ehr_user_id:
                query_params["ehr_user_id"] = [ehr_user_id]
            query_params["status"] = ["error"]
            query_params["error"] = [error_code]
            query_params["message"] = [error_message]

            # Rebuild URL with updated query parameters
            new_query = urlencode(query_params, doseq=True)
            deeplink_url = urlunparse(
                (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
            )

            logger.info(f"Redirecting to mobile app error deeplink: {deeplink_url}")

            # Clear session data after redirecting to error deeplink
            request.session.pop("linking_provider", None)
            request.session.pop("linking_ehr_user_id", None)
            request.session.pop("linking_timestamp", None)
            request.session.pop("linking_success_url", None)
            request.session.pop("linking_error_url", None)

            return HttpResponseRedirect(deeplink_url)

        # Keep the session data for potential retry if no deeplink
        # Don't clear it like we do in success view

        # Render the error template
        return render(
            request,
            "base/provider_link_error.html",
            {"provider": provider, "error_code": error_code, "error_message": error_message},
        )
