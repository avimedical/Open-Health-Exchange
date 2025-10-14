"""
Health data constants and models for the sync system
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from django.utils import timezone

from .constants import Provider


class HealthDataType(StrEnum):
    """Types of health data we can sync"""

    HEART_RATE = "heart_rate"
    STEPS = "steps"
    RR_INTERVALS = "rr_intervals"
    HRV = "hrv"
    ECG = "ecg"
    BLOOD_PRESSURE = "blood_pressure"
    WEIGHT = "weight"
    TEMPERATURE = "temperature"
    SPO2 = "spo2"
    SLEEP = "sleep"
    PULSE_WAVE_VELOCITY = "pulse_wave_velocity"
    FAT_MASS = "fat_mass"


class AggregationLevel(StrEnum):
    """Data aggregation preferences"""

    INDIVIDUAL = "individual"  # Keep individual measurements
    HOURLY = "hourly"  # Aggregate into hourly summaries
    DAILY = "daily"  # Daily summaries


class SyncFrequency(StrEnum):
    """How often to sync data"""

    REALTIME = "realtime"  # Via push notifications
    HOURLY = "hourly"  # Every hour via cron
    DAILY = "daily"  # Once per day


class SyncTrigger(StrEnum):
    """What triggered this sync"""

    INITIAL = "initial"  # First-time sync
    INCREMENTAL = "incremental"  # Regular incremental sync
    WEBHOOK = "webhook"  # Push notification
    MANUAL = "manual"  # User-triggered


class MeasurementSource(StrEnum):
    """Source of measurement data"""

    DEVICE = "device"  # Automatic measurement by device
    USER = "user"  # Manually entered by user
    UNKNOWN = "unknown"  # Source not specified


@dataclass(slots=True, frozen=True)
class DateRange:
    """Date range for data queries"""

    start: datetime
    end: datetime

    def __post_init__(self):
        if self.start >= self.end:
            raise ValueError("Start date must be before end date")


@dataclass(slots=True)
class HealthDataRecord:
    """Raw health data record from provider"""

    provider: Provider
    user_id: str
    data_type: HealthDataType
    timestamp: datetime
    value: float | dict[str, Any]  # Simple value or complex data
    unit: str
    device_id: str | None = None
    metadata: dict[str, Any] | None = None
    measurement_source: MeasurementSource = MeasurementSource.UNKNOWN

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass(slots=True)
class HealthSyncConfig:
    """User-level sync configuration"""

    user_id: str
    enabled_data_types: list[HealthDataType]
    aggregation_preference: AggregationLevel
    sync_frequency: SyncFrequency
    retention_period: timedelta

    # Special linking rules (e.g., ECG always with heart rate)
    linked_data_rules: dict[HealthDataType, list[HealthDataType]] | None = None

    def __post_init__(self):
        if self.linked_data_rules is None:
            # Default linking rules
            self.linked_data_rules = {
                HealthDataType.ECG: [HealthDataType.HEART_RATE],
                HealthDataType.RR_INTERVALS: [HealthDataType.HEART_RATE],
                HealthDataType.HRV: [HealthDataType.HEART_RATE],
            }


@dataclass(slots=True)
class HealthSyncResult:
    """Result of health data synchronization"""

    user_id: str
    provider: Provider
    data_types: list[HealthDataType]
    trigger: SyncTrigger
    records_fetched: int = 0
    records_transformed: int = 0
    fhir_resources_created: int = 0
    errors: list[str] | None = None
    success: bool = False
    sync_timestamp: str | None = None
    processing_time_ms: int = 0

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.sync_timestamp is None:
            self.sync_timestamp = timezone.now().isoformat() + "Z"


# LOINC codes for health data types
HEALTH_DATA_LOINC_CODES = {
    HealthDataType.HEART_RATE: "8867-4",  # Heart rate
    HealthDataType.STEPS: "55423-8",  # Number of steps in unspecified time Pedometer
    HealthDataType.RR_INTERVALS: "8637-1",  # R-R interval
    HealthDataType.ECG: "8601-7",  # EKG impression
    HealthDataType.BLOOD_PRESSURE: "85354-9",  # Blood pressure panel with all children optional
    HealthDataType.WEIGHT: "29463-7",  # Body weight
    HealthDataType.TEMPERATURE: "8310-5",  # Body temperature
    HealthDataType.SPO2: "59408-5",  # Oxygen saturation in Arterial blood by Pulse oximetry
    HealthDataType.SLEEP: "93832-4",  # Sleep study
    HealthDataType.PULSE_WAVE_VELOCITY: "8494-7",  # Pulse wave velocity
    HealthDataType.FAT_MASS: "73708-0",  # Fat mass by DEXA
}

# UCUM units for health data types (aligned with mobile app BaseUnit)
# Maps display unit to UCUM code
HEALTH_DATA_UCUM_UNITS = {
    "bpm": "{beats}/min",  # beats per minute
    "cal": "cal",  # calories
    "cm": "cm",  # centimeter
    "count": "[count]",  # count (for steps)
    "steps": "[count]",  # steps (alternative mapping)
    "°C": "Cel",  # degrees Celsius (UCUM standard)
    "celsius": "Cel",  # Celsius (alternative)
    "kg": "kg",  # kilograms
    "kg/m²": "kg/m2",  # kilograms per square meter (BMI)
    "l": "L",  # liter
    "L": "L",  # liter (alternative)
    "m": "m",  # meter
    "uV": "uV",  # microvolt
    "mmol/l": "mmol/L",  # millimole per liter
    "mmol/L": "mmol/L",  # millimole per liter (alternative)
    "mmol/mol": "mmol/mol",  # millimole per mole
    "mg/dl": "mg/dL",  # milligram per deciliter
    "mg/dL": "mg/dL",  # milligram per deciliter (alternative)
    "mmHg": "mm[Hg]",  # millimeters of mercury (blood pressure)
    "ms": "ms",  # milliseconds
    "min": "min",  # minutes
    "minutes": "min",  # minutes (alternative)
    "%": "%",  # percentage
    # Legacy/additional units
    "lbs": "[lb_av]",  # pounds
    "fahrenheit": "[degF]",  # Fahrenheit
    "hours": "h",  # hours
    "h": "h",  # hours (alternative)
    "m/s": "m/s",  # meters per second
    "g": "g",  # grams
}

# Display names for health data types
HEALTH_DATA_DISPLAY_NAMES = {
    HealthDataType.HEART_RATE: "Heart rate",
    HealthDataType.STEPS: "Steps",
    HealthDataType.RR_INTERVALS: "R-R intervals",
    HealthDataType.HRV: "Heart rate variability",
    HealthDataType.ECG: "Electrocardiogram",
    HealthDataType.BLOOD_PRESSURE: "Blood pressure",
    HealthDataType.WEIGHT: "Body weight",
    HealthDataType.TEMPERATURE: "Body temperature",
    HealthDataType.SPO2: "Oxygen saturation",
    HealthDataType.SLEEP: "Sleep data",
    HealthDataType.PULSE_WAVE_VELOCITY: "Pulse wave velocity",
    HealthDataType.FAT_MASS: "Fat mass",
}

# FHIR observation categories
HEALTH_DATA_FHIR_CATEGORIES = {
    HealthDataType.HEART_RATE: "vital-signs",
    HealthDataType.STEPS: "activity",
    HealthDataType.RR_INTERVALS: "vital-signs",
    HealthDataType.HRV: "vital-signs",
    HealthDataType.ECG: "procedure",
    HealthDataType.BLOOD_PRESSURE: "vital-signs",
    HealthDataType.WEIGHT: "vital-signs",
    HealthDataType.TEMPERATURE: "vital-signs",
    HealthDataType.SPO2: "vital-signs",
    HealthDataType.SLEEP: "activity",
    HealthDataType.PULSE_WAVE_VELOCITY: "vital-signs",
    HealthDataType.FAT_MASS: "vital-signs",
}
