"""
Huey tasks for device synchronization
"""

import logging

from django.utils import timezone
from huey import crontab

from base.models import EHRUser, ProviderLink
from open_health_exchange.settings import HUEY

from .constants import Provider
from .device_sync_service import DeviceSyncService

logger = logging.getLogger(__name__)


@HUEY.task(priority=1)  # High priority for real-time sync
def sync_user_devices(user_id: str, provider_name: str, patient_reference: str | None = None) -> dict:
    """
    Device synchronization task

    Args:
        user_id: EHR user ID
        provider_name: Provider name (withings, fitbit, etc.)
        patient_reference: Optional FHIR Patient reference

    Returns:
        Sync result dictionary
    """
    logger.info(f"Starting device sync for user {user_id} with provider {provider_name}")

    try:
        # Validate inputs
        try:
            user = EHRUser.objects.get(ehr_user_id=user_id)
            provider = Provider(provider_name)
        except EHRUser.DoesNotExist:
            error_msg = f"EHR user {user_id} not found"
            logger.error(error_msg)
            return {"error": error_msg, "success": False}
        except ValueError:
            error_msg = f"Unsupported provider: {provider_name}"
            logger.error(error_msg)
            return {"error": error_msg, "success": False}

        # Perform sync
        sync_service = DeviceSyncService()
        result = sync_service.sync_user_devices(user_id=user_id, provider=provider, patient_reference=patient_reference)

        # Update provider link with sync information
        try:
            _update_provider_link_sync_info(user, provider, result)
        except Exception as e:
            logger.warning(f"Could not update provider link: {e}")

        # Convert result to dictionary
        result_dict = {
            "user_id": result.user_id,
            "provider": result.provider.value,
            "processed_devices": result.processed_devices,
            "processed_associations": result.processed_associations,
            "deactivated_devices": result.deactivated_devices,
            "deactivated_associations": result.deactivated_associations,
            "errors": result.errors,
            "success": result.success,
            "sync_timestamp": result.sync_timestamp,
        }

        logger.info(f"Device sync completed for user {user_id}: {result_dict}")
        return result_dict

    except Exception as e:
        error_msg = f"Unexpected error in device sync for user {user_id}: {e}"
        logger.error(error_msg)
        return {"error": error_msg, "success": False}


@HUEY.task(priority=5)  # Lowest priority for test tasks
def test_task() -> str:
    """
    Simple test task
    """
    logger.info("Test task executed successfully!")
    return "Test task completed"


@HUEY.periodic_task(crontab(hour="2", minute="30"), priority=2)  # Nightly sync
def nightly_device_sync() -> list[dict]:
    """
    Nightly device synchronization task
    Runs every night at 2:30 AM
    """
    logger.info("Starting nightly device synchronization")

    # Get all active provider links
    active_links = ProviderLink.objects.filter(provider__active=True).select_related("user", "provider")

    sync_results = []

    for link in active_links:
        try:
            # Validate provider is supported
            if link.provider.provider_type not in [p.value for p in Provider]:
                logger.warning(f"Unsupported provider {link.provider.provider_type} for link {link.id}")
                continue

            # Check for access token
            if not link.extra_data or "access_token" not in link.extra_data:
                logger.warning(f"No access token found for provider link {link.id}")
                continue

            # Queue device sync task
            result = sync_user_devices(user_id=link.user.ehr_user_id, provider_name=link.provider.provider_type)
            sync_results.append(result)

            logger.info(f"Queued device sync for user {link.user.ehr_user_id} with {link.provider.provider_type}")

        except Exception as e:
            error_result = {
                "error": f"Error processing provider link {link.id}: {e}",
                "success": False,
                "link_id": link.id,
            }
            sync_results.append(error_result)
            logger.error(f"Error processing provider link {link.id}: {e}")

    logger.info(f"Nightly device sync completed. Processed {len(sync_results)} provider links")
    return sync_results


def _update_provider_link_sync_info(user: EHRUser, provider: Provider, result) -> None:
    """Update provider link with sync information"""
    try:
        provider_link = ProviderLink.objects.filter(user=user, provider__provider_type=provider.value).first()

        if provider_link:
            # Update extra_data with sync information
            if not provider_link.extra_data:
                provider_link.extra_data = {}

            provider_link.extra_data.update(
                {
                    "last_device_sync": result.sync_timestamp,
                    "last_sync_device_count": result.processed_devices,
                    "last_sync_association_count": result.processed_associations,
                    "last_sync_errors": len(result.errors),
                    "last_sync_success": result.success,
                }
            )
            provider_link.save()
            logger.info(f"Updated provider link {provider_link.id} with sync information")

    except Exception as e:
        logger.error(f"Failed to update provider link: {e}")
        raise


@HUEY.task(priority=3)  # Medium priority for subscription management
def ensure_webhook_subscriptions(user_id: str, provider_name: str, data_types: list[str] | None = None) -> dict:
    """
    Ensure webhook subscriptions exist for a user and provider

    Args:
        user_id: EHR user ID
        provider_name: Provider name (withings, fitbit, etc.)
        data_types: Optional list of data types to subscribe to

    Returns:
        Subscription result dictionary
    """
    logger.info(f"Ensuring webhook subscriptions for user {user_id} with provider {provider_name}")

    try:
        # Validate inputs
        try:
            user = EHRUser.objects.get(ehr_user_id=user_id)
            provider = Provider(provider_name)
        except EHRUser.DoesNotExist:
            error_msg = f"EHR user {user_id} not found"
            logger.error(error_msg)
            return {"error": error_msg, "success": False}
        except ValueError:
            error_msg = f"Unsupported provider: {provider_name}"
            logger.error(error_msg)
            return {"error": error_msg, "success": False}

        # Get provider configuration
        from ingestors.constants import PROVIDER_CONFIGS

        provider_config = PROVIDER_CONFIGS.get(provider)
        if not provider_config:
            error_msg = f"No configuration found for provider {provider_name}"
            logger.error(error_msg)
            return {"error": error_msg, "success": False}

        # Get configured data types from database provider settings
        from base.models import Provider as ProviderModel

        try:
            provider_db = ProviderModel.objects.get(provider_type=provider_name, active=True)
            effective_data_types = provider_db.get_effective_data_types() if not data_types else data_types
            webhook_enabled = provider_db.is_webhook_enabled()
        except ProviderModel.DoesNotExist:
            # Fallback to config defaults if provider not in database
            effective_data_types = data_types or provider_config.default_health_data_types
            webhook_enabled = provider_config.supports_webhooks
            logger.warning(f"Provider {provider_name} not found in database, using config defaults")

        # Check if webhooks are enabled
        if not webhook_enabled:
            error_msg = f"Webhook subscriptions disabled for provider {provider_name}"
            logger.warning(error_msg)
            return {"error": error_msg, "success": False}

        # Use effective data types
        data_types = effective_data_types

        # Import subscription manager
        from webhooks.subscriptions import WebhookSubscriptionManager

        subscription_manager = WebhookSubscriptionManager()

        try:
            # Get collection types from provider configuration
            all_collection_types = set()
            for data_type in data_types:
                if data_type in provider_config.webhook_collection_types:
                    all_collection_types.update(provider_config.webhook_collection_types[data_type])

            if not all_collection_types:
                error_msg = f"No webhook collection types found for data types {data_types}"
                logger.error(error_msg)
                return {"error": error_msg, "success": False}

            # Create subscriptions based on provider type
            if provider == Provider.WITHINGS:
                # For Withings, collection types are appli IDs (integers)
                subscription_manager.create_withings_subscription(user_id, data_types=data_types)
                logger.info(f"Successfully ensured Withings subscriptions for user {user_id}")

            elif provider == Provider.FITBIT:
                # For Fitbit, collection types are strings like "activities", "body"
                subscription_manager.create_fitbit_subscription(user_id, collection_types=list(all_collection_types))
                logger.info(f"Successfully ensured Fitbit subscriptions for user {user_id}")

            else:
                error_msg = f"Webhook subscription creation not implemented for provider {provider_name}"
                logger.error(error_msg)
                return {"error": error_msg, "success": False}

            # Update provider link with subscription info
            try:
                provider_link = ProviderLink.objects.filter(user=user, provider__provider_type=provider.value).first()

                if provider_link:
                    if not provider_link.extra_data:
                        provider_link.extra_data = {}

                    provider_link.extra_data.update(
                        {
                            "webhook_subscriptions_created": timezone.now().isoformat(),
                            "subscribed_data_types": data_types,
                            "webhook_active": True,
                        }
                    )
                    provider_link.save()
                    logger.debug(f"Updated provider link {provider_link.id} with subscription info")

            except Exception as e:
                logger.warning(f"Could not update provider link with subscription info: {e}")

            return {
                "user_id": user_id,
                "provider": provider_name,
                "data_types": data_types,
                "subscription_active": True,
                "success": True,
                "timestamp": timezone.now().isoformat(),
            }

        except Exception as e:
            error_msg = f"Failed to create webhook subscriptions for {provider_name}: {e}"
            logger.error(error_msg)
            return {"error": error_msg, "success": False}

    except Exception as e:
        error_msg = f"Unexpected error ensuring webhook subscriptions for user {user_id}: {e}"
        logger.error(error_msg)
        return {"error": error_msg, "success": False}
