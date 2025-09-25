"""
FHIR R5 transformers for health data records
Now inherits from BaseFHIRTransformer to eliminate duplication
"""
import logging
from datetime import datetime
from typing import Any, Union, cast

from ingestors.health_data_constants import (
    HealthDataType, HealthDataRecord, MeasurementSource,
    HEALTH_DATA_LOINC_CODES, HEALTH_DATA_UCUM_UNITS,
    HEALTH_DATA_DISPLAY_NAMES, HEALTH_DATA_FHIR_CATEGORIES
)
from .ecg_transformers import ECGTransformer
from .base_fhir_transformer import BaseFHIRTransformer


logger = logging.getLogger(__name__)


class HealthDataTransformer(BaseFHIRTransformer):
    """Transforms health data records to FHIR R5 Observation resources

    Inherits unified FHIR methods from BaseFHIRTransformer
    """

    def __init__(self):
        self.ecg_transformer = ECGTransformer()

    def transform(self, record: HealthDataRecord, patient_reference: str, device_reference: str | None = None) -> dict[str, Any]:
        """Implementation of abstract transform method from BaseFHIRTransformer"""
        return self.transform_health_record(record, patient_reference, device_reference)

    # _safe_float removed - now using unified safe_convert_value from base class

    # _create_measurement_source_tags removed - now using unified create_measurement_source_tags from base class

    def transform_health_record(
        self,
        record: HealthDataRecord,
        patient_reference: str,
        device_reference: str | None = None
    ) -> dict[str, Any]:
        """Transform a health data record to FHIR Observation"""

        # Use specialized ECG transformer for ECG data
        if record.data_type == HealthDataType.ECG:
            return cast(dict[str, Any], self.ecg_transformer.transform_ecg_to_fhir_panel(
                record, patient_reference, device_reference
            ))

        # Get FHIR codes and mappings for non-ECG data
        loinc_code = HEALTH_DATA_LOINC_CODES.get(record.data_type)
        display_name = HEALTH_DATA_DISPLAY_NAMES.get(record.data_type)
        category = HEALTH_DATA_FHIR_CATEGORIES.get(record.data_type, "survey")

        if not loinc_code:
            raise ValueError(f"No LOINC code defined for data type: {record.data_type}")

        # Create base observation
        observation = {
            "resourceType": "Observation",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": category,
                    "display": category.title().replace("-", " ")
                }]
            }],
            "code": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": loinc_code,
                    "display": display_name
                }],
                "text": display_name
            },
            "subject": {"reference": patient_reference},
            "effectiveDateTime": record.timestamp.isoformat() + "Z",
            "meta": {
                "source": f"#{record.provider.value}",
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
                    "code": "auto-generated",
                    "display": "Auto-generated"
                }, {
                    "system": "https://open-health-exchange.com/provider",
                    "code": record.provider.value,
                    "display": record.provider.value.title()
                }] + self.create_measurement_source_tags(record.measurement_source)
            }
        }

        # Add device reference if available
        if device_reference:
            observation["device"] = {"reference": device_reference}

        # Add provider-specific identifier
        observation["identifier"] = [{
            "use": "secondary",
            "system": f"https://api.{record.provider.value}.com/health-data",
            "value": f"{record.data_type.value}_{record.timestamp.isoformat()}_{record.user_id}"
        }]

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
            observation["note"] = [{
                "time": datetime.utcnow().isoformat() + "Z",
                "text": f"Synced from {record.provider.value.title()} Health Platform. Metadata: {record.metadata}"
            }]

        logger.debug(f"Transformed {record.data_type} record to FHIR Observation")
        return observation

    def _transform_heart_rate_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform heart rate value to FHIR format"""
        ucum_unit = HEALTH_DATA_UCUM_UNITS.get(record.unit, record.unit)

        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": "beats/minute",
                "system": "http://unitsofmeasure.org",
                "code": ucum_unit
            }
        }

    def _transform_steps_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform steps value to FHIR format"""
        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": "steps",
                "system": "http://unitsofmeasure.org",
                "code": "1"  # UCUM code for count
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
                "code": ucum_unit
            }
        }

    def _transform_blood_pressure_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform blood pressure value to FHIR format with components"""
        if not isinstance(record.value, dict):
            raise ValueError("Blood pressure value must be a dictionary with systolic and diastolic")

        systolic = record.value.get('systolic')
        diastolic = record.value.get('diastolic')

        if systolic is None or diastolic is None:
            raise ValueError("Blood pressure must include both systolic and diastolic values")

        return {
            "component": [
                {
                    "code": {
                        "coding": [{
                            "system": "http://loinc.org",
                            "code": "8480-6",
                            "display": "Systolic blood pressure"
                        }]
                    },
                    "valueQuantity": {
                        "value": float(systolic),
                        "unit": "mmHg",
                        "system": "http://unitsofmeasure.org",
                        "code": "mm[Hg]"
                    }
                },
                {
                    "code": {
                        "coding": [{
                            "system": "http://loinc.org",
                            "code": "8462-4",
                            "display": "Diastolic blood pressure"
                        }]
                    },
                    "valueQuantity": {
                        "value": float(diastolic),
                        "unit": "mmHg",
                        "system": "http://unitsofmeasure.org",
                        "code": "mm[Hg]"
                    }
                }
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
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": "8628-0",
                                "display": "ECG waveform"
                            }]
                        },
                        "valueString": str(record.value)
                    }
                ]
            }
        else:
            # Simple ECG measurement
            return {
                "valueString": f"ECG measurement: {record.value}"
            }

    def _transform_temperature_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform temperature value to FHIR format"""
        ucum_unit = HEALTH_DATA_UCUM_UNITS.get(record.unit, record.unit)

        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": record.unit,
                "system": "http://unitsofmeasure.org",
                "code": ucum_unit
            }
        }

    def _transform_spo2_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform SpO2 (oxygen saturation) value to FHIR format"""
        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": "%",
                "system": "http://unitsofmeasure.org",
                "code": "%"
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
                                "coding": [{
                                    "system": "http://loinc.org",
                                    "code": "8637-1",
                                    "display": "R-R interval"
                                }]
                            },
                            "valueString": f"RR intervals: {intervals}"
                        }
                    ]
                }

        # Single RR interval value
        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": "ms",
                "system": "http://unitsofmeasure.org",
                "code": "ms"
            }
        }

    def _transform_sleep_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform sleep data to FHIR format"""
        if isinstance(record.value, dict):
            # Complex sleep data with multiple metrics
            components = []

            # Sleep duration component
            if "total_sleep_time" in record.value:
                components.append({
                    "code": {
                        "coding": [{
                            "system": "http://loinc.org",
                            "code": "93831-6",
                            "display": "Total sleep time"
                        }]
                    },
                    "valueQuantity": {
                        "value": float(record.value["total_sleep_time"]),
                        "unit": "minutes",
                        "system": "http://unitsofmeasure.org",
                        "code": "min"
                    }
                })

            # Sleep efficiency component
            if "sleep_efficiency" in record.value:
                components.append({
                    "code": {
                        "coding": [{
                            "system": "http://loinc.org",
                            "code": "93830-8",
                            "display": "Sleep efficiency"
                        }]
                    },
                    "valueQuantity": {
                        "value": float(record.value["sleep_efficiency"]),
                        "unit": "%",
                        "system": "http://unitsofmeasure.org",
                        "code": "%"
                    }
                })

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
                    "code": "min"
                }
            }

    def _transform_pulse_wave_velocity_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform pulse wave velocity to FHIR format"""
        return {
            "valueQuantity": {
                "value": self.safe_convert_value(record.value, float),
                "unit": record.unit or "m/s",
                "system": "http://unitsofmeasure.org",
                "code": "m/s"
            }
        }

    def _transform_fat_mass_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform fat mass/body composition to FHIR format"""
        if isinstance(record.value, dict):
            # Complex body composition data
            components = []

            # Fat mass component
            if "fat_mass" in record.value:
                components.append({
                    "code": {
                        "coding": [{
                            "system": "http://loinc.org",
                            "code": "73708-0",
                            "display": "Fat mass by DEXA"
                        }]
                    },
                    "valueQuantity": {
                        "value": float(record.value["fat_mass"]),
                        "unit": record.unit or "kg",
                        "system": "http://unitsofmeasure.org",
                        "code": "kg"
                    }
                })

            # Fat percentage component
            if "fat_percentage" in record.value:
                components.append({
                    "code": {
                        "coding": [{
                            "system": "http://loinc.org",
                            "code": "41982-0",
                            "display": "Percentage of body fat Measured"
                        }]
                    },
                    "valueQuantity": {
                        "value": float(record.value["fat_percentage"]),
                        "unit": "%",
                        "system": "http://unitsofmeasure.org",
                        "code": "%"
                    }
                })

            # Muscle mass component
            if "muscle_mass" in record.value:
                components.append({
                    "code": {
                        "coding": [{
                            "system": "http://loinc.org",
                            "code": "73964-9",
                            "display": "Muscle mass by DEXA"
                        }]
                    },
                    "valueQuantity": {
                        "value": float(record.value["muscle_mass"]),
                        "unit": record.unit or "kg",
                        "system": "http://unitsofmeasure.org",
                        "code": "kg"
                    }
                })

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
                    "code": "kg"
                }
            }

    def _transform_generic_value(self, record: HealthDataRecord) -> dict[str, Any]:
        """Transform generic numeric value to FHIR format"""
        ucum_unit = HEALTH_DATA_UCUM_UNITS.get(record.unit, record.unit)

        if isinstance(record.value, (int, float)):
            return {
                "valueQuantity": {
                    "value": float(record.value),
                    "unit": record.unit,
                    "system": "http://unitsofmeasure.org",
                    "code": ucum_unit
                }
            }
        else:
            # Complex value - store as string for now
            return {
                "valueString": str(record.value)
            }

    def transform_multiple_records(
        self,
        records: list[HealthDataRecord],
        patient_reference: str,
        device_reference: str | None = None
    ) -> list[dict[str, Any]]:
        """Transform multiple health data records to FHIR Observations"""
        observations = []

        for record in records:
            try:
                observation = self.transform_health_record(
                    record, patient_reference, device_reference
                )
                observations.append(observation)
            except Exception as e:
                logger.error(f"Error transforming health record {record.data_type} for {record.user_id}: {e}")

        logger.info(f"Transformed {len(observations)} health records to FHIR Observations")
        return observations


class HealthDataBundle:
    """Creates FHIR Bundles for health data resources"""

    @staticmethod
    def create_transaction_bundle(
        observations: list[dict[str, Any]],
        bundle_id: str | None = None
    ) -> dict[str, Any]:
        """Create a FHIR transaction bundle for health observations"""

        if bundle_id is None:
            bundle_id = f"health-data-bundle-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        # Create bundle entries
        entries = []
        for i, observation in enumerate(observations):
            entry = {
                "fullUrl": f"urn:uuid:observation-{i}",
                "resource": observation,
                "request": {
                    "method": "POST",
                    "url": "Observation"
                }
            }
            entries.append(entry)

        bundle = {
            "resourceType": "Bundle",
            "id": bundle_id,
            "type": "transaction",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "total": len(entries),
            "entry": entries,
            "meta": {
                "tag": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "HDATA",
                    "display": "Health Data"
                }]
            }
        }

        return bundle


# Convenience functions for backward compatibility
def transform_health_record(
    record: HealthDataRecord,
    patient_reference: str,
    device_reference: str | None = None
) -> dict[str, Any]:
    """Transform a single health data record to FHIR Observation"""
    transformer = HealthDataTransformer()
    return transformer.transform_health_record(record, patient_reference, device_reference)


def transform_multiple_health_records(
    records: list[HealthDataRecord],
    patient_reference: str,
    device_reference: str | None = None
) -> list[dict[str, Any]]:
    """Transform multiple health data records to FHIR Observations"""
    transformer = HealthDataTransformer()
    return transformer.transform_multiple_records(records, patient_reference, device_reference)


def create_health_data_bundle(
    observations: list[dict[str, Any]],
    bundle_id: str | None = None
) -> dict[str, Any]:
    """Create a FHIR transaction bundle for health observations"""
    return HealthDataBundle.create_transaction_bundle(observations, bundle_id)