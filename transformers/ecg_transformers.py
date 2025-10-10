"""
FHIR R5 transformers for ECG data with proper panel structure and waveform storage
Implements LOINC 34534-8 12-lead EKG panel with SampledData for waveforms
Now inherits from BaseFHIRTransformer to eliminate duplication
"""

import logging
from typing import Any, cast

from django.utils import timezone

from ingestors.health_data_constants import HealthDataRecord

from .base_fhir_transformer import BaseFHIRTransformer

logger = logging.getLogger(__name__)


class ECGTransformer(BaseFHIRTransformer):
    """Transforms ECG health data records to FHIR R5 Observation resources with proper panel structure

    Inherits unified FHIR methods from BaseFHIRTransformer
    """

    def transform(
        self, record: HealthDataRecord, patient_reference: str, device_reference: str | None = None
    ) -> dict[str, Any]:
        """Implementation of abstract transform method from BaseFHIRTransformer"""
        return self.transform_ecg_to_fhir_panel(record, patient_reference, device_reference)

    def transform_ecg_to_fhir_panel(
        self, record: HealthDataRecord, patient_reference: str, device_reference: str | None = None
    ) -> dict[str, Any]:
        """Transform ECG record to FHIR R5 Observation with 12-lead EKG panel structure"""

        # Extract ECG metadata
        metadata = record.metadata or {}
        ecg_metrics = metadata.get("ecg_metrics", {})
        waveform_data = metadata.get("waveform_data", {})

        # Create base observation with LOINC 34534-8 (12 lead EKG panel)
        observation: dict[str, Any] = {
            "resourceType": "Observation",
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "procedure",
                            "display": "Procedure",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [{"system": "http://loinc.org", "code": "34534-8", "display": "12 lead EKG panel"}],
                "text": "12-lead Electrocardiogram Panel",
            },
            "subject": {"reference": patient_reference},
            "effectiveDateTime": self.create_fhir_timestamp(record.timestamp),
            "meta": self.create_fhir_meta(record.provider, record.measurement_source),
            "component": [],
        }

        # Add device reference if available
        if device_reference:
            observation["device"] = {"reference": device_reference}

        # Add provider-specific identifier
        observation["identifier"] = [
            {
                "use": "secondary",
                "system": f"https://api.{record.provider.value}.com/health-data",
                "value": f"ecg_{record.timestamp.isoformat()}_{record.user_id}",
            }
        ]

        # Component 1: EKG impression (LOINC 8601-7)
        if ecg_metrics.get("result_classification"):
            observation["component"].append(
                {
                    "code": {"coding": [{"system": "http://loinc.org", "code": "8601-7", "display": "EKG impression"}]},
                    "valueString": ecg_metrics["result_classification"],
                }
            )

        # Component 2: Average heart rate during ECG
        if record.value and isinstance(record.value, (int, float)) and record.value > 0:
            observation["component"].append(
                {
                    "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
                    "valueQuantity": {
                        "value": float(cast(int | float, record.value)),
                        "unit": "/min",
                        "system": "http://unitsofmeasure.org",
                        "code": "/min",
                    },
                }
            )

        # Component 3: ECG waveform data using SampledData
        if waveform_data.get("samples"):
            samples = waveform_data["samples"]
            sampling_frequency = waveform_data.get("sampling_frequency_hz", 250)
            scaling_factor = waveform_data.get("scaling_factor", 1)
            lead_number = waveform_data.get("lead_number", 1)

            # Create SampledData structure for waveform
            sampled_data = self._create_sampled_data(
                samples=samples,
                sampling_frequency=sampling_frequency,
                scaling_factor=scaling_factor,
                duration_seconds=waveform_data.get("duration_seconds", 30),
            )

            # Determine LOINC code based on lead number (Fitbit typically uses Lead I equivalent)
            lead_loinc_map = {
                1: {"code": "131329", "display": "MDC_ECG_ELEC_POTL_I"}  # Lead I equivalent
            }

            lead_info = lead_loinc_map.get(lead_number, {"code": "131328", "display": "MDC_ECG_ELEC_POTL"})

            observation["component"].append(
                {
                    "code": {
                        "coding": [
                            {
                                "system": "urn:oid:2.16.840.1.113883.6.24",  # MDC (Medical Device Communication)
                                "code": lead_info["code"],
                                "display": lead_info["display"],
                            }
                        ]
                    },
                    "valueSampledData": sampled_data,
                }
            )

        # Component 4: Device and technical information
        device_info = []
        if ecg_metrics.get("device_name"):
            device_info.append(f"Device: {ecg_metrics['device_name']}")
        if ecg_metrics.get("firmware_version"):
            device_info.append(f"Firmware: {ecg_metrics['firmware_version']}")
        if ecg_metrics.get("feature_version"):
            device_info.append(f"Feature Version: {ecg_metrics['feature_version']}")
        if sampling_frequency:
            device_info.append(f"Sampling Frequency: {sampling_frequency} Hz")

        if device_info:
            observation["note"] = [
                {
                    "time": timezone.now().isoformat() + "Z",
                    "text": f"Synced from {record.provider.value.title()} Health Platform. Technical info: {'; '.join(device_info)}",
                }
            ]

        return observation

    def _create_sampled_data(
        self, samples: list[int | float], sampling_frequency: int, scaling_factor: float, duration_seconds: float
    ) -> dict[str, Any]:
        """Create FHIR SampledData structure for ECG waveform"""

        if not samples:
            return {}

        # Calculate interval between samples (in milliseconds)
        interval_ms = (1000.0 / sampling_frequency) if sampling_frequency > 0 else 4.0  # Default 4ms = 250Hz

        # Convert samples to space-separated string (FHIR SampledData format)
        # Samples are guaranteed to be numeric per type annotation
        samples_string = " ".join(str(int(s)) for s in samples[:10000])  # Limit to 10000 samples

        return {
            "origin": {
                "value": 2048,  # Baseline value (typical for ECG)
                "unit": "mV",
                "system": "http://unitsofmeasure.org",
                "code": "mV",
            },
            "interval": interval_ms,
            "intervalUnit": "ms",
            "factor": scaling_factor if scaling_factor > 0 else 1.0,
            "lowerLimit": -3300,  # Typical ECG range
            "upperLimit": 3300,
            "dimensions": 1,
            "codeMap": "mV",
            "offsets": None,  # Using factor instead
            "data": samples_string,
        }

    # _create_measurement_source_tags removed - now using unified create_measurement_source_tags from base class
