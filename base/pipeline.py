import logging

from django.conf import settings
from mozilla_django_oidc.contrib.drf import get_oidc_backend
from social_core.exceptions import AuthForbidden
from social_django.models import UserSocialAuth

logger = logging.getLogger(__name__)


def associate_by_token_user(strategy, details, backend, user=None, *args, **kwargs):
    """
    Associate the current authenticated user with the social account.
    Uses multiple methods to identify the target EHR user:
    1. Session-stored EHR user ID (always takes priority - this is the provider linking flow)
    2. Bearer token from request/session (for API calls)
    3. Currently authenticated user
    """
    logger.info(f"Starting user association for social auth - Backend: {backend.name}")

    # Debug session data
    session_keys = [k for k in strategy.session.keys() if "linking" in k]
    logger.info(f"Session keys with 'linking': {session_keys}")

    if user:
        logger.info(
            f"Pipeline already has user set: {user.username} (ehr_user_id: {getattr(user, 'ehr_user_id', 'N/A')})"
        )

    # Method 1: Check for EHR user ID stored in session (provider linking flow)
    # This ALWAYS takes priority, even if user is already set by social_core,
    # because the session contains the correct EHR user from the linking initiation.
    ehr_user_id = strategy.session_get("linking_ehr_user_id")
    provider_from_session = strategy.session_get("linking_provider")

    logger.info(f"Session data - EHR User ID: {ehr_user_id}, Provider: {provider_from_session}")

    if ehr_user_id:
        logger.info(f"Found EHR user ID in session: {ehr_user_id}")
        try:
            from base.models import EHRUser

            target_user = EHRUser.objects.get(ehr_user_id=ehr_user_id)
            if user and user != target_user:
                logger.warning(f"Overriding pipeline user {user.username} with session EHR user {target_user.username}")
            logger.info(f"Successfully retrieved user {target_user.username} for provider linking")

            return {"user": target_user}
        except EHRUser.DoesNotExist:
            # Session indicates linking flow but user doesn't exist - CRITICAL ERROR
            error_msg = (
                f"OAuth linking flow failed for {backend.name}: Session indicates linking to "
                f"EHR user {ehr_user_id}, but this user does not exist in the database. "
                f"This may indicate a race condition (user deleted during OAuth) or session corruption."
            )
            logger.error(error_msg)
            raise AuthForbidden(backend, error_msg)

    if not user:
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


def handle_existing_social_association(strategy, details, backend, user=None, uid=None, *args, **kwargs):
    """
    Handle the case where a social account is already linked to a different user.
    If the social account exists and belongs to a different EHR user, delete the old
    association and let the pipeline create a fresh one for the new user.

    Also cleans up any duplicate UserSocialAuth records for the same provider+uid
    to prevent 'get() returned more than one' errors in downstream code.

    This allows users to relink their health provider accounts if they've changed
    EHR systems or if there was a previous incorrect association.
    """
    if not user or not uid:
        return None

    provider = backend.name

    # Find ALL existing social auths for this provider+uid (handles duplicates)
    existing_socials = UserSocialAuth.objects.filter(provider=provider, uid=uid)
    count = existing_socials.count()

    if count == 0:
        # No existing association, let the pipeline continue normally
        return None

    if count > 1:
        logger.warning(f"Found {count} duplicate UserSocialAuth records for {provider}:{uid}, cleaning up")

    # Check if any belong to the current user
    own_social = existing_socials.filter(user=user).first()

    # Delete all existing social auths for this provider+uid that belong to OTHER users
    for existing_social in existing_socials.exclude(user=user):
        old_user = existing_social.user
        logger.warning(
            f"Social account {provider}:{uid} is linked to user {old_user.ehr_user_id}. "
            f"Deleting old association to relink to {user.ehr_user_id}."
        )

        # Clean up the old user's ProviderLink
        try:
            from base.models import ProviderLink

            old_provider_link = ProviderLink.objects.filter(
                user=old_user,
                provider__provider_type=provider,
            ).first()

            if old_provider_link:
                logger.info(f"Removing old ProviderLink for user {old_user.ehr_user_id}")
                old_provider_link.delete()
        except Exception as e:
            logger.warning(f"Error cleaning up old ProviderLink: {e}")

        existing_social.delete()
        logger.info(f"Deleted old UserSocialAuth {provider}:{uid} for user {old_user.ehr_user_id}")

    # Also clean up duplicates for the current user (keep only one)
    own_socials = UserSocialAuth.objects.filter(provider=provider, uid=uid, user=user)
    if own_socials.count() > 1:
        logger.warning(f"Found {own_socials.count()} duplicate UserSocialAuth for current user, keeping newest")
        # Keep the most recent one, delete the rest
        latest = own_socials.order_by("-id").first()
        own_socials.exclude(id=latest.id).delete()
        own_social = latest

    if own_social:
        logger.info(f"Social account {provider}:{uid} already linked to current user {user.ehr_user_id}")
        return {"social": own_social, "is_new": False}

    # All old associations deleted, let the pipeline create a fresh one
    logger.info(f"Old associations cleaned up, pipeline will create new UserSocialAuth for {user.ehr_user_id}")
    return None


def create_provider_link(strategy, details, backend, user, uid, response, *args, **kwargs):
    """
    Create or update the ProviderLink after successful OAuth authentication.
    This links the external provider user ID (e.g., Withings userid) to the EHR user,
    enabling webhook processing to find the correct user.
    """
    if not user or not uid:
        logger.warning("Cannot create ProviderLink: missing user or uid")
        return None

    provider_name = backend.name
    external_user_id = str(uid)

    try:
        from base.models import Provider, ProviderLink

        # Get or create the Provider model instance
        provider_db, created = Provider.objects.get_or_create(
            provider_type=provider_name,
            defaults={
                "name": provider_name.title(),
                "active": True,
            },
        )
        if created:
            logger.info(f"Created new Provider: {provider_name}")

        # Create or update the ProviderLink
        provider_link, link_created = ProviderLink.objects.update_or_create(
            provider=provider_db,
            user=user,
            defaults={
                "external_user_id": external_user_id,
                "extra_data": {
                    "linked_via": "oauth_pipeline",
                    "response_keys": list(response.keys()) if response else [],
                },
            },
        )

        if link_created:
            logger.info(
                f"Created ProviderLink: {provider_name} external_user_id={external_user_id} -> EHR user {user.ehr_user_id}"
            )
        else:
            logger.info(
                f"Updated ProviderLink: {provider_name} external_user_id={external_user_id} -> EHR user {user.ehr_user_id}"
            )

        return {"provider_link": provider_link}

    except Exception as e:
        logger.error(f"Error creating ProviderLink for {provider_name}: {e}")
        # Don't fail the OAuth flow if ProviderLink creation fails
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

            # Queue device sync (high priority) - async to not block OAuth callback
            sync_user_devices(user_id=user.ehr_user_id, provider_name=provider_name)

            # Queue health data sync (low priority for initial sync) - async
            if effective_data_types:  # Only sync if data types are configured
                sync_user_health_data_initial(
                    user_id=user.ehr_user_id,
                    provider_name=provider_name,
                    lookback_days=settings.HEALTH_DATA_CONFIG["LOOKBACK_DAYS"],
                    data_types=effective_data_types,
                )

            # Queue webhook subscription creation (medium priority) - async
            if webhook_enabled and effective_data_types:
                ensure_webhook_subscriptions(
                    user_id=user.ehr_user_id, provider_name=provider_name, data_types=effective_data_types
                )
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
