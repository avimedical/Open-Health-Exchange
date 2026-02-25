"""
Health data managers for fetching health data from different providers
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Protocol, cast, runtime_checkable

from django.contrib.auth import get_user_model
from social_django.models import UserSocialAuth

# Real API clients for Phase 2
from .api_clients import APIError, get_unified_health_data_client
from .constants import Provider
from .health_data_constants import (
    FHIR_UNITS,
    DateRange,
    HealthDataRecord,
    HealthDataType,
    MeasurementSource,
    SyncTrigger,
)

logger = logging.getLogger(__name__)
User = get_user_model()


@runtime_checkable
class HealthDataManager(Protocol):
    """Protocol for health data managers"""

    def fetch_health_data(
        self, user_id: str, data_types: list[HealthDataType], date_range: DateRange, sync_trigger: SyncTrigger
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
        self, user_id: str, data_types: list[HealthDataType], date_range: DateRange, sync_trigger: SyncTrigger
    ) -> list[HealthDataRecord]:
        """Fetch health data for user"""

    @abstractmethod
    def get_supported_data_types(self) -> list[HealthDataType]:
        """Get data types supported by this provider"""

    def _get_user_social_auth(self, user_id: str) -> UserSocialAuth:
        """Get user's social auth for this provider"""
        try:
            user = User.objects.get(ehr_user_id=user_id)
            return cast(UserSocialAuth, UserSocialAuth.objects.get(user=user, provider=self.provider.value))
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
        measurement_source: MeasurementSource = MeasurementSource.UNKNOWN,
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
            measurement_source=measurement_source,
        )


class WithingsHealthDataManager(BaseHealthDataManager):
    """Health data manager for Withings"""

    def __init__(self):
        super().__init__(Provider.WITHINGS)

    def get_supported_data_types(self) -> list[HealthDataType]:
        """Withings supports heart rate, steps, weight, blood pressure, ECG, temperature, SpO2, sleep, RR intervals"""
        return [
            HealthDataType.HEART_RATE,
            HealthDataType.STEPS,
            HealthDataType.WEIGHT,
            HealthDataType.BLOOD_PRESSURE,
            HealthDataType.ECG,
            HealthDataType.TEMPERATURE,
            HealthDataType.SPO2,
            HealthDataType.SLEEP,
            HealthDataType.RR_INTERVALS,
        ]

    def fetch_health_data(
        self, user_id: str, data_types: list[HealthDataType], date_range: DateRange, sync_trigger: SyncTrigger
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
                    records = self._fetch_data_type(client, user_id, data_type, date_range)
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
        client,  # UnifiedHealthDataClient
        user_id: str,
        data_type: HealthDataType,
        date_range: DateRange,
    ) -> list[HealthDataRecord]:
        """Fetch specific data type from Withings using the unified client API"""
        records = []

        try:
            # Use the unified client API to fetch data
            raw_data = client.get_health_data(Provider.WITHINGS, data_type, user_id, date_range)

            if data_type == HealthDataType.HEART_RATE:
                for measurement in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.HEART_RATE,
                        timestamp=measurement["timestamp"],
                        value=float(measurement["value"]),
                        unit=FHIR_UNITS["heart_rate"]["display"],
                        device_id=measurement.get("device_id"),
                        metadata={
                            "source": "withings_api",
                            "measurement_id": measurement.get("measurement_id"),
                            "category": measurement.get("category"),
                        },
                        measurement_source=measurement.get("measurement_source", MeasurementSource.UNKNOWN),
                    )
                    records.append(record)

            elif data_type == HealthDataType.STEPS:
                for activity in raw_data:
                    if activity.get("steps", 0) > 0:
                        record = self._create_health_record(
                            user_id=user_id,
                            data_type=HealthDataType.STEPS,
                            timestamp=activity["date"],
                            value=float(activity["steps"]),
                            unit=FHIR_UNITS["steps"]["display"],
                            device_id=activity.get("device_id"),
                            metadata={
                                "source": "withings_api",
                                "original_date": activity.get("original_date"),
                                "distance": activity.get("distance"),
                                "calories": activity.get("calories"),
                                "elevation": activity.get("elevation"),
                            },
                        )
                        records.append(record)

            elif data_type == HealthDataType.WEIGHT:
                for measurement in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.WEIGHT,
                        timestamp=measurement["timestamp"],
                        value=float(measurement["value"]),
                        unit=FHIR_UNITS["weight"]["display"],
                        device_id=measurement.get("device_id"),
                        metadata={
                            "source": "withings_api",
                            "measurement_id": measurement.get("measurement_id"),
                            "category": measurement.get("category"),
                        },
                        measurement_source=measurement.get("measurement_source", MeasurementSource.UNKNOWN),
                    )
                    records.append(record)

            elif data_type == HealthDataType.BLOOD_PRESSURE:
                for measurement in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.BLOOD_PRESSURE,
                        timestamp=measurement["timestamp"],
                        value=measurement["value"],
                        unit=FHIR_UNITS["blood_pressure"]["display"],
                        device_id=measurement.get("device_id"),
                        metadata={
                            "source": "withings_api",
                            "measurement_id": measurement.get("measurement_id"),
                            "category": measurement.get("category"),
                        },
                        measurement_source=measurement.get("measurement_source", MeasurementSource.UNKNOWN),
                    )
                    records.append(record)

            elif data_type == HealthDataType.ECG:
                for measurement in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.ECG,
                        timestamp=measurement["timestamp"],
                        value={
                            "heart_rate": measurement.get("heart_rate"),
                            "signal_id": measurement.get("signal_id"),
                            "afib_result": measurement.get("afib_result"),
                            "afib_classification": measurement.get("afib_classification"),
                        },
                        unit="uV",  # ECG waveform voltage - no FHIR_UNITS mapping needed
                        device_id=measurement.get("device_id"),
                        metadata={
                            "source": "withings_api",
                            "device_model": measurement.get("device_model"),
                            "modified": (measurement["modified"].isoformat() if measurement.get("modified") else None),
                            "qrs_interval": measurement.get("qrs_interval"),
                            "pr_interval": measurement.get("pr_interval"),
                            "qt_interval": measurement.get("qt_interval"),
                            "qtc_interval": measurement.get("qtc_interval"),
                        },
                        measurement_source=measurement.get("measurement_source", MeasurementSource.DEVICE),
                    )
                    records.append(record)

            elif data_type == HealthDataType.TEMPERATURE:
                for measurement in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.TEMPERATURE,
                        timestamp=measurement["timestamp"],
                        value=float(measurement["value"]),
                        unit=FHIR_UNITS["temperature"]["display"],
                        device_id=measurement.get("device_id"),
                        metadata={
                            "source": "withings_api",
                            "measurement_id": measurement.get("measurement_id"),
                            "category": measurement.get("category"),
                        },
                        measurement_source=measurement.get("measurement_source", MeasurementSource.UNKNOWN),
                    )
                    records.append(record)

            elif data_type == HealthDataType.SPO2:
                for measurement in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.SPO2,
                        timestamp=measurement["timestamp"],
                        value=float(measurement["value"]),
                        unit=FHIR_UNITS["spo2"]["display"],
                        device_id=measurement.get("device_id"),
                        metadata={
                            "source": "withings_api",
                            "measurement_id": measurement.get("measurement_id"),
                            "category": measurement.get("category"),
                        },
                        measurement_source=measurement.get("measurement_source", MeasurementSource.UNKNOWN),
                    )
                    records.append(record)

            elif data_type == HealthDataType.SLEEP:
                for measurement in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.SLEEP,
                        timestamp=measurement["timestamp"],
                        value={
                            "duration": measurement.get("duration"),
                            "deep_sleep_duration": measurement.get("deep_sleep_duration"),
                            "light_sleep_duration": measurement.get("light_sleep_duration"),
                            "rem_sleep_duration": measurement.get("rem_sleep_duration"),
                            "wake_up_count": measurement.get("wake_up_count"),
                        },
                        unit="seconds",
                        device_id=measurement.get("device_id"),
                        metadata={
                            "source": "withings_api",
                            "end_timestamp": (
                                measurement["end_timestamp"].isoformat() if measurement.get("end_timestamp") else None
                            ),
                        },
                        measurement_source=measurement.get("measurement_source", MeasurementSource.DEVICE),
                    )
                    records.append(record)

            elif data_type == HealthDataType.RR_INTERVALS:
                for measurement in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.RR_INTERVALS,
                        timestamp=measurement["timestamp"],
                        value=float(measurement["value"]),
                        unit=FHIR_UNITS["time_ms"]["display"],
                        device_id=measurement.get("device_id"),
                        metadata={
                            "source": "withings_api",
                            "hr": measurement.get("hr"),
                        },
                        measurement_source=measurement.get("measurement_source", MeasurementSource.DEVICE),
                    )
                    records.append(record)

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
            HealthDataType.RR_INTERVALS,
        ]

    def fetch_health_data(
        self, user_id: str, data_types: list[HealthDataType], date_range: DateRange, sync_trigger: SyncTrigger
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
                    records = self._fetch_data_type(client, user_id, data_type, date_range)
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
        client,  # UnifiedHealthDataClient
        user_id: str,
        data_type: HealthDataType,
        date_range: DateRange,
    ) -> list[HealthDataRecord]:
        """Fetch specific data type from Fitbit using the unified client API"""
        records = []

        try:
            # Use the unified client API to fetch data
            raw_data = client.get_health_data(Provider.FITBIT, data_type, user_id, date_range)

            if data_type == HealthDataType.HEART_RATE:
                for data_point in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.HEART_RATE,
                        timestamp=data_point["timestamp"],
                        value=float(data_point["value"]),
                        unit=FHIR_UNITS["heart_rate"]["display"],
                        device_id=data_point.get("device_id"),
                        metadata={
                            "source": "fitbit_api",
                            "heart_rate_type": data_point.get("heart_rate_type", "resting"),
                        },
                        measurement_source=data_point.get("measurement_source", MeasurementSource.UNKNOWN),
                    )
                    records.append(record)

            elif data_type == HealthDataType.STEPS:
                for data_point in raw_data:
                    if data_point.get("steps", 0) > 0:
                        record = self._create_health_record(
                            user_id=user_id,
                            data_type=HealthDataType.STEPS,
                            timestamp=data_point["date"],
                            value=float(data_point["steps"]),
                            unit=FHIR_UNITS["steps"]["display"],
                            device_id=data_point.get("device_id"),
                            metadata={"source": "fitbit_api"},
                            measurement_source=data_point.get("measurement_source", MeasurementSource.UNKNOWN),
                        )
                        records.append(record)

            elif data_type == HealthDataType.WEIGHT:
                for data_point in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.WEIGHT,
                        timestamp=data_point["timestamp"],
                        value=float(data_point["value"]),
                        unit=FHIR_UNITS["weight"]["display"],
                        device_id=data_point.get("device_id"),
                        metadata={
                            "source": "fitbit_api",
                            "fitbit_source": data_point.get("source"),
                            "log_id": data_point.get("log_id"),
                            "bmi": data_point.get("bmi"),
                        },
                        measurement_source=data_point.get("measurement_source", MeasurementSource.UNKNOWN),
                    )
                    records.append(record)

            elif data_type == HealthDataType.SLEEP:
                for data_point in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.SLEEP,
                        timestamp=data_point["timestamp"],
                        value=float(data_point["value"]),  # minutes asleep
                        unit=data_point.get("unit", FHIR_UNITS["time_min"]["display"]),
                        device_id=data_point.get("device_id"),
                        metadata={
                            "source": "fitbit_api",
                            "fitbit_log_type": data_point.get("log_type"),
                            "log_id": data_point.get("log_id"),
                            "end_time": (data_point["end_time"].isoformat() if data_point.get("end_time") else None),
                            "sleep_metrics": data_point.get("sleep_metrics", {}),
                        },
                        measurement_source=data_point.get("measurement_source", MeasurementSource.UNKNOWN),
                    )
                    records.append(record)

            elif data_type == HealthDataType.ECG:
                for data_point in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.ECG,
                        timestamp=data_point["timestamp"],
                        value={
                            "heart_rate": data_point.get("value"),
                            "ecg_metrics": data_point.get("ecg_metrics", {}),
                        },
                        unit=data_point.get("unit", "uV"),
                        device_id=data_point.get("device_id"),
                        metadata={
                            "source": "fitbit_api",
                            "ecg_metrics": data_point.get("ecg_metrics", {}),
                            "waveform_data": data_point.get("waveform_data", {}),
                        },
                        measurement_source=data_point.get("measurement_source", MeasurementSource.DEVICE),
                    )
                    records.append(record)

            elif data_type == HealthDataType.RR_INTERVALS:
                for data_point in raw_data:
                    record = self._create_health_record(
                        user_id=user_id,
                        data_type=HealthDataType.RR_INTERVALS,
                        timestamp=data_point["timestamp"],
                        value=float(data_point["value"]),  # RMSSD value
                        unit=data_point.get("unit", FHIR_UNITS["time_ms"]["display"]),
                        device_id=data_point.get("device_id"),
                        metadata={
                            "source": "fitbit_api",
                            "hrv_metrics": data_point.get("hrv_metrics", {}),
                            "data_source": "hrv_intraday",
                        },
                        measurement_source=data_point.get("measurement_source", MeasurementSource.DEVICE),
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

    _managers = {Provider.WITHINGS: WithingsHealthDataManager, Provider.FITBIT: FitbitHealthDataManager}

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
