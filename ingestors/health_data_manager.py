"""
Health data managers for fetching health data from different providers
"""
import logging
from typing import Protocol, runtime_checkable
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

from social_django.models import UserSocialAuth
from django.contrib.auth import get_user_model

from .constants import Provider
from .health_data_constants import (
    HealthDataType, HealthDataRecord, DateRange, SyncTrigger, MeasurementSource
)
# Real API clients for Phase 2
from .api_clients import get_unified_health_data_client, APIError, TokenExpiredError


logger = logging.getLogger(__name__)
User = get_user_model()


@runtime_checkable
class HealthDataManager(Protocol):
    """Protocol for health data managers"""

    def fetch_health_data(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        date_range: DateRange,
        sync_trigger: SyncTrigger
    ) -> list[HealthDataRecord]:
        """Fetch health data for user"""
        ...

    def get_supported_data_types(self) -> list[HealthDataType]:
        """Get data types supported by this provider"""
        ...


class BaseHealthDataManager(ABC):
    """Base class for health data managers"""

    def __init__(self, provider: Provider):
        self.provider = provider
        self.logger = logging.getLogger(f"{__name__}.{provider.value.title()}HealthDataManager")

    @abstractmethod
    def fetch_health_data(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        date_range: DateRange,
        sync_trigger: SyncTrigger
    ) -> list[HealthDataRecord]:
        """Fetch health data for user"""
        pass

    @abstractmethod
    def get_supported_data_types(self) -> list[HealthDataType]:
        """Get data types supported by this provider"""
        pass

    def _get_user_social_auth(self, user_id: str) -> UserSocialAuth:
        """Get user's social auth for this provider"""
        try:
            user = User.objects.get(ehr_user_id=user_id)
            return UserSocialAuth.objects.get(
                user=user,
                provider=self.provider.value
            )
        except (User.DoesNotExist, UserSocialAuth.DoesNotExist) as e:
            raise ValueError(f"User {user_id} not found or not connected to {self.provider.value}") from e

    def _create_health_record(
        self,
        user_id: str,
        data_type: HealthDataType,
        timestamp: datetime,
        value: float | dict,
        unit: str,
        device_id: str | None = None,
        metadata: dict | None = None,
        measurement_source: MeasurementSource = MeasurementSource.UNKNOWN
    ) -> HealthDataRecord:
        """Create a standardized health data record"""
        return HealthDataRecord(
            provider=self.provider,
            user_id=user_id,
            data_type=data_type,
            timestamp=timestamp,
            value=value,
            unit=unit,
            device_id=device_id,
            metadata=metadata or {},
            measurement_source=measurement_source
        )


class WithingsHealthDataManager(BaseHealthDataManager):
    """Health data manager for Withings"""

    def __init__(self):
        super().__init__(Provider.WITHINGS)

    def get_supported_data_types(self) -> list[HealthDataType]:
        """Withings supports heart rate, steps, weight, blood pressure"""
        return [
            HealthDataType.HEART_RATE,
            HealthDataType.STEPS,
            HealthDataType.WEIGHT,
            HealthDataType.BLOOD_PRESSURE
        ]

    def fetch_health_data(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        date_range: DateRange,
        sync_trigger: SyncTrigger
    ) -> list[HealthDataRecord]:
        """Fetch health data from Withings API"""
        try:
            # Create real API client
            client = get_unified_health_data_client()

            # Fetch data for each requested type
            all_records = []

            for data_type in data_types:
                if data_type not in self.get_supported_data_types():
                    self.logger.warning(f"Data type {data_type} not supported by Withings")
                    continue

                try:
                    records = self._fetch_data_type(
                        client, user_id, data_type, date_range
                    )
                    all_records.extend(records)
                    self.logger.info(f"Fetched {len(records)} {data_type} records from Withings")
                except APIError as e:
                    self.logger.error(f"API error fetching {data_type} from Withings: {e}")
                    # Continue with other data types
                except Exception as e:
                    self.logger.error(f"Unexpected error fetching {data_type} from Withings: {e}")

            return all_records

        except APIError as e:
            self.logger.error(f"API error fetching Withings health data for user {user_id}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error fetching Withings health data for user {user_id}: {e}")
            raise

    def _fetch_data_type(
        self,
        client,  # Real WithingsAPIClient for Phase 2
        user_id: str,
        data_type: HealthDataType,
        date_range: DateRange
    ) -> list[HealthDataRecord]:
        """Fetch specific data type from Withings"""
        records = []

        try:
            if data_type == HealthDataType.HEART_RATE:
                # Fetch heart rate measurements
                measurements = client.get_heart_rate_data(user_id, date_range.start, date_range.end)
                for measurement in measurements:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.HEART_RATE,
                        timestamp=measurement['timestamp'],
                        value=float(measurement['value']),
                        unit="bpm",
                        device_id=measurement.get('device_id'),
                        metadata={
                            'source': 'withings_api',
                            'measurement_id': measurement.get('measurement_id'),
                            'category': measurement.get('category')
                        },
                        measurement_source=measurement.get('measurement_source', MeasurementSource.UNKNOWN)
                    )
                    records.append(record)

            elif data_type == HealthDataType.STEPS:
                # Fetch activity measurements (steps)
                activities = client.get_activity_data(user_id, date_range.start, date_range.end)
                for activity in activities:
                    if activity.get('steps', 0) > 0:
                        record = self._create_health_record(
                            user_id=user_id,
                            data_type=HealthDataType.STEPS,
                            timestamp=activity['date'],
                            value=float(activity['steps']),
                            unit="steps",
                            device_id=activity.get('device_id'),
                            metadata={
                                'source': 'withings_api',
                                'distance': activity.get('distance'),
                                'calories': activity.get('calories'),
                                'elevation': activity.get('elevation')
                            }
                        )
                        records.append(record)

            elif data_type == HealthDataType.WEIGHT:
                # Fetch weight measurements
                measurements = client.get_weight_data(user_id, date_range.start, date_range.end)
                for measurement in measurements:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.WEIGHT,
                        timestamp=measurement['timestamp'],
                        value=float(measurement['value']),
                        unit="kg",
                        device_id=measurement.get('device_id'),
                        metadata={
                            'source': 'withings_api',
                            'measurement_id': measurement.get('measurement_id'),
                            'category': measurement.get('category')
                        },
                        measurement_source=measurement.get('measurement_source', MeasurementSource.UNKNOWN)
                    )
                    records.append(record)

            elif data_type == HealthDataType.BLOOD_PRESSURE:
                # Note: Blood pressure not implemented in current API client
                # Would need additional Withings API calls for blood pressure data
                self.logger.warning("Blood pressure data not yet implemented for real Withings API")

        except APIError as e:
            self.logger.error(f"API error fetching {data_type} from Withings: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error processing {data_type} data from Withings: {e}")
            raise

        return records


class FitbitHealthDataManager(BaseHealthDataManager):
    """Health data manager for Fitbit"""

    def __init__(self):
        super().__init__(Provider.FITBIT)

    def get_supported_data_types(self) -> list[HealthDataType]:
        """Fitbit supports heart rate, steps, weight, sleep, ECG, and HRV"""
        return [
            HealthDataType.HEART_RATE,
            HealthDataType.STEPS,
            HealthDataType.WEIGHT,
            HealthDataType.SLEEP,
            HealthDataType.ECG,
            HealthDataType.RR_INTERVALS
        ]

    def fetch_health_data(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        date_range: DateRange,
        sync_trigger: SyncTrigger
    ) -> list[HealthDataRecord]:
        """Fetch health data from Fitbit API"""
        try:
            # Create real API client
            client = get_unified_health_data_client()

            # Fetch data for each requested type
            all_records = []

            for data_type in data_types:
                if data_type not in self.get_supported_data_types():
                    self.logger.warning(f"Data type {data_type} not supported by Fitbit")
                    continue

                try:
                    records = self._fetch_data_type(
                        client, user_id, data_type, date_range
                    )
                    all_records.extend(records)
                    self.logger.info(f"Fetched {len(records)} {data_type} records from Fitbit")
                except APIError as e:
                    self.logger.error(f"API error fetching {data_type} from Fitbit: {e}")
                    # Continue with other data types
                except Exception as e:
                    self.logger.error(f"Unexpected error fetching {data_type} from Fitbit: {e}")

            return all_records

        except APIError as e:
            self.logger.error(f"API error fetching Fitbit health data for user {user_id}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error fetching Fitbit health data for user {user_id}: {e}")
            raise

    def _fetch_data_type(
        self,
        client,  # Real FitbitAPIClient for Phase 2
        user_id: str,
        data_type: HealthDataType,
        date_range: DateRange
    ) -> list[HealthDataRecord]:
        """Fetch specific data type from Fitbit"""
        records = []

        try:
            if data_type == HealthDataType.HEART_RATE:
                # Fetch heart rate data
                heart_rate_data = client.get_heart_rate_data(
                    user_id, date_range.start, date_range.end
                )
                for data_point in heart_rate_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.HEART_RATE,
                        timestamp=data_point['timestamp'],
                        value=float(data_point['value']),
                        unit="bpm",
                        device_id=data_point.get('device_id'),
                        metadata={
                            'source': 'fitbit_api',
                            'heart_rate_type': data_point.get('heart_rate_type', 'resting')
                        },
                        measurement_source=data_point.get('measurement_source', MeasurementSource.UNKNOWN)
                    )
                    records.append(record)

            elif data_type == HealthDataType.STEPS:
                # Fetch steps data
                steps_data = client.get_activity_data(
                    user_id, date_range.start, date_range.end
                )
                for data_point in steps_data:
                    if data_point.get('steps', 0) > 0:
                        record = self._create_health_record(
                            user_id=user_id,
                            data_type=HealthDataType.STEPS,
                            timestamp=data_point['date'],
                            value=float(data_point['steps']),
                            unit="steps",
                            device_id=data_point.get('device_id'),
                            metadata={'source': 'fitbit_api'},
                            measurement_source=data_point.get('measurement_source', MeasurementSource.UNKNOWN)
                        )
                        records.append(record)

            elif data_type == HealthDataType.WEIGHT:
                # Fetch weight data
                weight_data = client.get_weight_data(
                    user_id, date_range.start, date_range.end
                )
                for data_point in weight_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.WEIGHT,
                        timestamp=data_point['timestamp'],
                        value=float(data_point['value']),
                        unit="kg",
                        device_id=data_point.get('device_id'),
                        metadata={
                            'source': 'fitbit_api',
                            'fitbit_source': data_point.get('source'),
                            'log_id': data_point.get('log_id'),
                            'bmi': data_point.get('bmi')
                        },
                        measurement_source=data_point.get('measurement_source', MeasurementSource.UNKNOWN)
                    )
                    records.append(record)

            elif data_type == HealthDataType.SLEEP:
                # Fetch sleep data
                sleep_data = client.get_sleep_data(
                    user_id, date_range.start, date_range.end
                )
                for data_point in sleep_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.SLEEP,
                        timestamp=data_point['timestamp'],
                        value=float(data_point['value']),  # minutes asleep
                        unit=data_point['unit'],
                        device_id=data_point.get('device_id'),
                        metadata={
                            'source': 'fitbit_api',
                            'fitbit_log_type': data_point.get('log_type'),
                            'log_id': data_point.get('log_id'),
                            'end_time': data_point.get('end_time'),
                            'sleep_metrics': data_point.get('sleep_metrics', {})
                        },
                        measurement_source=data_point.get('measurement_source', MeasurementSource.UNKNOWN)
                    )
                    records.append(record)

            elif data_type == HealthDataType.ECG:
                # Fetch ECG data
                ecg_data = client.get_ecg_data(
                    user_id, date_range.start, date_range.end
                )
                for data_point in ecg_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.ECG,
                        timestamp=data_point['timestamp'],
                        value=float(data_point['value']),  # average heart rate
                        unit=data_point['unit'],
                        device_id=data_point.get('device_id'),
                        metadata={
                            'source': 'fitbit_api',
                            'ecg_metrics': data_point.get('ecg_metrics', {}),
                            'waveform_data': data_point.get('waveform_data', {})
                        },
                        measurement_source=data_point.get('measurement_source', MeasurementSource.UNKNOWN)
                    )
                    records.append(record)

            elif data_type == HealthDataType.RR_INTERVALS:
                # Fetch HRV data (Heart Rate Variability maps to RR_INTERVALS)
                hrv_data = client.get_hrv_data(
                    user_id, date_range.start, date_range.end
                )
                for data_point in hrv_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.RR_INTERVALS,
                        timestamp=data_point['timestamp'],
                        value=float(data_point['value']),  # RMSSD value
                        unit=data_point['unit'],
                        device_id=data_point.get('device_id'),
                        metadata={
                            'source': 'fitbit_api',
                            'hrv_metrics': data_point.get('hrv_metrics', {}),
                            'data_source': 'hrv_intraday'
                        },
                        measurement_source=data_point.get('measurement_source', MeasurementSource.UNKNOWN)
                    )
                    records.append(record)

        except APIError as e:
            self.logger.error(f"API error fetching {data_type} from Fitbit: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error processing {data_type} data from Fitbit: {e}")
            raise

        return records


class HealthDataManagerFactory:
    """Factory for creating health data managers"""

    _managers = {
        Provider.WITHINGS: WithingsHealthDataManager,
        Provider.FITBIT: FitbitHealthDataManager
    }

    @classmethod
    def create(cls, provider: Provider) -> HealthDataManager:
        """Create a health data manager for the given provider"""
        if provider not in cls._managers:
            raise ValueError(f"Unsupported health data provider: {provider}")

        return cls._managers[provider]()

    @classmethod
    def get_supported_providers(cls) -> list[Provider]:
        """Get list of supported providers"""
        return list(cls._managers.keys())

    @classmethod
    def get_supported_data_types(cls, provider: Provider) -> list[HealthDataType]:
        """Get supported data types for a provider"""
        manager = cls.create(provider)
        return manager.get_supported_data_types()


# ============================================================================
# REAL API INTEGRATION FOR PHASE 2
# ============================================================================
# Mock API clients have been replaced with real API implementations in api_clients.py
# Real API clients handle:
# - OAuth2 token management and refresh
# - Rate limiting and retry logic
# - Production API error handling
# - Real data format mapping