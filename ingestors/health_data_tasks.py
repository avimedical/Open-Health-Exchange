"""
Huey tasks for health data synchronization
"""
import logging
from datetime import datetime
from typing import Any

from huey import crontab
from open_health_exchange.settings import HUEY

from .health_data_service import HealthDataSyncService
from .health_sync_strategies import SyncStrategy, SyncStrategyFactory
from .health_data_constants import (
    Provider, HealthDataType, SyncTrigger, HealthSyncConfig,
    AggregationLevel, SyncFrequency, DateRange
)
from base.models import EHRUser, ProviderLink


logger = logging.getLogger(__name__)


@HUEY.task(priority=1)  # High priority for real-time sync
def sync_user_health_data_realtime(
    user_id: str,
    provider_name: str,
    data_types: list[str],
    trigger_type: str = "webhook",
    date_range: dict[str, str] | None = None
) -> dict[str, Any]:
    """
    Real-time health data sync triggered by webhooks

    Args:
        user_id: EHR user ID
        provider_name: Provider name (withings, fitbit, etc.)
        data_types: List of health data type strings
        trigger_type: What triggered this sync
        date_range: Optional custom date range

    Returns:
        Sync result dictionary
    """
    logger.info(f"Starting real-time health data sync for user {user_id} with provider {provider_name}")

    try:
        # Validate inputs
        try:
            user = EHRUser.objects.get(ehr_user_id=user_id)
            provider = Provider(provider_name)
            data_type_enums = [HealthDataType(dt) for dt in data_types]
        except EHRUser.DoesNotExist:
            error_msg = f"EHR user {user_id} not found"
            logger.error(error_msg)
            return {"error": error_msg, "success": False}
        except ValueError as e:
            error_msg = f"Invalid parameter: {e}"
            logger.error(error_msg)
            return {"error": error_msg, "success": False}

        # Create sync strategy
        sync_strategy: SyncStrategy = SyncStrategyFactory.create_webhook_sync()

        # Override date range if provided
        if date_range:
            try:
                start_date = datetime.fromisoformat(date_range["start"].replace("Z", "+00:00"))
                end_date = datetime.fromisoformat(date_range["end"].replace("Z", "+00:00"))
                custom_range = DateRange(start_date, end_date)
                sync_strategy = SyncStrategyFactory.create_manual_sync(custom_range)
            except Exception as e:
                logger.warning(f"Invalid date range, using default: {e}")

        # Create sync service
        sync_service = HealthDataSyncService()

        # Perform sync
        result = sync_service.sync_user_health_data(
            user_id=user_id,
            provider=provider,
            data_types=data_type_enums,
            sync_strategy=sync_strategy
        )

        # Convert result to dictionary
        result_dict = {
            "user_id": result.user_id,
            "provider": result.provider.value,
            "data_types": [dt.value for dt in result.data_types],
            "trigger": result.trigger.value,
            "records_fetched": result.records_fetched,
            "records_transformed": result.records_transformed,
            "fhir_resources_created": result.fhir_resources_created,
            "errors": result.errors,
            "success": result.success,
            "sync_timestamp": result.sync_timestamp,
            "processing_time_ms": result.processing_time_ms
        }

        logger.info(f"Real-time health data sync completed for user {user_id}: {result_dict}")
        return result_dict

    except Exception as e:
        error_msg = f"Unexpected error in real-time health data sync for user {user_id}: {e}"
        logger.error(error_msg)
        return {"error": error_msg, "success": False}


@HUEY.task(priority=3)  # Medium priority for scheduled sync
def sync_user_health_data_incremental(
    user_id: str,
    provider_name: str,
    data_types: list[str] | None = None
) -> dict[str, Any]:
    """
    Incremental health data sync for regular updates

    Args:
        user_id: EHR user ID
        provider_name: Provider name
        data_types: Optional list of specific data types to sync

    Returns:
        Sync result dictionary
    """
    logger.info(f"Starting incremental health data sync for user {user_id} with provider {provider_name}")

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

        # Determine data types to sync
        if data_types:
            try:
                data_type_enums = [HealthDataType(dt) for dt in data_types]
            except ValueError as e:
                error_msg = f"Invalid data type: {e}"
                logger.error(error_msg)
                return {"error": error_msg, "success": False}
        else:
            # Default to heart rate and steps for Phase 1
            data_type_enums = [HealthDataType.HEART_RATE, HealthDataType.STEPS]

        # Create incremental sync strategy
        sync_strategy = SyncStrategyFactory.create_incremental_sync()

        # Create sync service
        sync_service = HealthDataSyncService()

        # Perform sync
        result = sync_service.sync_user_health_data(
            user_id=user_id,
            provider=provider,
            data_types=data_type_enums,
            sync_strategy=sync_strategy
        )

        # Update provider link with sync information
        try:
            _update_provider_link_health_sync_info(user, provider, result)
        except Exception as e:
            logger.warning(f"Could not update provider link: {e}")

        # Convert result to dictionary
        result_dict = {
            "user_id": result.user_id,
            "provider": result.provider.value,
            "data_types": [dt.value for dt in result.data_types],
            "trigger": result.trigger.value,
            "records_fetched": result.records_fetched,
            "records_transformed": result.records_transformed,
            "fhir_resources_created": result.fhir_resources_created,
            "errors": result.errors,
            "success": result.success,
            "sync_timestamp": result.sync_timestamp,
            "processing_time_ms": result.processing_time_ms
        }

        logger.info(f"Incremental health data sync completed for user {user_id}: {result_dict}")
        return result_dict

    except Exception as e:
        error_msg = f"Unexpected error in incremental health data sync for user {user_id}: {e}"
        logger.error(error_msg)
        return {"error": error_msg, "success": False}


@HUEY.task(priority=4)  # Low priority for initial sync
def sync_user_health_data_initial(
    user_id: str,
    provider_name: str,
    lookback_days: int = 30,
    data_types: list[str] | None = None
) -> dict[str, Any]:
    """
    Initial health data sync for new users

    Args:
        user_id: EHR user ID
        provider_name: Provider name
        lookback_days: Number of days to sync historically
        data_types: Optional list of specific data types to sync

    Returns:
        Sync result dictionary
    """
    logger.info(f"Starting initial health data sync for user {user_id} with provider {provider_name} ({lookback_days} days)")

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

        # Determine data types to sync
        if data_types:
            try:
                data_type_enums = [HealthDataType(dt) for dt in data_types]
            except ValueError as e:
                error_msg = f"Invalid data type: {e}"
                logger.error(error_msg)
                return {"error": error_msg, "success": False}
        else:
            # Default to heart rate and steps for Phase 1
            data_type_enums = [HealthDataType.HEART_RATE, HealthDataType.STEPS]

        # Create initial sync strategy
        sync_strategy = SyncStrategyFactory.create_initial_sync(lookback_days)

        # Create sync service
        sync_service = HealthDataSyncService()

        # Perform sync
        result = sync_service.sync_user_health_data(
            user_id=user_id,
            provider=provider,
            data_types=data_type_enums,
            sync_strategy=sync_strategy
        )

        # Update provider link with sync information
        try:
            _update_provider_link_health_sync_info(user, provider, result)
        except Exception as e:
            logger.warning(f"Could not update provider link: {e}")

        # Convert result to dictionary
        result_dict = {
            "user_id": result.user_id,
            "provider": result.provider.value,
            "data_types": [dt.value for dt in result.data_types],
            "trigger": result.trigger.value,
            "records_fetched": result.records_fetched,
            "records_transformed": result.records_transformed,
            "fhir_resources_created": result.fhir_resources_created,
            "errors": result.errors,
            "success": result.success,
            "sync_timestamp": result.sync_timestamp,
            "processing_time_ms": result.processing_time_ms
        }

        logger.info(f"Initial health data sync completed for user {user_id}: {result_dict}")
        return result_dict

    except Exception as e:
        error_msg = f"Unexpected error in initial health data sync for user {user_id}: {e}"
        logger.error(error_msg)
        return {"error": error_msg, "success": False}


@HUEY.periodic_task(crontab(hour="4", minute="0"), priority=5)  # Nightly sync at 4 AM
def nightly_health_data_sync() -> list[dict]:
    """
    Nightly health data synchronization for all active users
    Runs every night at 4:00 AM
    """
    logger.info("Starting nightly health data synchronization")

    # Get all active provider links
    active_links = ProviderLink.objects.filter(
        provider__active=True
    ).select_related("user", "provider")

    sync_results = []

    for link in active_links:
        try:
            # Validate provider is supported for health data
            if link.provider.provider_type not in [p.value for p in Provider]:
                logger.debug(f"Provider {link.provider.provider_type} not supported for health data sync")
                continue

            # Check for access token
            if not link.extra_data or "access_token" not in link.extra_data:
                logger.warning(f"No access token found for provider link {link.id}")
                continue

            # Queue incremental health data sync
            result = sync_user_health_data_incremental.delay(
                user_id=link.user.ehr_user_id,
                provider_name=link.provider.provider_type,
                data_types=["heart_rate", "steps"]  # Default types for Phase 1
            )

            sync_results.append({
                "user_id": link.user.ehr_user_id,
                "provider": link.provider.provider_type,
                "task_id": result.id,
                "status": "queued"
            })

            logger.debug(
                f"Queued nightly health data sync for user {link.user.ehr_user_id} "
                f"with {link.provider.provider_type}"
            )

        except Exception as e:
            error_result = {
                "error": f"Error processing provider link {link.id}: {e}",
                "success": False,
                "link_id": link.id
            }
            sync_results.append(error_result)
            logger.error(f"Error processing provider link {link.id}: {e}")

    logger.info(
        f"Nightly health data sync completed. "
        f"Queued {len(sync_results)} sync tasks"
    )
    return sync_results


def _update_provider_link_health_sync_info(user: EHRUser, provider: Provider, result) -> None:
    """Update provider link with health data sync information"""
    try:
        provider_link = ProviderLink.objects.filter(
            user=user,
            provider__provider_type=provider.value
        ).first()

        if provider_link:
            # Update extra_data with health sync information
            if not provider_link.extra_data:
                provider_link.extra_data = {}

            provider_link.extra_data.update({
                "last_health_data_sync": result.sync_timestamp,
                "last_health_sync_records_fetched": result.records_fetched,
                "last_health_sync_records_transformed": result.records_transformed,
                "last_health_sync_fhir_resources_created": result.fhir_resources_created,
                "last_health_sync_errors": len(result.errors),
                "last_health_sync_success": result.success,
                "last_health_sync_processing_time_ms": result.processing_time_ms
            })
            provider_link.save()
            logger.debug(f"Updated provider link {provider_link.id} with health sync information")

    except Exception as e:
        logger.error(f"Failed to update provider link health sync info: {e}")
        raise