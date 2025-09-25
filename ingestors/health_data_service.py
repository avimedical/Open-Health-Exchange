"""
Health data synchronization service
"""
import logging
import time
from typing import Any
from datetime import datetime, timezone
from django.conf import settings

from .health_data_manager import HealthDataManagerFactory, HealthDataManager
from .health_sync_strategies import SyncStrategy, get_default_sync_strategy
from .health_data_constants import (
    Provider, HealthDataType, HealthSyncConfig, HealthSyncResult,
    SyncTrigger, HealthDataRecord, DateRange
)
from transformers.health_data_transformers import HealthDataTransformer
from publishers.fhir.health_data_publisher import HealthDataPublisher


logger = logging.getLogger(__name__)


class HealthDataSyncService:
    """Main health data synchronization service"""

    def __init__(self, fhir_publisher: HealthDataPublisher | None = None):
        self.fhir_publisher = fhir_publisher or HealthDataPublisher()
        self.transformer = HealthDataTransformer()
        self.logger = logging.getLogger(f"{__name__}.HealthDataSyncService")

    def sync_user_health_data(
        self,
        user_id: str,
        provider: Provider | str,
        data_types: list[HealthDataType],
        sync_strategy: SyncStrategy | None = None,
        config: HealthSyncConfig | None = None,
        patient_reference: str | None = None,
        device_reference: str | None = None
    ) -> HealthSyncResult:
        """
        Synchronize health data for a user from a specific provider

        Args:
            user_id: EHR user ID
            provider: Provider name or enum
            data_types: List of health data types to sync
            sync_strategy: Sync strategy (auto-detected if None)
            config: User sync configuration
            patient_reference: FHIR Patient reference (defaults to Patient/{user_id})
            device_reference: FHIR Device reference (optional)

        Returns:
            HealthSyncResult with details of the synchronization
        """
        start_time = time.time()

        # Convert provider to enum if needed
        if isinstance(provider, str):
            provider = Provider(provider)

        # Default patient reference
        if patient_reference is None:
            patient_reference = f"Patient/{user_id}"

        # Create default config if not provided
        if config is None:
            config = self._create_default_config(user_id, data_types)

        # Determine sync strategy
        if sync_strategy is None:
            # Check if user has synced before (simplified for Phase 1)
            user_has_synced_before = False  # TODO: Implement proper check
            sync_strategy = get_default_sync_strategy(user_has_synced_before)

        # Initialize result
        result = HealthSyncResult(
            user_id=user_id,
            provider=provider,
            data_types=data_types,
            trigger=sync_strategy.sync_trigger
        )

        try:
            self.logger.info(f"Starting health data sync for user {user_id} with {provider.value}")

            # 1. Get sync parameters
            sync_params = sync_strategy.get_sync_params(
                user_id, data_types, config
            )
            self.logger.debug(f"Sync parameters: {sync_params}")

            # 2. Fetch health data from provider
            health_records = self._fetch_health_data(
                user_id, provider, data_types, sync_params
            )
            result.records_fetched = len(health_records)

            if not health_records:
                self.logger.info(f"No health data found for user {user_id}")
                result.success = True
                return result

            self.logger.info(f"Fetched {len(health_records)} health records from {provider.value}")

            # 3. Transform to FHIR resources
            fhir_observations = self._transform_health_data(
                health_records, patient_reference, device_reference
            )
            result.records_transformed = len(fhir_observations)

            if not fhir_observations:
                self.logger.warning(f"No FHIR observations created from {len(health_records)} records")
                result.success = True
                return result

            self.logger.info(f"Transformed {len(fhir_observations)} health records to FHIR observations")

            # 4. Publish to FHIR server
            publish_result = self._publish_health_data(fhir_observations, sync_params)
            result.fhir_resources_created = publish_result.get("published_successfully", 0)

            # 5. Handle publishing errors
            if publish_result.get("errors"):
                assert result.errors is not None  # Initialized in __post_init__
                result.errors.extend(publish_result["errors"])

            # 6. Determine success
            result.success = (
                len(result.errors or []) == 0 and
                publish_result.get("success", False)
            )

            # 7. Calculate processing time
            result.processing_time_ms = int((time.time() - start_time) * 1000)

            self.logger.info(
                f"Health data sync completed for user {user_id}: "
                f"{result.records_fetched} fetched, "
                f"{result.records_transformed} transformed, "
                f"{result.fhir_resources_created} published, "
                f"{len(result.errors or [])} errors, "
                f"{result.processing_time_ms}ms"
            )

            return result

        except Exception as e:
            error_msg = f"Unexpected error in health data sync for user {user_id}: {e}"
            self.logger.error(error_msg)
            assert result.errors is not None  # Initialized in __post_init__
            result.errors.append(error_msg)
            result.processing_time_ms = int((time.time() - start_time) * 1000)
            return result

    def _create_default_config(
        self,
        user_id: str,
        data_types: list[HealthDataType]
    ) -> HealthSyncConfig:
        """Create default sync configuration"""
        from datetime import timedelta
        from .health_data_constants import AggregationLevel, SyncFrequency

        return HealthSyncConfig(
            user_id=user_id,
            enabled_data_types=data_types,
            aggregation_preference=AggregationLevel.INDIVIDUAL,  # No aggregation in Phase 1
            sync_frequency=SyncFrequency.DAILY,
            retention_period=timedelta(days=90)
        )

    def _fetch_health_data(
        self,
        user_id: str,
        provider: Provider,
        data_types: list[HealthDataType],
        sync_params: dict[str, Any]
    ) -> list[HealthDataRecord]:
        """Fetch health data from provider"""
        try:
            # Create health data manager for provider
            health_manager = HealthDataManagerFactory.create(provider)

            # Extract date range and sync trigger from params
            date_range = sync_params["date_range"]
            sync_trigger = sync_params["sync_trigger"]

            # Fetch data
            health_records = health_manager.fetch_health_data(
                user_id=user_id,
                data_types=data_types,
                date_range=date_range,
                sync_trigger=sync_trigger
            )

            return health_records

        except Exception as e:
            self.logger.error(f"Failed to fetch health data from {provider.value}: {e}")
            raise

    def _transform_health_data(
        self,
        health_records: list[HealthDataRecord],
        patient_reference: str,
        device_reference: str | None
    ) -> list[dict[str, Any]]:
        """Transform health data to FHIR observations"""
        try:
            fhir_observations = self.transformer.transform_multiple_records(
                records=health_records,
                patient_reference=patient_reference,
                device_reference=device_reference
            )

            return fhir_observations

        except Exception as e:
            self.logger.error(f"Failed to transform health data to FHIR: {e}")
            raise

    def _publish_health_data(
        self,
        fhir_observations: list[dict[str, Any]],
        sync_params: dict[str, Any]
    ) -> dict[str, Any]:
        """Publish FHIR observations to server"""
        try:
            # Get batch size from sync params
            batch_size = sync_params.get("batch_size", settings.BATCH_SIZES['PUBLISHER'])

            # Publish observations
            publish_result = self.fhir_publisher.publish_health_observations(
                observations=fhir_observations,
                batch_size=batch_size
            )

            return publish_result

        except Exception as e:
            self.logger.error(f"Failed to publish health data to FHIR server: {e}")
            raise

    def get_sync_statistics(self, user_id: str) -> dict[str, Any]:
        """Get synchronization statistics for a user"""
        try:
            patient_ref = f"Patient/{user_id}"

            # Get health data statistics from FHIR server
            stats = self.fhir_publisher.get_health_data_statistics(patient_ref)

            # Add user context
            stats["user_id"] = user_id
            stats["last_check"] = datetime.utcnow().isoformat()

            return stats

        except Exception as e:
            self.logger.error(f"Failed to get sync statistics for user {user_id}: {e}")
            return {
                "user_id": user_id,
                "error": str(e),
                "last_check": datetime.utcnow().isoformat()
            }

    def delete_user_health_data(
        self,
        user_id: str,
        provider: Provider | str
    ) -> dict[str, Any]:
        """Delete all health data for a user from a specific provider"""
        try:
            if isinstance(provider, str):
                provider = Provider(provider)

            patient_ref = f"Patient/{user_id}"

            result = self.fhir_publisher.delete_health_data_by_provider(
                patient_reference=patient_ref,
                provider=provider
            )

            self.logger.info(
                f"Deleted health data for user {user_id} from {provider.value}: "
                f"{result.get('deleted_count', 0)} observations"
            )

            return result

        except Exception as e:
            self.logger.error(f"Failed to delete health data for user {user_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "deleted_count": 0
            }


class MockHealthDataSyncService(HealthDataSyncService):
    """Mock health data sync service for testing"""

    def __init__(self):
        # Use real FHIR publisher for testing, but mock data fetching
        super().__init__(fhir_publisher=None)  # Will use default HealthDataPublisher
        self.published_observations = []
        self.mock_records = []

    def _fetch_health_data(
        self,
        user_id: str,
        provider: Provider,
        data_types: list[HealthDataType],
        sync_params: dict[str, Any]
    ) -> list[HealthDataRecord]:
        """Mock health data fetching"""
        if self.mock_records:
            return self.mock_records

        # Generate mock data
        from datetime import datetime, timedelta

        mock_records = []
        base_time = datetime.utcnow() - timedelta(hours=1)

        for i, data_type in enumerate(data_types):
            if data_type == HealthDataType.HEART_RATE:
                record = HealthDataRecord(
                    provider=provider,
                    user_id=user_id,
                    data_type=data_type,
                    timestamp=base_time + timedelta(minutes=i * 10),
                    value=72.0 + i,
                    unit="bpm",
                    metadata={"source": "mock"}
                )
            elif data_type == HealthDataType.STEPS:
                record = HealthDataRecord(
                    provider=provider,
                    user_id=user_id,
                    data_type=data_type,
                    timestamp=base_time + timedelta(minutes=i * 10),
                    value=1000.0 + i * 100,
                    unit="steps",
                    metadata={"source": "mock"}
                )
            else:
                continue  # Skip unsupported types in mock

            mock_records.append(record)

        return mock_records

    def _publish_health_data(
        self,
        fhir_observations: list[dict[str, Any]],
        sync_params: dict[str, Any]
    ) -> dict[str, Any]:
        """Publish to real FHIR server and store for inspection"""
        # Store observations for test inspection
        self.published_observations.extend(fhir_observations)

        # Use the real publisher
        return super()._publish_health_data(fhir_observations, sync_params)

    def set_mock_records(self, records: list[HealthDataRecord]):
        """Set mock records for testing"""
        self.mock_records = records