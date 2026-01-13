"""
FHIR R5 transformers for health data records
Now inherits from BaseFHIRTransformer to eliminate duplication
"""

import logging
from typing import Any, cast

from django.utils import timezone

from ingestors.health_data_constants import (
    HEALTH_DATA_DISPLAY_NAMES,
    HEALTH_DATA_FHIR_CATEGORIES,
    HEALTH_DATA_LOINC_CODES,
    HEALTH_DATA_UCUM_UNITS,
    HealthDataRecord,
    HealthDataType,
)

from .base_fhir_transformer import BaseFHIRTransformer
from .ecg_transformers import ECGTransformer
from .identifier_utils import generate_resource_uuid

logger = logging.getLogger(__name__)


def _create_fhir_timestamp(dt=None) -> str:
    """Create a FHIR-compliant timestamp with Z suffix for UTC times."""
    from datetime import UTC

    timestamp = dt or timezone.now()
    utc_timestamp = timestamp.astimezone(UTC)
    return utc_timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class HealthDataTransformer(BaseFHIRTransformer):
    """Transforms health data records to FHIR R5 Observation resources

    Inherits unified FHIR methods from BaseFHIRTransformer
    """

    def __init__(self):
        self.ecg_transformer = ECGTransformer()

    def transform(
        self, record: HealthDataRecord, patient_reference: str, device_reference: str | None = None
    ) -> dict[str, Any]:
        """Implementation of abstract transform method from BaseFHIRTransformer"""
        return self.transform_health_record(record, patient_reference, device_reference)

    # _safe_float removed - now using unified safe_convert_value from base class

    # _create_measurement_source_tags removed - now using unified create_measurement_source_tags from base class

    def transform_health_record(
        self, record: HealthDataRecord, patient_reference: str, device_reference: str | None = None
    ) -> dict[str, Any]:
        """Transform a health data record to FHIR Observation"""

        # Use specialized ECG transformer for ECG data
        if record.data_type == HealthDataType.ECG:
            return cast(
                dict[str, Any],
                self.ecg_transformer.transform_ecg_to_fhir_panel(record, patient_reference, device_reference),
            )

        # Get FHIR codes and mappings for non-ECG data
        # Use LOINC override if available (e.g., steps: 41950-7 for inwithings compatibility)
        # Convert HealthDataType keys to strings for compatibility with get_loinc_code
        loinc_codes_str: dict[str, str] = {k.value: v for k, v in HEALTH_DATA_LOINC_CODES.items()}
        loinc_code = self.get_loinc_code(record.data_type.value, loinc_codes_str)
        if not loinc_code:
            loinc_code = HEALTH_DATA_LOINC_CODES.get(record.data_type)
        display_name = HEALTH_DATA_DISPLAY_NAMES.get(record.data_type)
        category = HEALTH_DATA_FHIR_CATEGORIES.get(record.data_type, "survey")

        if not loinc_code:
            raise ValueError(f"No LOINC code defined for data type: {record.data_type}")

        # Extract patient ID from reference for identifier and UUID generation
        patient_id = patient_reference.split("/")[-1] if "/" in patient_reference else patient_reference

        # Generate deterministic UUID for Observation resource ID
        resource_id = generate_resource_uuid("Observation", f"{patient_id}:{record.timestamp.isoformat()}:{loinc_code}")

        # Create base observation with compatibility support
        observation: dict[str, Any] = {
            "resourceType": "Observation",
            "id": resource_id,
            "status": self.get_observation_status(),  # "registered" in legacy mode, "final" in modern
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": category,
                            "display": category.title().replace("-", " "),
                        }
                    ]
                }
            ],
            "code": {
                "coding": [{"system": "http://loinc.org", "code": loinc_code, "display": display_name}],
                "text": display_name,
            },
            "subject": {"reference": patient_reference},
            "effectiveDateTime": self.create_fhir_timestamp(record.timestamp),
            "meta": {
                "source": f"#{record.provider.value}",
                "tag": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
                        "code": "auto-generated",
                        "display": "Auto-generated",
                    },
                    {
                        "system": "https://open-health-exchange.com/provider",
                        "code": record.provider.value,
                        "display": record.provider.value.title(),
                    },
                ]
                + self.create_measurement_source_tags(record.measurement_source),
            },
        }

        # Add issued field in legacy mode (inwithings includes sync timestamp)
        if self.should_include_issued_field():
            observation["issued"] = self.create_fhir_timestamp()

        # Add device info based on compatibility mode
        if self.should_use_device_extensions():
            # Legacy mode: device info as extensions
            device_id = record.device_id
            device_model = record.metadata.get("device_model") if record.metadata else None
            extensions = self.create_device_extensions(record.provider.value, device_id, device_model)
            if extensions:
                observation["extension"] = extensions
        elif device_reference:
            # Modern mode: device reference
            observation["device"] = {"reference": device_reference}

        # Add provider-specific identifier using compatibility strategy
        # For blood pressure, include both LOINC codes in identifier for uniqueness
        secondary_loinc = "8462-4" if record.data_type == HealthDataType.BLOOD_PRESSURE else None
        observation["identifier"] = self.create_observation_identifier(
            provider=record.provider,
            patient_id=patient_id,
            timestamp=record.timestamp,
            loinc_code=loinc_code,
            secondary_loinc_code=secondary_loinc,
        )

        # Transform value based on data type
        if record.data_type == HealthDataType.HEART_RATE:
            observation.update(self._transform_heart_rate_value(record))
        elif record.data_type == HealthDataType.STEPS:
            observation.update(self._transform_steps_value(record))
        elif record.data_type == HealthDataType.WEIGHT:
            observation.update(self._transform_weight_value(record))
        elif record.data_type == HealthDataType.BLOOD_PRESSURE:
            observation.update(self._transform_blood_pressure_value(record))
        elif record.data_type == HealthDataType.TEMPERATURE:
            observation.update(self._transform_temperature_value(record))
        elif record.data_type == HealthDataType.SPO2:
            observation.update(self._transform_spo2_value(record))
        elif record.data_type == HealthDataType.RR_INTERVALS:
            observation.update(self._transform_rr_intervals_value(record))
        elif record.data_type == HealthDataType.SLEEP:
            observation.update(self._transform_sleep_value(record))
        elif record.data_type == HealthDataType.PULSE_WAVE_VELOCITY:
            observation.update(self._transform_pulse_wave_velocity_value(record))
        elif record.data_type == HealthDataType.FAT_MASS:
            observation.update(self._transform_fat_mass_value(record))
        else:
            # Generic value transformation
            observation.update(self._transform_generic_value(record))

        # Add notes with metadata
        if record.metadata:
            observation["note"] = [
                {
                    "time": self.create_fhir_timestamp(),
                    "text": f"Synced from {record.provider.value.title()} Health Platform. Metadata: {record.metadata}",
                }
            ]

        logger.debug(f"Transformed {record.data_type} record to FHIR Observation")
        return observation

    def _transform_heart_rate_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform heart rate value to FHIR format"""
        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": "bpm",
                "system": "http://unitsofmeasure.org",
                "code": "{beats}/min",
            }
        }

    def _transform_steps_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform steps value to FHIR format"""
        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": "steps",
                "system": "http://unitsofmeasure.org",
                "code": "[count]",  # UCUM code for count
            }
        }

    def _transform_weight_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform weight value to FHIR format"""
        ucum_unit = HEALTH_DATA_UCUM_UNITS.get(record.unit, record.unit)

        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": record.unit,
                "system": "http://unitsofmeasure.org",
                "code": ucum_unit,
            }
        }

    def _transform_blood_pressure_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform blood pressure value to FHIR format with components"""
        if not isinstance(record.value, dict):
            raise ValueError("Blood pressure value must be a dictionary with systolic and diastolic")

        systolic = record.value.get("systolic")
        diastolic = record.value.get("diastolic")

        if systolic is None or diastolic is None:
            raise ValueError("Blood pressure must include both systolic and diastolic values")

        return {
            "component": [
                {
                    "code": {
                        "coding": [
                            {"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}
                        ]
                    },
                    "valueQuantity": {
                        "value": float(systolic),
                        "unit": "mmHg",
                        "system": "http://unitsofmeasure.org",
                        "code": "mm[Hg]",
                    },
                },
                {
                    "code": {
                        "coding": [
                            {"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}
                        ]
                    },
                    "valueQuantity": {
                        "value": float(diastolic),
                        "unit": "mmHg",
                        "system": "http://unitsofmeasure.org",
                        "code": "mm[Hg]",
                    },
                },
            ]
        }

    def _transform_ecg_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform ECG value to FHIR format"""
        if isinstance(record.value, dict):
            # Complex ECG data with waveforms
            return {
                "component": [
                    {
                        "code": {
                            "coding": [{"system": "http://loinc.org", "code": "8628-0", "display": "ECG waveform"}]
                        },
                        "valueString": str(record.value),
                    }
                ]
            }
        else:
            # Simple ECG measurement
            return {"valueString": f"ECG measurement: {record.value}"}

    def _transform_temperature_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform temperature value to FHIR format"""
        ucum_unit = HEALTH_DATA_UCUM_UNITS.get(record.unit, record.unit)

        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": record.unit,
                "system": "http://unitsofmeasure.org",
                "code": ucum_unit,
            }
        }

    def _transform_spo2_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform SpO2 (oxygen saturation) value to FHIR format"""
        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": "%",
                "system": "http://unitsofmeasure.org",
                "code": "%",
            }
        }

    def _transform_rr_intervals_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform RR intervals value to FHIR format"""
        if isinstance(record.value, dict) and "intervals" in record.value:
            # Array of RR intervals
            intervals = record.value["intervals"]
            if isinstance(intervals, list):
                return {
                    "component": [
                        {
                            "code": {
                                "coding": [{"system": "http://loinc.org", "code": "8637-1", "display": "R-R interval"}]
                            },
                            "valueString": f"RR intervals: {intervals}",
                        }
                    ]
                }

        # Single RR interval value
        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": "ms",
                "system": "http://unitsofmeasure.org",
                "code": "ms",
            }
        }

    def _transform_sleep_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform sleep data to FHIR format"""
        if isinstance(record.value, dict):
            # Complex sleep data with multiple metrics
            components = []

            # Sleep duration component
            if "total_sleep_time" in record.value:
                components.append(
                    {
                        "code": {
                            "coding": [{"system": "http://loinc.org", "code": "93831-6", "display": "Total sleep time"}]
                        },
                        "valueQuantity": {
                            "value": float(record.value["total_sleep_time"]),
                            "unit": "minutes",
                            "system": "http://unitsofmeasure.org",
                            "code": "min",
                        },
                    }
                )

            # Sleep efficiency component
            if "sleep_efficiency" in record.value:
                components.append(
                    {
                        "code": {
                            "coding": [{"system": "http://loinc.org", "code": "93830-8", "display": "Sleep efficiency"}]
                        },
                        "valueQuantity": {
                            "value": float(record.value["sleep_efficiency"]),
                            "unit": "%",
                            "system": "http://unitsofmeasure.org",
                            "code": "%",
                        },
                    }
                )

            if components:
                return {"component": components}
            else:
                # Fallback to string representation
                return {"valueString": str(record.value)}
        else:
            # Simple sleep duration value
            return {
                "valueQuantity": {
                    "value": self.safe_convert_value(record.value, float),
                    "unit": record.unit or "minutes",
                    "system": "http://unitsofmeasure.org",
                    "code": "min",
                }
            }

    def _transform_pulse_wave_velocity_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform pulse wave velocity to FHIR format"""
        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": record.unit or "m/s",
                "system": "http://unitsofmeasure.org",
                "code": "m/s",
            }
        }

    def _transform_fat_mass_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform fat mass/body composition to FHIR format"""
        if isinstance(record.value, dict):
            # Complex body composition data
            components = []

            # Fat mass component
            if "fat_mass" in record.value:
                components.append(
                    {
                        "code": {
                            "coding": [{"system": "http://loinc.org", "code": "73708-0", "display": "Fat mass by DEXA"}]
                        },
                        "valueQuantity": {
                            "value": float(record.value["fat_mass"]),
                            "unit": record.unit or "kg",
                            "system": "http://unitsofmeasure.org",
                            "code": "kg",
                        },
                    }
                )

            # Fat percentage component
            if "fat_percentage" in record.value:
                components.append(
                    {
                        "code": {
                            "coding": [
                                {
                                    "system": "http://loinc.org",
                                    "code": "41982-0",
                                    "display": "Percentage of body fat Measured",
                                }
                            ]
                        },
                        "valueQuantity": {
                            "value": float(record.value["fat_percentage"]),
                            "unit": "%",
                            "system": "http://unitsofmeasure.org",
                            "code": "%",
                        },
                    }
                )

            # Muscle mass component
            if "muscle_mass" in record.value:
                components.append(
                    {
                        "code": {
                            "coding": [
                                {"system": "http://loinc.org", "code": "73964-9", "display": "Muscle mass by DEXA"}
                            ]
                        },
                        "valueQuantity": {
                            "value": float(record.value["muscle_mass"]),
                            "unit": record.unit or "kg",
                            "system": "http://unitsofmeasure.org",
                            "code": "kg",
                        },
                    }
                )

            if components:
                return {"component": components}
            else:
                return {"valueString": str(record.value)}
        else:
            # Simple fat mass value
            return {
                "valueQuantity": {
                    "value": self.safe_convert_value(record.value, float),
                    "unit": record.unit or "kg",
                    "system": "http://unitsofmeasure.org",
                    "code": "kg",
                }
            }

    def _transform_generic_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform generic numeric value to FHIR format"""
        ucum_unit = HEALTH_DATA_UCUM_UNITS.get(record.unit, record.unit)

        if isinstance(record.value, int | float):
            return {
                "valueQuantity": {
                    "value": float(record.value),
                    "unit": record.unit,
                    "system": "http://unitsofmeasure.org",
                    "code": ucum_unit,
                }
            }
        else:
            # Complex value - store as string for now
            return {"valueString": str(record.value)}

    def transform_multiple_records(
        self, records: list[HealthDataRecord], patient_reference: str, device_reference: str | None = None
    ) -> list[dict[str, Any]]:
        """Transform multiple health data records to FHIR Observations"""
        observations = []

        for record in records:
            try:
                observation = self.transform_health_record(record, patient_reference, device_reference)
                observations.append(observation)
            except Exception as e:
                logger.error(f"Error transforming health record {record.data_type} for {record.user_id}: {e}")

        logger.info(f"Transformed {len(observations)} health records to FHIR Observations")
        return observations


class HealthDataBundle:
    """Creates FHIR Bundles for health data resources"""

    @staticmethod
    def get_compatibility_config() -> dict[str, Any]:
        """Get FHIR compatibility configuration."""
        from django.conf import settings

        return getattr(settings, "FHIR_COMPATIBILITY_CONFIG", {})

    @staticmethod
    def create_transaction_bundle(observations: list[dict[str, Any]], bundle_id: str | None = None) -> dict[str, Any]:
        """Create a FHIR bundle for health observations with compatibility support.

        In legacy mode (inwithings compatible):
        - Uses 'batch' bundle type with PUT method for idempotent updates
        - Observations must have identifiers for PUT requests

        In modern mode:
        - Uses 'transaction' bundle type with POST method
        """
        config = HealthDataBundle.get_compatibility_config()
        bundle_type = config.get("BUNDLE_TYPE", "batch")  # Default to batch for legacy
        bundle_method = config.get("BUNDLE_METHOD", "PUT")  # Default to PUT for legacy

        if bundle_id is None:
            bundle_id = f"health-data-bundle-{timezone.now().strftime('%Y%m%d%H%M%S')}"

        # Create bundle entries based on compatibility mode
        entries = []
        for i, observation in enumerate(observations):
            # Get observation ID for PUT method
            obs_id = observation.get("id")
            if not obs_id and observation.get("identifier"):
                # Use identifier value as ID for PUT
                obs_id = observation["identifier"][0].get("value", f"observation-{i}")

            if bundle_method == "PUT" and obs_id:
                # Legacy mode: PUT for idempotent updates
                entry = {
                    "fullUrl": f"Observation/{obs_id}",
                    "resource": {**observation, "id": obs_id},
                    "request": {"method": "PUT", "url": f"Observation/{obs_id}"},
                }
            else:
                # Modern mode: POST for new resources
                entry = {
                    "fullUrl": f"urn:uuid:observation-{i}",
                    "resource": observation,
                    "request": {"method": "POST", "url": "Observation"},
                }
            entries.append(entry)

        bundle = {
            "resourceType": "Bundle",
            "id": bundle_id,
            "type": bundle_type,
            "timestamp": _create_fhir_timestamp(),
            "total": len(entries),
            "entry": entries,
            "meta": {
                "tag": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                        "code": "HDATA",
                        "display": "Health Data",
                    }
                ]
            },
        }

        return bundle


# Convenience functions for backward compatibility
def transform_health_record(
    record: HealthDataRecord, patient_reference: str, device_reference: str | None = None
) -> dict[str, Any]:
    """Transform a single health data record to FHIR Observation"""
    transformer = HealthDataTransformer()
    return transformer.transform_health_record(record, patient_reference, device_reference)


def transform_multiple_health_records(
    records: list[HealthDataRecord], patient_reference: str, device_reference: str | None = None
) -> list[dict[str, Any]]:
    """Transform multiple health data records to FHIR Observations"""
    transformer = HealthDataTransformer()
    return transformer.transform_multiple_records(records, patient_reference, device_reference)


def create_health_data_bundle(observations: list[dict[str, Any]], bundle_id: str | None = None) -> dict[str, Any]:
    """Create a FHIR transaction bundle for health observations"""
    return HealthDataBundle.create_transaction_bundle(observations, bundle_id)
