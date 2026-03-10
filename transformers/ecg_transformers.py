"""
FHIR R5 transformers for ECG data with proper panel structure and waveform storage
Implements LOINC 8601-7 EKG impression with SampledData for waveforms
Now inherits from BaseFHIRTransformer to eliminate duplication

Supports backwards compatibility with inwithings:
- Separate HR observation emission (ECG_EMIT_SEPARATE_HR)
- Coded AFib interpretation (ECG_AFIB_CODED_INTERPRETATION)
- Observation linking via derivedFrom (ENABLE_OBSERVATION_LINKING)
"""

import logging
from typing import Any

from ingestors.health_data_constants import (
    ECG_LOINC,
    FHIR_UNITS,
    HEART_RATE_LOINC,
    HealthDataRecord,
)

from .base_fhir_transformer import BaseFHIRTransformer
from .identifier_utils import generate_resource_uuid

logger = logging.getLogger(__name__)

# AFib classification codes for coded interpretation (inwithings format)
AFIB_INTERPRETATION_CODES = {
    # Positive AFib detection
    "POSITIVE": {"code": "DET", "display": "atrialFibrillation"},
    "atrial_fibrillation": {"code": "DET", "display": "atrialFibrillation"},
    "afib": {"code": "DET", "display": "atrialFibrillation"},
    # Negative (sinus rhythm)
    "NEGATIVE": {"code": "N", "display": "sinusRhythm"},
    "sinus_rhythm": {"code": "N", "display": "sinusRhythm"},
    "normal": {"code": "N", "display": "sinusRhythm"},
    # Inconclusive
    "INCONCLUSIVE": {"code": "IND", "display": "inconclusivePoorReading"},
    "inconclusive": {"code": "IND", "display": "inconclusivePoorReading"},
    "poor_reading": {"code": "IND", "display": "inconclusivePoorReading"},
}


class ECGTransformer(BaseFHIRTransformer):
    """Transforms ECG health data records to FHIR R5 Observation resources with proper panel structure

    Inherits unified FHIR methods from BaseFHIRTransformer.

    Supports backwards compatibility with inwithings:
    - Emits separate HR observation when ECG_EMIT_SEPARATE_HR is enabled
    - Uses coded AFib interpretation when ECG_AFIB_CODED_INTERPRETATION is enabled
    - Links observations via derivedFrom when ENABLE_OBSERVATION_LINKING is enabled
    """

    def transform(
        self, record: HealthDataRecord, patient_reference: str, device_reference: str | None = None
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Implementation of abstract transform method from BaseFHIRTransformer.

        Returns:
            Single observation dict in modern mode, or list of [ECG, HR] observations in legacy mode
        """
        return self.transform_ecg_to_fhir_panel(record, patient_reference, device_reference)

    def transform_ecg_to_fhir_panel(
        self, record: HealthDataRecord, patient_reference: str, device_reference: str | None = None
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Transform ECG record to FHIR R5 Observation(s) with EKG impression structure.

        In legacy mode with ECG_EMIT_SEPARATE_HR enabled, returns a list containing:
        1. ECG observation
        2. Heart rate observation (linked via derivedFrom)

        In modern mode, returns a single ECG observation with HR as a component.
        """
        config = self.get_compatibility_config()

        # Extract ECG metadata
        metadata = record.metadata or {}
        ecg_metrics = metadata.get("ecg_metrics", {})
        waveform_data = metadata.get("waveform_data", {})

        # Extract patient ID for identifier and UUID generation
        patient_id = patient_reference.split("/")[-1] if "/" in patient_reference else patient_reference

        # Generate deterministic UUID for ECG Observation resource ID
        resource_id = generate_resource_uuid("Observation", f"{patient_id}:{record.timestamp.isoformat()}:{ECG_LOINC}")

        # Create base observation with LOINC 8601-7 (EKG impression)
        observation: dict[str, Any] = {
            "resourceType": "Observation",
            "id": resource_id,
            "status": self.get_observation_status(),
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
                "coding": [{"system": "http://loinc.org", "code": ECG_LOINC, "display": "EKG impression"}],
                "text": "Electrocardiogram",
            },
            "subject": {"reference": patient_reference},
            "effectiveDateTime": self.create_fhir_timestamp(record.timestamp),
            "meta": self.create_fhir_meta(record.provider, record.measurement_source),
            "component": [],
        }

        # Add issued field in legacy mode
        if self.should_include_issued_field():
            observation["issued"] = self.create_fhir_timestamp()

        # Add device info based on compatibility mode
        if self.should_use_device_extensions():
            device_id = record.device_id
            device_model = metadata.get("device_model") or ecg_metrics.get("device_name")
            extensions = self.create_device_extensions(record.provider.value, device_id, device_model)
            if extensions:
                observation["extension"] = extensions
        elif device_reference:
            observation["device"] = {"reference": device_reference}

        # Add provider-specific identifier using compatibility strategy
        observation["identifier"] = self.create_observation_identifier(
            provider=record.provider,
            patient_id=patient_id,
            timestamp=record.timestamp,
            loinc_code=ECG_LOINC,
        )

        # AFib classification — always add interpretation (app reads it from observation.interpretation)
        result_classification = ecg_metrics.get("result_classification") or ecg_metrics.get("afib")
        if result_classification:
            afib_interpretation = self._create_afib_interpretation(result_classification)
            if afib_interpretation:
                observation["interpretation"] = afib_interpretation

        # Component 1 (MUST be first when present): ECG waveform data using SampledData
        # The app reads component.first.valueSampledData — waveform must be at index 0.
        # If waveform enrichment failed (empty samples), this component is omitted and
        # the app gracefully handles null valueSampledData (shows "No ECG data available").
        if waveform_data.get("samples"):
            samples = waveform_data["samples"]
            sampling_frequency = waveform_data.get("sampling_frequency_hz", 250)
            scaling_factor = waveform_data.get("scaling_factor", 1)

            # Create SampledData structure for waveform
            sampled_data = self._create_sampled_data(
                samples=samples,
                sampling_frequency=sampling_frequency,
                scaling_factor=scaling_factor,
                duration_seconds=waveform_data.get("duration_seconds", 30),
            )

            observation["component"].append(
                {
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": ECG_LOINC, "display": "EKG impression"}]
                    },
                    "valueSampledData": sampled_data,
                }
            )

        # Component 2: AFib classification as valueString
        if result_classification:
            observation["component"].append(
                {
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": ECG_LOINC, "display": "EKG impression"}]
                    },
                    "valueString": result_classification,
                }
            )

        # Component 3: Average heart rate during ECG (only in modern mode or when not emitting separate HR)
        heart_rate_value: float | None = (
            float(record.value) if isinstance(record.value, int | float) and record.value > 0 else None
        )
        emit_separate_hr = config.get("ECG_EMIT_SEPARATE_HR", False)

        if heart_rate_value is not None and not emit_separate_hr:
            observation["component"].append(
                {
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": HEART_RATE_LOINC, "display": "Heart rate"}]
                    },
                    "valueQuantity": {
                        "value": heart_rate_value,
                        "unit": FHIR_UNITS["heart_rate"]["display"],
                        "system": "http://unitsofmeasure.org",
                        "code": FHIR_UNITS["heart_rate"]["code"],
                    },
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
        # Get sampling frequency from waveform data if available
        waveform_sampling_freq = waveform_data.get("sampling_frequency_hz")
        if waveform_sampling_freq:
            device_info.append(f"Sampling Frequency: {waveform_sampling_freq} Hz")

        if device_info:
            observation["note"] = [
                {
                    "time": self.create_fhir_timestamp(),
                    "text": f"Synced from {record.provider.value.title()} Health Platform. Technical info: {'; '.join(device_info)}",
                }
            ]

        # In legacy mode, emit separate HR observation linked to ECG
        if emit_separate_hr and heart_rate_value is not None:
            hr_observation = self._create_related_hr_observation(
                record=record,
                patient_reference=patient_reference,
                patient_id=patient_id,
                device_reference=device_reference,
                ecg_observation=observation,
            )
            return [observation, hr_observation]

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
                "value": 0,
                "unit": "uV",
                "system": "http://unitsofmeasure.org",
                "code": "uV",
            },
            "interval": interval_ms,
            "intervalUnit": "ms",
            "factor": scaling_factor if scaling_factor != 0 else 1.0,
            "lowerLimit": -3300,  # Typical ECG range
            "upperLimit": 3300,
            "dimensions": 1,
            "data": samples_string,
        }

    def _create_afib_interpretation(self, classification: str) -> list[dict[str, Any]] | None:
        """
        Create coded AFib interpretation for ECG observation.

        Maps classification strings to FHIR interpretation codes:
        - NEGATIVE/normal/sinus_rhythm -> N (sinusRhythm)
        - POSITIVE/afib/atrial_fibrillation -> DET (atrialFibrillation)
        - INCONCLUSIVE/poor_reading -> IND (inconclusivePoorReading)

        Args:
            classification: AFib classification string from provider

        Returns:
            FHIR interpretation array or None if classification not recognized
        """
        # Try to find matching code (case-insensitive)
        code_info = AFIB_INTERPRETATION_CODES.get(classification) or AFIB_INTERPRETATION_CODES.get(
            classification.lower()
        )

        if not code_info:
            # Try partial matching for common variations
            classification_lower = classification.lower()
            if "normal" in classification_lower or "sinus" in classification_lower:
                code_info = AFIB_INTERPRETATION_CODES["normal"]
            elif "afib" in classification_lower or "fibrillation" in classification_lower:
                code_info = AFIB_INTERPRETATION_CODES["afib"]
            elif "inconclusive" in classification_lower or "poor" in classification_lower:
                code_info = AFIB_INTERPRETATION_CODES["inconclusive"]

        if not code_info:
            return None

        return [
            {
                "coding": [
                    {
                        "system": "http://hl7.org/fhir/ValueSet/observation-interpretation",
                        "code": code_info["code"],
                        "display": code_info["display"],
                    }
                ],
                # Add issued timestamp extension (inwithings format)
                "extension": [{"url": "Issued", "valueDateTime": self.create_fhir_timestamp()}],
            }
        ]

    def _create_related_hr_observation(
        self,
        record: HealthDataRecord,
        patient_reference: str,
        patient_id: str,
        device_reference: str | None,
        ecg_observation: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create a heart rate observation linked to an ECG observation.

        This supports the legacy inwithings pattern where HR is emitted as a
        separate observation with a derivedFrom reference to the ECG.

        Args:
            record: Original ECG health data record
            patient_reference: FHIR patient reference
            patient_id: Patient identifier for identifier generation
            device_reference: Optional FHIR device reference
            ecg_observation: The parent ECG observation

        Returns:
            FHIR Observation dict for heart rate
        """
        config = self.get_compatibility_config()
        metadata = record.metadata or {}

        # Generate deterministic UUID for HR Observation resource ID (from ECG)
        resource_id = generate_resource_uuid(
            "Observation", f"{patient_id}:{record.timestamp.isoformat()}:{HEART_RATE_LOINC}:from-ecg"
        )

        # Create HR observation
        hr_observation: dict[str, Any] = {
            "resourceType": "Observation",
            "id": resource_id,
            "status": self.get_observation_status(),
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "vital-signs",
                            "display": "Vital Signs",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [{"system": "http://loinc.org", "code": HEART_RATE_LOINC, "display": "Heart rate"}],
                "text": "Heart rate",
            },
            "subject": {"reference": patient_reference},
            "effectiveDateTime": self.create_fhir_timestamp(record.timestamp),
            "valueQuantity": {
                "value": float(record.value) if isinstance(record.value, int | float) else 0.0,
                "unit": FHIR_UNITS["heart_rate"]["display"],
                "system": "http://unitsofmeasure.org",
                "code": FHIR_UNITS["heart_rate"]["code"],
            },
            "meta": self.create_fhir_meta(record.provider, record.measurement_source),
        }

        # Add issued field in legacy mode
        if self.should_include_issued_field():
            hr_observation["issued"] = self.create_fhir_timestamp()

        # Add provider-specific identifier using compatibility strategy
        hr_observation["identifier"] = self.create_observation_identifier(
            provider=record.provider,
            patient_id=patient_id,
            timestamp=record.timestamp,
            loinc_code=HEART_RATE_LOINC,
        )

        # Add device info based on compatibility mode
        if self.should_use_device_extensions():
            device_id = record.device_id
            device_model = metadata.get("device_model")
            extensions = self.create_device_extensions(record.provider.value, device_id, device_model)
            if extensions:
                hr_observation["extension"] = extensions
        elif device_reference:
            hr_observation["device"] = {"reference": device_reference}

        # Link HR to ECG via derivedFrom (per PR feedback)
        if config.get("ENABLE_OBSERVATION_LINKING"):
            ecg_id = ecg_observation.get("id")
            if not ecg_id and ecg_observation.get("identifier"):
                ecg_id = ecg_observation["identifier"][0].get("value")
            if ecg_id:
                hr_observation["derivedFrom"] = [{"reference": f"Observation/{ecg_id}"}]

        return hr_observation

    # _create_measurement_source_tags removed - now using unified create_measurement_source_tags from base class
