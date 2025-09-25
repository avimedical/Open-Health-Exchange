"""
Constants and enums for device management
"""
from enum import Enum, StrEnum
from dataclasses import dataclass
from typing import Dict, Any


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
            'high': cls.HIGH.value,
            'medium': cls.MEDIUM.value,
            'low': cls.LOW.value,
            'critical': cls.CRITICAL.value,
            'empty': cls.EMPTY.value,
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
    device_types_map: Dict[str, DeviceType]
    default_health_data_types: list[str]
    supports_webhooks: bool
    webhook_collection_types: Dict[str, list[str]]  # Maps data types to provider collection types


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
            "heart_rate", "steps", "weight", "blood_pressure",
            "ecg", "temperature", "spo2", "rr_intervals",
            "sleep", "pulse_wave_velocity", "fat_mass"
        ],
        supports_webhooks=True,
        webhook_collection_types={
            # Comprehensive Withings appli mappings
            "heart_rate": ["4", "44"],     # Activity (4) + Heart rate (44)
            "steps": ["4"],                # Activity data (4)
            "weight": ["1"],               # Weight scale (1)
            "blood_pressure": ["46"],      # Blood pressure monitor (46)
            "ecg": ["50"],                 # ECG device (50)
            "temperature": ["21"],         # Temperature (21)
            "spo2": ["54"],               # Oxygen saturation (54)
            "rr_intervals": ["44"],        # Heart rate variability (44)
            "sleep": ["16"],               # Sleep (16)
            "pulse_wave_velocity": ["60"], # Pulse wave velocity (60)
            "fat_mass": ["1"]              # Fat mass via body composition from scale (1)
        }
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
            "heart_rate", "steps", "weight", "temperature", "spo2", "sleep", "fat_mass",
            "ecg", "rr_intervals"
        ],
        supports_webhooks=True,
        webhook_collection_types={
            # Comprehensive Fitbit collection mappings
            "heart_rate": ["activities"],    # Activities collection includes heart rate
            "steps": ["activities"],         # Activities collection includes steps
            "weight": ["body"],             # Body collection for weight/BMI
            "temperature": ["body"],        # Body collection for temperature
            "spo2": ["activities"],         # Activities collection includes SpO2
            "sleep": ["sleep"],             # Sleep collection for sleep data
            "fat_mass": ["body"],           # Body collection for body composition
            "rr_intervals": ["activities"]  # HRV data may be available via activities webhooks
            # Note: ECG not included as it doesn't support webhook subscriptions
        }
    )
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
    raw_data: Dict[str, Any] | None = None

    def __post_init__(self):
        if self.raw_data is None:
            self.raw_data = {}