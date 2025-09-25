"""
Modern unified health data manager - Provider-agnostic, type-safe
Replaces separate provider managers with unified batch operations
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Protocol, runtime_checkable

from django.conf import settings
from django.contrib.auth import get_user_model
from social_django.models import UserSocialAuth

from .api_clients import get_unified_health_data_client
from .constants import Provider
from .health_data_constants import (
    HealthDataType, HealthDataRecord, DateRange, SyncTrigger, MeasurementSource
)

logger = logging.getLogger(__name__)
User = get_user_model()


@dataclass(slots=True, frozen=True)
class HealthDataQuery:
    """Immutable health data query for batch operations"""
    provider: Provider
    user_id: str
    data_types: List[HealthDataType]
    date_range: DateRange
    sync_trigger: SyncTrigger

    @property
    def cache_key(self) -> str:
        """Generate cache key for this query"""
        start_str = self.date_range.start.strftime('%Y%m%d')
        end_str = self.date_range.end.strftime('%Y%m%d')
        data_types_str = '-'.join(sorted([dt.value for dt in self.data_types]))
        return f"health_manager:{self.provider.value}:{self.user_id}:{data_types_str}:{start_str}-{end_str}"


@runtime_checkable
class HealthDataManager(Protocol):
    """Protocol for health data managers"""

    def fetch_health_data(
        self,
        user_id: str,
        data_types: List[HealthDataType],
        date_range: DateRange,
        sync_trigger: SyncTrigger
    ) -> List[HealthDataRecord]:
        """Fetch health data for user"""
        ...

    def get_supported_data_types(self) -> List[HealthDataType]:
        """Get data types supported by this provider"""
        ...


class UnifiedHealthDataManager:
    """
    Modern health data manager using unified batch operations

    All operations go through a single core method for consistency
    Provider-agnostic design using settings configuration
    Unified error handling and data transformation
    """

    def __init__(self) -> None:
        self.config = settings.API_CLIENT_CONFIG
        self.client = get_unified_health_data_client()
        self.logger = logging.getLogger(__name__)

    def fetch_health_data(
        self,
        provider: Provider,
        user_id: str,
        data_types: List[HealthDataType],
        date_range: DateRange,
        sync_trigger: SyncTrigger
    ) -> List[HealthDataRecord]:
        """
        Fetch health data for a single provider
        Wrapper around unified batch method
        """
        if not data_types:
            return []

        query = HealthDataQuery(
            provider=provider,
            user_id=user_id,
            data_types=data_types,
            date_range=date_range,
            sync_trigger=sync_trigger
        )

        results = self.fetch_multiple_queries([query])
        return results.get(query.cache_key, [])

    def fetch_multiple_queries(self, queries: List[HealthDataQuery]) -> Dict[str, List[HealthDataRecord]]:
        """
        Unified method handling all health data fetching operations
        Single source of truth for data fetching, transformation, and error handling
        """
        if not queries:
            return {}

        results = {}

        for query in queries:
            try:
                # Validate supported data types
                supported_types = self._get_supported_data_types(query.provider)
                valid_data_types = [dt for dt in query.data_types if dt in supported_types]

                if not valid_data_types:
                    self.logger.warning(f"No supported data types for {query.provider.value}")
                    results[query.cache_key] = []
                    continue

                # Filter out unsupported types and warn
                unsupported = [dt for dt in query.data_types if dt not in supported_types]
                if unsupported:
                    self.logger.warning(f"Unsupported data types for {query.provider.value}: {unsupported}")

                # Fetch data for each supported type using unified client
                all_records = []

                for data_type in valid_data_types:
                    try:
                        # Use unified client to fetch raw data
                        raw_data = self.client.get_health_data(
                            provider=query.provider,
                            data_type=data_type,
                            user_id=query.user_id,
                            date_range=query.date_range
                        )

                        # Transform raw data to HealthDataRecord objects
                        records = self._transform_raw_data_to_records(
                            query.provider,
                            data_type,
                            query.user_id,
                            raw_data
                        )

                        all_records.extend(records)
                        self.logger.info(
                            f"Fetched {len(records)} {data_type.value} records from {query.provider.value}"
                        )

                    except Exception as e:
                        self.logger.error(
                            f"Error fetching {data_type.value} from {query.provider.value}: {e}"
                        )
                        # Continue with other data types

                results[query.cache_key] = all_records

            except Exception as e:
                self.logger.error(f"Failed to fetch health data for query {query.cache_key}: {e}")
                results[query.cache_key] = []

        return results

    def _get_supported_data_types(self, provider: Provider) -> List[HealthDataType]:
        """Get supported data types for provider from configuration"""
        provider_config = self.config.get('SUPPORTED_DATA_TYPES', {})

        # Default supported types if not in config
        default_types = {
            Provider.WITHINGS: [
                HealthDataType.HEART_RATE,
                HealthDataType.STEPS,
                HealthDataType.WEIGHT,
                HealthDataType.BLOOD_PRESSURE
            ],
            Provider.FITBIT: [
                HealthDataType.HEART_RATE,
                HealthDataType.STEPS,
                HealthDataType.WEIGHT,
                HealthDataType.SLEEP,
                HealthDataType.ECG,
                HealthDataType.RR_INTERVALS
            ]
        }

        # Get config values and convert string names to enum values
        config_types = provider_config.get(provider.value, [])
        if isinstance(config_types[0] if config_types else None, str):
            # Convert string names to HealthDataType enums
            enum_types = []
            for type_str in config_types:
                try:
                    enum_types.append(HealthDataType(type_str))
                except ValueError:
                    self.logger.warning(f"Unknown data type in config: {type_str}")
            return enum_types

        # Use defaults if config not found or empty
        return default_types.get(provider, [])

    def _transform_raw_data_to_records(
        self,
        provider: Provider,
        data_type: HealthDataType,
        user_id: str,
        raw_data: List[Dict]
    ) -> List[HealthDataRecord]:
        """Transform raw API data into HealthDataRecord objects"""
        records = []

        for item in raw_data:
            try:
                # Extract common fields using provider-agnostic logic
                record = self._create_health_record_from_raw(
                    provider=provider,
                    data_type=data_type,
                    user_id=user_id,
                    raw_item=item
                )
                if record:
                    records.append(record)

            except Exception as e:
                self.logger.error(f"Failed to transform raw data item: {e}")
                # Continue with other items

        return records

    def _create_health_record_from_raw(
        self,
        provider: Provider,
        data_type: HealthDataType,
        user_id: str,
        raw_item: Dict
    ) -> HealthDataRecord | None:
        """Create HealthDataRecord from raw API data using provider-agnostic mapping"""
        try:
            # Provider-agnostic field extraction using match statement
            match provider:
                case Provider.WITHINGS:
                    return self._create_withings_health_record(data_type, user_id, raw_item)
                case Provider.FITBIT:
                    return self._create_fitbit_health_record(data_type, user_id, raw_item)
                case _:
                    self.logger.error(f"Unsupported provider: {provider}")
                    return None

        except Exception as e:
            self.logger.error(f"Failed to create health record: {e}")
            return None

    def _create_withings_health_record(
        self,
        data_type: HealthDataType,
        user_id: str,
        raw_item: Dict
    ) -> HealthDataRecord | None:
        """Create HealthDataRecord from Withings raw data"""
        # Extract common Withings fields
        timestamp = raw_item.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        elif not isinstance(timestamp, datetime):
            return None

        value = raw_item.get('value')
        if value is None:
            return None

        # Get unit based on data type
        unit = self._get_unit_for_data_type(data_type)

        # Create metadata
        metadata = {
            'source': 'withings_api',
            'measurement_id': raw_item.get('measurement_id'),
            'category': raw_item.get('category')
        }

        return HealthDataRecord(
            provider=Provider.WITHINGS,
            user_id=user_id,
            data_type=data_type,
            timestamp=timestamp,
            value=float(value),
            unit=unit,
            device_id=raw_item.get('device_id'),
            metadata=metadata,
            measurement_source=raw_item.get('measurement_source', MeasurementSource.UNKNOWN)
        )

    def _create_fitbit_health_record(
        self,
        data_type: HealthDataType,
        user_id: str,
        raw_item: Dict
    ) -> HealthDataRecord | None:
        """Create HealthDataRecord from Fitbit raw data"""
        # Extract common Fitbit fields
        timestamp = raw_item.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        elif not isinstance(timestamp, datetime):
            # Try 'date' field for activity data
            date_value = raw_item.get('date')
            if isinstance(date_value, datetime):
                timestamp = date_value
            else:
                return None

        value = raw_item.get('value')
        if value is None:
            # Try data type specific fields
            match data_type:
                case HealthDataType.STEPS:
                    value = raw_item.get('steps')
                case HealthDataType.SLEEP:
                    value = raw_item.get('value', raw_item.get('minutes_asleep'))
                case _:
                    pass

        if value is None:
            return None

        # Get unit based on data type
        unit = self._get_unit_for_data_type(data_type)

        # Create metadata
        metadata = {
            'source': 'fitbit_api',
            'log_id': raw_item.get('log_id'),
            'heart_rate_type': raw_item.get('heart_rate_type'),
            'log_type': raw_item.get('log_type')
        }

        # Add specific metadata for different data types
        match data_type:
            case HealthDataType.SLEEP:
                metadata['sleep_metrics'] = raw_item.get('sleep_metrics', {})
            case HealthDataType.ECG:
                metadata['ecg_metrics'] = raw_item.get('ecg_metrics', {})
                metadata['waveform_data'] = raw_item.get('waveform_data', {})
            case HealthDataType.RR_INTERVALS:
                metadata['hrv_metrics'] = raw_item.get('hrv_metrics', {})

        return HealthDataRecord(
            provider=Provider.FITBIT,
            user_id=user_id,
            data_type=data_type,
            timestamp=timestamp,
            value=float(value),
            unit=unit,
            device_id=raw_item.get('device_id'),
            metadata=metadata,
            measurement_source=raw_item.get('measurement_source', MeasurementSource.UNKNOWN)
        )

    def _get_unit_for_data_type(self, data_type: HealthDataType) -> str:
        """Get standard unit for health data type"""
        unit_mapping = {
            HealthDataType.HEART_RATE: "bpm",
            HealthDataType.STEPS: "steps",
            HealthDataType.WEIGHT: "kg",
            HealthDataType.BLOOD_PRESSURE: "mmHg",
            HealthDataType.SLEEP: "minutes",
            HealthDataType.ECG: "bpm",
            HealthDataType.RR_INTERVALS: "ms"
        }
        return unit_mapping.get(data_type, "unknown")

    def get_supported_data_types(self, provider: Provider) -> List[HealthDataType]:
        """Get data types supported by provider"""
        return self._get_supported_data_types(provider)

    def get_manager_stats(self) -> Dict[str, any]:
        """Get manager configuration and status"""
        return {
            'supported_providers': [Provider.WITHINGS.value, Provider.FITBIT.value],
            'supported_data_types': {
                Provider.WITHINGS.value: [dt.value for dt in self._get_supported_data_types(Provider.WITHINGS)],
                Provider.FITBIT.value: [dt.value for dt in self._get_supported_data_types(Provider.FITBIT)]
            }
        }


# Global service instance
_unified_manager: UnifiedHealthDataManager | None = None


def get_unified_health_data_manager() -> UnifiedHealthDataManager:
    """Lazy singleton for global manager instance"""
    global _unified_manager
    if _unified_manager is None:
        _unified_manager = UnifiedHealthDataManager()
    return _unified_manager


# Provider-specific manager classes for interface compatibility
class ProviderHealthDataManager:
    """Provider-specific interface that delegates to unified manager"""

    def __init__(self, provider: Provider):
        self.provider = provider
        self.unified_manager = get_unified_health_data_manager()

    def get_supported_data_types(self) -> List[HealthDataType]:
        """Get data types supported by this provider"""
        return self.unified_manager.get_supported_data_types(self.provider)

    def fetch_health_data(
        self,
        user_id: str,
        data_types: List[HealthDataType],
        date_range: DateRange,
        sync_trigger: SyncTrigger
    ) -> List[HealthDataRecord]:
        """Fetch health data for this provider"""
        return self.unified_manager.fetch_health_data(
            provider=self.provider,
            user_id=user_id,
            data_types=data_types,
            date_range=date_range,
            sync_trigger=sync_trigger
        )


class HealthDataManagerFactory:
    """Factory for creating health data managers"""

    @staticmethod
    def get_manager(provider: Provider) -> HealthDataManager:
        """Get health data manager for provider"""
        return ProviderHealthDataManager(provider)

    @staticmethod
    def get_supported_providers() -> List[Provider]:
        """Get list of supported providers"""
        return [Provider.WITHINGS, Provider.FITBIT]