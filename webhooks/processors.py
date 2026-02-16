"""
Webhook payload processors for different health data providers
Handles provider-specific webhook formats and extracts sync information
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from django.utils import dateparse, timezone

from base.models import ProviderLink
from ingestors.health_data_constants import HealthDataType, Provider

logger = logging.getLogger(__name__)


def _lookup_ehr_user_id(external_user_id: str, provider: Provider) -> str | None:
    """
    Look up the EHR user ID from the external provider user ID.
    Returns None if no matching ProviderLink is found.
    """
    try:
        provider_link = ProviderLink.objects.select_related("user").get(
            external_user_id=external_user_id,
            provider__provider_type=provider.value,
        )
        return provider_link.user.ehr_user_id
    except ProviderLink.DoesNotExist:
        logger.warning(f"No ProviderLink found for {provider.value} user {external_user_id}")
        return None
    except ProviderLink.MultipleObjectsReturned:
        # If multiple links exist, use the first one (shouldn't happen normally)
        found_link = (
            ProviderLink.objects.select_related("user")
            .filter(
                external_user_id=external_user_id,
                provider__provider_type=provider.value,
            )
            .first()
        )
        if found_link:
            logger.warning(f"Multiple ProviderLinks found for {provider.value} user {external_user_id}, using first")
            return found_link.user.ehr_user_id
        return None


class WebhookValidationError(Exception):
    """Raised when webhook payload validation fails"""


class WebhookPayloadProcessor:
    """Process webhook payloads from health data providers"""

    def process_withings_webhook(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Process Withings webhook notification

        Withings webhook structure:
        {
            "userid": 12345,
            "appli": 1,    # 1=weight, 4=activity, 16=sleep, 44=heart_rate, 50=ECG
            "callbackurl": "https://...",
            "comment": "user",
            "startdate": 1234567890,
            "enddate": 1234567891
        }
        """
        try:
            # Validate required fields
            required_fields = ["userid", "appli"]
            for field in required_fields:
                if field not in payload:
                    raise WebhookValidationError(f"Missing required field: {field}")

            external_user_id = str(payload["userid"])
            appli = int(payload["appli"])  # Convert to int for mapping lookup

            # Look up EHR user from external Withings user ID
            ehr_user_id = _lookup_ehr_user_id(external_user_id, Provider.WITHINGS)
            if not ehr_user_id:
                logger.warning(
                    f"Cannot process Withings webhook: no EHR user found for Withings user {external_user_id}"
                )
                return []

            # Use centralized provider mapping to resolve data types from appli type
            from ingestors.provider_mappings import get_category_to_data_types_mapping

            # Get mapping of appli types to data type names
            category_mapping = get_category_to_data_types_mapping(Provider.WITHINGS)
            data_type_names = category_mapping.get(str(appli), [])

            if not data_type_names:
                logger.warning(f"Withings webhook with unsupported appli type: {appli} (no data types configured)")
                return []

            # Convert data type names to HealthDataType enums
            data_types = []
            for data_type_name in data_type_names:
                try:
                    data_types.append(HealthDataType(data_type_name))
                except ValueError:
                    logger.warning(f"Unknown HealthDataType: {data_type_name}")

            logger.info(f"Resolved Withings appli {appli} to data types: {[dt.value for dt in data_types]}")

            # Extract date range if provided
            date_range = None
            if "startdate" in payload and "enddate" in payload:
                try:
                    start_time = datetime.fromtimestamp(int(payload["startdate"]), tz=UTC)
                    end_time = datetime.fromtimestamp(int(payload["enddate"]), tz=UTC)
                    date_range = {"start": start_time.isoformat(), "end": end_time.isoformat()}
                except (ValueError, OSError) as e:
                    logger.warning(f"Invalid date range in Withings webhook: {e}")

            # Default to recent sync window if no date range provided
            if not date_range:
                end_time = timezone.now()
                start_time = end_time - timedelta(hours=1)  # Last hour
                date_range = {"start": start_time.isoformat(), "end": end_time.isoformat()}

            sync_request = {
                "user_id": ehr_user_id,
                "provider": Provider.WITHINGS.value,
                "data_types": [dt.value for dt in data_types],
                "date_range": date_range,
                "trigger": "webhook",
                "appli_type": appli,
                "callback_url": payload.get("callbackurl"),
                "comment": payload.get("comment"),
                "external_user_id": external_user_id,
            }

            logger.info(
                f"Processed Withings webhook for EHR user {ehr_user_id} (Withings: {external_user_id}), appli {appli}, data types: {[dt.value for dt in data_types]}"
            )
            return [sync_request]

        except Exception as e:
            logger.error(f"Error processing Withings webhook: {e}")
            raise WebhookValidationError(f"Failed to process Withings webhook: {e}")

    def process_fitbit_webhook(self, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Process Fitbit webhook notifications

        Fitbit webhook structure (array of notifications):
        [
            {
                "collectionType": "activities",
                "date": "2023-01-15",
                "ownerId": "ABC123",
                "ownerType": "user",
                "subscriptionId": "1"
            }
        ]
        """
        try:
            if not isinstance(payload, list):
                raise WebhookValidationError("Fitbit webhook payload must be an array")

            sync_requests = []

            for notification in payload:
                try:
                    # Validate required fields
                    required_fields = ["collectionType", "date", "ownerId"]
                    for field in required_fields:
                        if field not in notification:
                            raise WebhookValidationError(f"Missing required field in notification: {field}")

                    external_user_id = notification["ownerId"]
                    collection_type = notification["collectionType"]
                    date_str = notification["date"]

                    # Handle user revocation
                    if collection_type == "userRevokedAccess":
                        logger.info(f"Fitbit user {external_user_id} revoked access")
                        # TODO: Handle user access revocation
                        continue

                    # Look up EHR user from external Fitbit user ID
                    ehr_user_id = _lookup_ehr_user_id(external_user_id, Provider.FITBIT)
                    if not ehr_user_id:
                        logger.warning(
                            f"Cannot process Fitbit webhook: no EHR user found for Fitbit user {external_user_id}"
                        )
                        continue

                    # Map Fitbit collection types to our data types
                    collection_mapping = {
                        "activities": [HealthDataType.STEPS, HealthDataType.HEART_RATE],
                        "body": [HealthDataType.WEIGHT],
                        "foods": [],  # Not implemented
                        "sleep": [],  # Not implemented yet
                    }

                    data_types = collection_mapping.get(collection_type, [])
                    if not data_types:
                        logger.warning(f"Fitbit webhook with unsupported collection type: {collection_type}")
                        continue

                    # Parse date and create time range
                    try:
                        sync_date = dateparse.parse_date(date_str)
                        if sync_date:
                            start_time = datetime.combine(sync_date, datetime.min.time(), tzinfo=UTC)
                            end_time = start_time + timedelta(days=1)
                        else:
                            raise ValueError(f"Could not parse date: {date_str}")
                    except ValueError as e:
                        logger.warning(f"Invalid date in Fitbit webhook: {date_str}, error: {e}")
                        # Fallback to recent sync window
                        end_time = timezone.now()
                        start_time = end_time - timedelta(hours=1)

                    date_range = {"start": start_time.isoformat(), "end": end_time.isoformat()}

                    sync_request = {
                        "user_id": ehr_user_id,
                        "provider": Provider.FITBIT.value,
                        "data_types": [dt.value for dt in data_types],
                        "date_range": date_range,
                        "trigger": "webhook",
                        "collection_type": collection_type,
                        "subscription_id": notification.get("subscriptionId"),
                        "owner_type": notification.get("ownerType", "user"),
                        "external_user_id": external_user_id,
                    }

                    sync_requests.append(sync_request)
                    logger.info(
                        f"Processed Fitbit webhook for EHR user {ehr_user_id} (Fitbit: {external_user_id}), collection {collection_type}, data types: {[dt.value for dt in data_types]}"
                    )

                except Exception as e:
                    logger.error(f"Error processing individual Fitbit notification: {e}")
                    # Continue processing other notifications

            logger.info(f"Processed Fitbit webhook with {len(sync_requests)} valid notifications")
            return sync_requests

        except Exception as e:
            logger.error(f"Error processing Fitbit webhook: {e}")
            raise WebhookValidationError(f"Failed to process Fitbit webhook: {e}")

    def process_generic_webhook(self, payload: dict[str, Any], provider: str) -> list[dict[str, Any]]:
        """
        Process generic webhook for future provider support

        Generic webhook structure:
        {
            "user_id": "12345",
            "provider": "omron",
            "data_types": ["blood_pressure"],
            "start_date": "2023-01-15T00:00:00Z",
            "end_date": "2023-01-15T23:59:59Z"
        }
        """
        try:
            # Validate required fields
            required_fields = ["user_id", "data_types"]
            for field in required_fields:
                if field not in payload:
                    raise WebhookValidationError(f"Missing required field: {field}")

            user_id = payload["user_id"]
            data_types = payload["data_types"]

            # Validate data types
            valid_data_types = []
            for dt in data_types:
                try:
                    health_data_type = HealthDataType(dt)
                    valid_data_types.append(health_data_type.value)
                except ValueError:
                    logger.warning(f"Invalid data type in generic webhook: {dt}")

            if not valid_data_types:
                raise WebhookValidationError("No valid data types found")

            # Extract or create date range
            date_range = None
            if "start_date" in payload and "end_date" in payload:
                date_range = {"start": payload["start_date"], "end": payload["end_date"]}
            else:
                # Default to last hour
                end_time = timezone.now()
                start_time = end_time - timedelta(hours=1)
                date_range = {"start": start_time.isoformat(), "end": end_time.isoformat()}

            sync_request = {
                "user_id": user_id,
                "provider": provider,
                "data_types": valid_data_types,
                "date_range": date_range,
                "trigger": "webhook",
            }

            logger.info(
                f"Processed generic webhook for provider {provider}, user {user_id}, data types: {valid_data_types}"
            )
            return [sync_request]

        except Exception as e:
            logger.error(f"Error processing generic webhook: {e}")
            raise WebhookValidationError(f"Failed to process generic webhook: {e}")
