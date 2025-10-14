import logging

from mozilla_django_oidc.contrib.drf import get_oidc_backend
from social_core.exceptions import AuthForbidden

logger = logging.getLogger(__name__)


def associate_by_token_user(strategy, details, backend, user=None, *args, **kwargs):
    """
    Associate the current authenticated user with the social account.
    Uses multiple methods to identify the target EHR user:
    1. Session-stored EHR user ID (preferred for provider linking)
    2. Bearer token from request/session (for API calls)
    3. Currently authenticated user
    """
    logger.info(f"Starting user association for social auth - Backend: {backend.name}")

    # Debug session data
    session_keys = [k for k in strategy.session.keys() if "linking" in k]
    logger.info(f"Session keys with 'linking': {session_keys}")

    if not user:
        target_user = None

        # Method 1: Check for EHR user ID stored in session (provider linking flow)
        ehr_user_id = strategy.session_get("linking_ehr_user_id")
        provider_from_session = strategy.session_get("linking_provider")

        logger.info(f"Session data - EHR User ID: {ehr_user_id}, Provider: {provider_from_session}")

        if ehr_user_id:
            logger.info(f"Found EHR user ID in session: {ehr_user_id}")
            try:
                from base.models import EHRUser

                target_user = EHRUser.objects.get(ehr_user_id=ehr_user_id)
                logger.info(f"Successfully retrieved user {target_user.username} for provider linking")

                # Clear the session data after use
                strategy.session_set("linking_ehr_user_id", None)

                return {"user": target_user}
            except EHRUser.DoesNotExist:
                logger.error(f"EHR user with ID {ehr_user_id} not found in database")
                # Don't immediately fail - try other methods first
                logger.warning(f"EHR user {ehr_user_id} not found, trying other authentication methods")
        else:
            logger.warning("No EHR user ID found in session - session may have been lost during OAuth redirect")

        # Method 2: Bearer token from request/session (API-based auth)
        bearer_token = strategy.request.GET.get("token") or strategy.session_get("token")
        if bearer_token:
            logger.info("Attempting OIDC authentication with bearer token")
            try:
                current_user = get_oidc_backend().get_or_create_user(bearer_token, None, None)
                if current_user and current_user.is_authenticated:
                    logger.info(f"Using OIDC authenticated user {current_user.username} for social account linking")
                    return {"user": current_user}
            except Exception as e:
                logger.warning(f"OIDC authentication failed: {e}")

        # Method 3: Currently authenticated user (fallback)
        if hasattr(strategy.request, "user") and strategy.request.user.is_authenticated:
            logger.info(f"Using currently authenticated user {strategy.request.user.username}")
            return {"user": strategy.request.user}

    # If we don't have a user and are not creating new ones, stop the pipeline
    if not user and not strategy.setting("SOCIAL_AUTH_CREATE_USERS", True):
        error_msg = (
            f"OAuth flow failed for {backend.name}: No user found for association. "
            f"Checked session (ehr_user_id: {ehr_user_id}), bearer token, and authenticated user. "
            f"User creation is disabled (SOCIAL_AUTH_CREATE_USERS=False)."
        )
        logger.error(error_msg)
        raise AuthForbidden(backend, error_msg)

    return None


def initialize_provider_services(strategy, details, backend, user, response, *args, **kwargs):
    """
    Initialize provider services after successful OAuth linking.
    Queues device sync, health sync, and webhook subscription tasks.
    This runs at the end of the OAuth pipeline after a successful connection.
    """
    if not user:
        logger.warning("No user provided to initialize_provider_services, skipping initialization")
        return

    provider_name = backend.name
    logger.info(f"Initializing provider services for user {user.username} with provider {provider_name}")

    try:
        # Get provider configuration
        from ingestors.constants import PROVIDER_CONFIGS, Provider

        try:
            provider_enum = Provider(provider_name)
            provider_config = PROVIDER_CONFIGS.get(provider_enum)
            if not provider_config:
                logger.warning(f"No configuration found for provider {provider_name}")
                return
        except ValueError:
            logger.warning(f"Unsupported provider: {provider_name}")
            return

        # Get the access token from the response/extra data
        access_token = None
        if hasattr(user, "social_auth"):
            social_user = user.social_auth.filter(provider=provider_name).first()
            if social_user:
                access_token = social_user.access_token

        # If we don't have the token from social_user, try to get it from response
        if not access_token and response:
            access_token = response.get("access_token")

        if not access_token:
            logger.error(f"No access token found for {provider_name} provider")
            return

        # Get configured data types from database provider settings
        from base.models import Provider as ProviderModel

        try:
            provider_db = ProviderModel.objects.get(provider_type=provider_name, active=True)
            effective_data_types = provider_db.get_effective_data_types()
            webhook_enabled = provider_db.is_webhook_enabled()
        except ProviderModel.DoesNotExist:
            # Fallback to config defaults if provider not in database
            effective_data_types = provider_config.default_health_data_types
            webhook_enabled = provider_config.supports_webhooks
            logger.warning(f"Provider {provider_name} not found in database, using config defaults")

        # Import and queue both device and health sync tasks in parallel
        try:
            from ingestors.health_data_tasks import sync_user_health_data_initial
            from ingestors.tasks import ensure_webhook_subscriptions, sync_user_devices

            # Queue device sync (high priority)
            sync_user_devices(user.ehr_user_id, provider_name)

            # Queue health data sync (low priority for initial sync)
            if effective_data_types:  # Only sync if data types are configured
                sync_user_health_data_initial(
                    user.ehr_user_id,
                    provider_name,
                    lookback_days=30,  # Initial sync covers last 30 days
                    data_types=effective_data_types,
                )

            # Queue webhook subscription creation (medium priority, async)
            if webhook_enabled and effective_data_types:
                ensure_webhook_subscriptions(user.ehr_user_id, provider_name, data_types=effective_data_types)
                logger.info(f"Queued webhook subscription creation for user {user.ehr_user_id}")
            else:
                logger.info(f"Webhooks disabled or no data types configured for {provider_name}")

            logger.info(f"Successfully queued all provider services for user {user.ehr_user_id}")
        except ImportError:
            logger.warning("Sync tasks not available yet - tasks will be implemented next")
            logger.info(f"Would initialize services for user {user.ehr_user_id} with {provider_name}")

    except Exception as e:
        logger.error(f"Error initializing provider services for user {user.username}: {e}")
        # Don't fail the OAuth flow if service initialization fails
