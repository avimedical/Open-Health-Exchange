# Health Data Sync - Code Examples

This document provides comprehensive code examples demonstrating the health data synchronization architecture patterns and implementations.

## Core Data Types and Models

### Health Data Types
```python
from enum import StrEnum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, Any, Optional
from abc import ABC, abstractmethod

class HealthDataType(StrEnum):
    """Types of health data we can sync"""
    HEART_RATE = "heart_rate"
    STEPS = "steps"
    RR_INTERVALS = "rr_intervals"
    ECG = "ecg"
    BLOOD_PRESSURE = "blood_pressure"
    WEIGHT = "weight"
    TEMPERATURE = "temperature"
    SPO2 = "spo2"

class AggregationLevel(StrEnum):
    """Data aggregation preferences"""
    INDIVIDUAL = "individual"  # Keep individual measurements
    HOURLY = "hourly"         # Aggregate into hourly summaries
    DAILY = "daily"           # Daily summaries

class SyncFrequency(StrEnum):
    """How often to sync data"""
    REALTIME = "realtime"     # Via push notifications
    HOURLY = "hourly"         # Every hour via cron
    DAILY = "daily"           # Once per day
```

### Core Data Models
```python
@dataclass(slots=True)
class HealthDataRecord:
    """Raw health data record from provider"""
    provider: str
    user_id: str
    data_type: HealthDataType
    timestamp: datetime
    value: float | dict[str, Any]  # Simple value or complex data
    unit: str
    device_id: str | None = None
    metadata: dict[str, Any] | None = None

@dataclass(slots=True)
class DateRange:
    """Date range for data queries"""
    start: datetime
    end: datetime

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
```

## Sync Strategies

### Strategy Protocol
```python
class SyncStrategy(Protocol):
    """Protocol for different sync strategies"""

    def get_sync_params(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        last_sync: datetime | None = None
    ) -> dict[str, Any]:
        """Get parameters for this sync strategy"""
        ...
```

### Initial Sync Strategy
```python
class InitialSyncStrategy:
    """Strategy for initial historical data sync"""

    def __init__(self, lookback_days: int = 30):
        self.lookback_days = lookback_days

    def get_sync_params(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        last_sync: datetime | None = None
    ) -> dict[str, Any]:
        """Get full historical sync parameters"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=self.lookback_days)

        return {
            "sync_type": "initial",
            "date_range": DateRange(start_date, end_date),
            "include_all_records": True,
            "batch_size": 1000,  # Larger batches for historical data
        }
```

### Incremental Sync Strategy
```python
class IncrementalSyncStrategy:
    """Strategy for incremental updates since last sync"""

    def get_sync_params(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        last_sync: datetime | None = None
    ) -> dict[str, Any]:
        """Get incremental sync parameters"""
        if last_sync is None:
            # Fallback to recent data if no last sync
            start_date = datetime.utcnow() - timedelta(hours=24)
        else:
            # Small overlap to handle timezone issues
            start_date = last_sync - timedelta(minutes=5)

        return {
            "sync_type": "incremental",
            "date_range": DateRange(start_date, datetime.utcnow()),
            "include_all_records": False,
            "batch_size": 100,  # Smaller batches for recent data
        }
```

### Push Notification Sync Strategy
```python
class PushNotificationSyncStrategy:
    """Strategy for real-time webhook-triggered sync"""

    def get_sync_params(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        last_sync: datetime | None = None
    ) -> dict[str, Any]:
        """Get real-time sync parameters"""
        # Only sync very recent data for webhooks
        start_date = datetime.utcnow() - timedelta(minutes=15)

        return {
            "sync_type": "realtime",
            "date_range": DateRange(start_date, datetime.utcnow()),
            "include_all_records": False,
            "batch_size": 50,  # Small batches for real-time
            "priority": "high"
        }
```

## FHIR Transformation Examples

### Health Data Transformer
```python
class HealthDataTransformer:
    """Transforms health data to FHIR R5 resources"""

    def __init__(self):
        # LOINC codes for different measurement types
        self.loinc_codes = {
            HealthDataType.HEART_RATE: "8867-4",
            HealthDataType.STEPS: "55423-8",
            HealthDataType.RR_INTERVALS: "8637-1",
            HealthDataType.ECG: "11524-6",
            HealthDataType.BLOOD_PRESSURE: "85354-9",
            HealthDataType.WEIGHT: "29463-7",
            HealthDataType.SPO2: "59408-5"
        }

        # Units mapping
        self.ucum_units = {
            "bpm": "/min",      # beats per minute
            "steps": "1",       # count
            "ms": "ms",         # milliseconds
            "mmHg": "mm[Hg]",   # blood pressure
            "kg": "kg",         # weight
            "%": "%"            # percentage
        }
```

### Heart Rate Transformation
```python
    def transform_heart_rate(
        self,
        record: HealthDataRecord,
        patient_ref: str,
        device_ref: str
    ) -> dict[str, Any]:
        """Transform heart rate measurement to FHIR Observation"""

        return {
            "resourceType": "Observation",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "vital-signs",
                    "display": "Vital Signs"
                }]
            }],
            "code": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": self.loinc_codes[HealthDataType.HEART_RATE],
                    "display": "Heart rate"
                }],
                "text": "Heart rate"
            },
            "subject": {"reference": patient_ref},
            "device": {"reference": device_ref},
            "effectiveDateTime": record.timestamp.isoformat() + "Z",
            "valueQuantity": {
                "value": record.value,
                "unit": "beats/minute",
                "system": "http://unitsofmeasure.org",
                "code": "/min"
            },
            "component": []  # May be populated with RR intervals
        }
```

### ECG with Heart Rate Transformation
```python
    def transform_ecg_with_heart_rate(
        self,
        ecg_record: HealthDataRecord,
        heart_rate_record: HealthDataRecord,
        patient_ref: str,
        device_ref: str
    ) -> dict[str, Any]:
        """Transform ECG with linked heart rate to FHIR DiagnosticReport"""

        # Create heart rate observation first
        hr_observation = self.transform_heart_rate(
            heart_rate_record, patient_ref, device_ref
        )

        # Create ECG diagnostic report
        diagnostic_report = {
            "resourceType": "DiagnosticReport",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                    "code": "CG",
                    "display": "Cardiodiagnostics"
                }]
            }],
            "code": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": self.loinc_codes[HealthDataType.ECG],
                    "display": "12 lead EKG panel"
                }],
                "text": "Electrocardiogram"
            },
            "subject": {"reference": patient_ref},
            "device": {"reference": device_ref},
            "effectiveDateTime": ecg_record.timestamp.isoformat() + "Z",
            "result": [
                {"reference": f"Observation/{hr_observation.get('id', 'temp-hr')}"}
            ],
            "media": []
        }

        # Add ECG waveform data if available
        if isinstance(ecg_record.value, dict) and "waveform" in ecg_record.value:
            media_list = diagnostic_report["media"]
            if isinstance(media_list, list):
                media_list.append({
                "comment": "ECG waveform data",
                "link": {
                    "contentType": "application/json",
                        "data": str(ecg_record.value["waveform"])  # Base64 encoded in real implementation
                    }
                })

        return {
            "diagnostic_report": diagnostic_report,
            "linked_observations": [hr_observation]
        }
```

## Aggregation Engine Example

### Hourly Aggregator
```python
class HourlyAggregator:
    """Aggregates individual measurements into hourly summaries"""

    def aggregate_heart_rate(
        self,
        records: list[HealthDataRecord]
    ) -> list[HealthDataRecord]:
        """Aggregate heart rate measurements by hour"""

        # Group by hour
        hourly_groups: dict[datetime, list[HealthDataRecord]] = {}

        for record in records:
            # Round down to the hour
            hour_key = record.timestamp.replace(minute=0, second=0, microsecond=0)

            if hour_key not in hourly_groups:
                hourly_groups[hour_key] = []
            hourly_groups[hour_key].append(record)

        # Create aggregated records
        aggregated_records = []

        for hour, hour_records in hourly_groups.items():
            if not hour_records:
                continue

            # Calculate statistics
            values = [float(r.value) if isinstance(r.value, (int, float, str)) else 0.0 for r in hour_records]
            avg_hr = sum(values) / len(values)
            min_hr = min(values)
            max_hr = max(values)

            # Create aggregated record
            agg_record = HealthDataRecord(
                provider=hour_records[0].provider,
                user_id=hour_records[0].user_id,
                data_type=HealthDataType.HEART_RATE,
                timestamp=hour,
                value={
                    "average": round(avg_hr, 1),
                    "minimum": min_hr,
                    "maximum": max_hr,
                    "count": len(values)
                },
                unit="bpm",
                device_id=hour_records[0].device_id,
                metadata={
                    "aggregation": "hourly",
                    "source_records": len(hour_records)
                }
            )

            aggregated_records.append(agg_record)

        return aggregated_records
```

## Usage Examples

### Initial Sync Example
```python
def example_initial_sync():
    """Example: Initial sync for a new user"""

    # User configuration
    config = HealthSyncConfig(
        user_id="user-123",
        enabled_data_types=[HealthDataType.HEART_RATE, HealthDataType.STEPS],
        aggregation_preference=AggregationLevel.HOURLY,
        sync_frequency=SyncFrequency.DAILY,
        retention_period=timedelta(days=90)
    )

    # Initial sync strategy
    strategy = InitialSyncStrategy(lookback_days=30)
    sync_params = strategy.get_sync_params(
        config.user_id,
        config.enabled_data_types
    )

    print("Initial Sync Parameters:")
    print(f"  Date Range: {sync_params['date_range'].start} to {sync_params['date_range'].end}")
    print(f"  Batch Size: {sync_params['batch_size']}")
    print(f"  Sync Type: {sync_params['sync_type']}")
```

### ECG with Heart Rate Example
```python
def example_ecg_with_heart_rate():
    """Example: ECG measurement with linked heart rate"""

    # Sample ECG record
    ecg_record = HealthDataRecord(
        provider="fitbit",
        user_id="user-123",
        data_type=HealthDataType.ECG,
        timestamp=datetime.utcnow(),
        value={
            "waveform": [1.2, 1.5, 2.1, 1.8, 1.3],  # Simplified waveform
            "analysis": "Normal sinus rhythm"
        },
        unit="mV",
        device_id="fitbit-sense-456"
    )

    # Corresponding heart rate
    hr_record = HealthDataRecord(
        provider="fitbit",
        user_id="user-123",
        data_type=HealthDataType.HEART_RATE,
        timestamp=datetime.utcnow(),
        value=72.0,
        unit="bpm",
        device_id="fitbit-sense-456"
    )

    # Transform to FHIR
    transformer = HealthDataTransformer()
    fhir_bundle = transformer.transform_ecg_with_heart_rate(
        ecg_record, hr_record,
        "Patient/user-123",
        "Device/fitbit-sense-456"
    )

    print("ECG + Heart Rate FHIR Bundle:")
    print(f"  DiagnosticReport: {fhir_bundle['diagnostic_report']['resourceType']}")
    print(f"  Linked Observations: {len(fhir_bundle['linked_observations'])}")
```

### Hourly Aggregation Example
```python
def example_hourly_aggregation():
    """Example: Aggregating heart rate data by hour"""

    # Sample individual heart rate measurements
    base_time = datetime.utcnow().replace(minute=0, second=0, microsecond=0)

    individual_records = [
        HealthDataRecord("fitbit", "user-123", HealthDataType.HEART_RATE,
                        base_time + timedelta(minutes=5), 68.0, "bpm"),
        HealthDataRecord("fitbit", "user-123", HealthDataType.HEART_RATE,
                        base_time + timedelta(minutes=15), 72.0, "bpm"),
        HealthDataRecord("fitbit", "user-123", HealthDataType.HEART_RATE,
                        base_time + timedelta(minutes=35), 75.0, "bpm"),
        HealthDataRecord("fitbit", "user-123", HealthDataType.HEART_RATE,
                        base_time + timedelta(minutes=50), 69.0, "bpm"),
    ]

    # Aggregate by hour
    aggregator = HourlyAggregator()
    hourly_records = aggregator.aggregate_heart_rate(individual_records)

    print("Hourly Aggregation Result:")
    for record in hourly_records:
        print(f"  Hour: {record.timestamp}")
        print(f"  Stats: {record.value}")
        print(f"  Source Records: {record.metadata['source_records']}")
```

## Running the Examples

To run these examples in your development environment:

```python
if __name__ == "__main__":
    print("=== Health Data Sync Architecture Examples ===")
    print()

    example_initial_sync()
    print()

    example_ecg_with_heart_rate()
    print()

    example_hourly_aggregation()
```

## Integration Notes

These examples demonstrate the core patterns used in the Open Health Exchange system:

1. **Strategy Pattern**: Different sync approaches for various triggers
2. **FHIR R5 Compliance**: Proper resource structure and LOINC coding
3. **Data Linking**: ECG and RR intervals always include heart rate
4. **Aggregation**: Flexible summarization for different use cases
5. **Type Safety**: Strong typing with Python 3.13+ features

For production implementation, these patterns are integrated with:
- Django REST Framework for API endpoints
- Huey for background task processing
- Redis for caching and task queuing
- PostgreSQL for configuration storage
- FHIR R5 servers for health record integration

See the main [architecture documentation](architecture.md) for complete system design details.