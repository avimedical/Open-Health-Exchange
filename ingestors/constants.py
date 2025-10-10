"""
Constants and enums for device management
"""

from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any


class DeviceType(StrEnum):
    """Standardized device types"""

    BP_MONITOR = "bp_monitor"
    SCALE = "scale"
    ACTIVITY_TRACKER = "activity_tracker"
    SMARTWATCH = "smartwatch"
    THERMOMETER = "thermometer"
    PULSE_OXIMETER = "pulse_oximeter"
    UNKNOWN = "unknown"


class BatteryLevel(Enum):
    """Battery level mappings from text to percentage"""

    HIGH = 80
    MEDIUM = 50
    LOW = 20
    CRITICAL = 5
    EMPTY = 5

    @classmethod
    def from_text(cls, text: str | None) -> int | None:
        """Convert battery text to percentage"""
        if not text:
            return None

        text_lower = text.lower()
        mapping = {
            "high": cls.HIGH.value,
            "medium": cls.MEDIUM.value,
            "low": cls.LOW.value,
            "critical": cls.CRITICAL.value,
            "empty": cls.EMPTY.value,
        }
        return mapping.get(text_lower)


class Provider(StrEnum):
    """Supported health data providers"""

    WITHINGS = "withings"
    FITBIT = "fitbit"


@dataclass(slots=True, frozen=True)
class ProviderConfig:
    """Configuration for a health data provider"""

    name: Provider
    client_id_setting: str
    client_secret_setting: str
    api_base_url: str
    device_endpoint: str
    device_types_map: dict[str, DeviceType]
    default_health_data_types: list[str]
    supports_webhooks: bool
    webhook_collection_types: dict[str, list[str]]  # Maps data types to provider collection types


# Provider configurations
PROVIDER_CONFIGS = {
    Provider.WITHINGS: ProviderConfig(
        name=Provider.WITHINGS,
        client_id_setting="SOCIAL_AUTH_WITHINGS_KEY",
        client_secret_setting="SOCIAL_AUTH_WITHINGS_SECRET",
        api_base_url="https://wbsapi.withings.net",
        device_endpoint="/v2/user",
        device_types_map={
            "Blood Pressure Monitor": DeviceType.BP_MONITOR,
            "Scale": DeviceType.SCALE,
            "Activity Tracker": DeviceType.ACTIVITY_TRACKER,
        },
        # Default: sync ALL available health data types (admin can opt-out)
        default_health_data_types=[
            "heart_rate",
            "steps",
            "weight",
            "blood_pressure",
            "ecg",
            "temperature",
            "spo2",
            "rr_intervals",
            "sleep",
            "pulse_wave_velocity",
            "fat_mass",
        ],
        supports_webhooks=True,
        webhook_collection_types={
            # Official Withings appli type mappings
            # Source: https://developer.withings.com/developer-guide/v3/data-api/keep-user-data-up-to-date/
            "weight": ["1"],  # Appli 1: Weight-related metrics (weight, fat mass, muscle mass)
            "fat_mass": ["1"],  # Appli 1: Fat mass via body composition
            "temperature": ["2"],  # Appli 2: Temperature-related data
            "blood_pressure": ["4"],  # Appli 4: Pressure-related data (BP, heart pulse, SPO2)
            "heart_rate": ["4"],  # Appli 4: Pressure-related data includes heart pulse
            "spo2": ["4"],  # Appli 4: Pressure-related data includes SPO2
            "steps": ["16"],  # Appli 16: Activity data (steps, distance, calories, workouts)
            "sleep": ["44"],  # Appli 44: Sleep-related data
            "rr_intervals": ["44"],  # Appli 44: Sleep data includes RR intervals
            "ecg": ["54"],  # Appli 54: ECG data (FIXED: was 50, correct is 54)
            "glucose": ["58"],  # Appli 58: Glucose data
            "pulse_wave_velocity": ["4"],  # Appli 4: Likely part of pressure-related measurements
        },
    ),
    Provider.FITBIT: ProviderConfig(
        name=Provider.FITBIT,
        client_id_setting="SOCIAL_AUTH_FITBIT_KEY",
        client_secret_setting="SOCIAL_AUTH_FITBIT_SECRET",
        api_base_url="https://api.fitbit.com",
        device_endpoint="/1/user/-/devices.json",
        device_types_map={
            "SCALE": DeviceType.SCALE,
            "TRACKER": DeviceType.ACTIVITY_TRACKER,
        },
        # Default: sync ALL available health data types (admin can opt-out)
        default_health_data_types=[
            "heart_rate",
            "steps",
            "weight",
            "temperature",
            "spo2",
            "sleep",
            "fat_mass",
            "ecg",
            "rr_intervals",
        ],
        supports_webhooks=True,
        webhook_collection_types={
            # Comprehensive Fitbit collection mappings
            "heart_rate": ["activities"],  # Activities collection includes heart rate
            "steps": ["activities"],  # Activities collection includes steps
            "weight": ["body"],  # Body collection for weight/BMI
            "temperature": ["body"],  # Body collection for temperature
            "spo2": ["activities"],  # Activities collection includes SpO2
            "sleep": ["sleep"],  # Sleep collection for sleep data
            "fat_mass": ["body"],  # Body collection for body composition
            "rr_intervals": ["activities"],  # HRV data may be available via activities webhooks
            # Note: ECG not included as it doesn't support webhook subscriptions
        },
    ),
}


@dataclass(slots=True)
class DeviceData:
    """Clean device data structure"""

    provider_device_id: str
    provider: Provider
    device_type: DeviceType
    manufacturer: str
    model: str
    battery_level: int | None = None
    last_sync: str | None = None
    firmware_version: str | None = None
    serial_number: str | None = None
    status: str = "active"
    raw_data: dict[str, Any] | None = None

    def __post_init__(self):
        if self.raw_data is None:
            self.raw_data = {}
