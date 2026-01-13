"""
Unified base FHIR transformer - Eliminates duplication across all transformer files
Provides common FHIR structure creation methods and validation patterns
"""

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from django.utils import timezone

from ingestors.constants import Provider
from ingestors.health_data_constants import MeasurementSource

logger = logging.getLogger(__name__)


class BaseFHIRTransformer(ABC):
    """
    Base FHIR transformer with unified methods for common patterns

    Eliminates duplication across DeviceTransformer, DeviceAssociationTransformer,
    HealthDataTransformer, and ECGTransformer
    """

    # Common FHIR system URLs
    FHIR_SYSTEMS = {
        "SNOMED": "http://snomed.info/sct",
        "LOINC": "http://loinc.org",
        "UCUM": "http://unitsofmeasure.org",
        "OBSERVATION_CATEGORY": "http://terminology.hl7.org/CodeSystem/observation-category",
        "OBSERVATION_VALUE": "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
        "DEVICE_VERSION_TYPE": "http://terminology.hl7.org/CodeSystem/device-version-type",
        "DEVICE_PROPERTY_TYPE": "http://terminology.hl7.org/CodeSystem/device-property-type",
        "DEVICE_ASSOCIATION_CATEGORY": "http://hl7.org/fhir/device-association-category",
        "DEVICE_ASSOCIATION_STATUS": "http://hl7.org/fhir/device-association-status",
        "DEVICE_ASSOCIATION_OPERATION_STATUS": "http://hl7.org/fhir/device-association-operation-status",
        "PROVIDER_SYSTEM": "https://open-health-exchange.com/provider",
        "MEASUREMENT_SOURCE": "https://open-health-exchange.com/measurement-source",
    }

    @abstractmethod
    def transform(self, *args, **kwargs) -> dict[str, Any] | list[dict[str, Any]]:
        """Abstract method for transformation - must be implemented by subclasses"""

    def create_fhir_coding(self, system: str, code: str, display: str) -> dict[str, Any]:
        """
        Unified FHIR coding structure creation

        Eliminates duplication across all transformer classes
        """
        return {"coding": [{"system": system, "code": code, "display": display}], "text": display}

    def create_provider_system_url(self, provider: Provider, endpoint_type: str) -> str:
        """
        Unified provider system URL creation

        Args:
            provider: Provider enum (withings, fitbit, etc.)
            endpoint_type: Type of endpoint (device-id, device-association, etc.)
        """
        return f"https://api.{provider.value}.com/{endpoint_type}"

    def create_fhir_identifier(
        self, provider: Provider, value: str, endpoint_type: str, use: str = "official"
    ) -> dict[str, Any]:
        """
        Unified FHIR identifier creation

        Eliminates duplication between DeviceTransformer and DeviceAssociationTransformer
        """
        return {
            "use": use,
            "system": self.create_provider_system_url(provider, endpoint_type),
            "value": value,
            "assigner": {"display": provider.value.title()},
        }

    def create_measurement_source_tags(self, measurement_source: MeasurementSource) -> list[dict[str, Any]]:
        """
        Unified measurement source tags creation

        Eliminates exact duplication between HealthDataTransformer and ECGTransformer
        """
        source_display_map = {
            MeasurementSource.DEVICE: "Device measurement",
            MeasurementSource.USER: "User-entered measurement",
            MeasurementSource.UNKNOWN: "Unknown source",
        }

        source_display = source_display_map.get(measurement_source, "Unknown source")

        return [
            {
                "system": self.FHIR_SYSTEMS["MEASUREMENT_SOURCE"],
                "code": measurement_source.value,
                "display": source_display,
            }
        ]

    def create_provider_tags(self, provider: Provider) -> list[dict[str, Any]]:
        """
        Unified provider tag creation

        Standardizes provider tagging across all transformers
        """
        return [
            {"system": self.FHIR_SYSTEMS["OBSERVATION_VALUE"], "code": "auto-generated", "display": "Auto-generated"},
            {"system": self.FHIR_SYSTEMS["PROVIDER_SYSTEM"], "code": provider.value, "display": provider.value.title()},
        ]

    def create_fhir_meta(
        self, provider: Provider, measurement_source: MeasurementSource | None = None
    ) -> dict[str, Any]:
        """
        Unified FHIR meta section creation

        Combines provider tags and measurement source tags consistently
        """
        tags = self.create_provider_tags(provider)

        if measurement_source:
            tags.extend(self.create_measurement_source_tags(measurement_source))

        return {"source": f"#{provider.value}", "tag": tags}

    def safe_convert_value(self, value: float | dict | str | int, target_type: type = float):
        """
        Unified safe value conversion

        Handles type conversion with fallback for FHIR data consistency
        """
        if isinstance(value, int | float) and target_type is float:
            return float(value)
        elif isinstance(value, str):
            try:
                if target_type is float:
                    return float(value)
                elif target_type is int:
                    return int(value)
                else:
                    return str(value)
            except ValueError:
                return 0.0 if target_type is float else 0 if target_type is int else ""
        else:
            return 0.0 if target_type is float else 0 if target_type is int else ""

    def create_fhir_timestamp(self, dt: datetime | None = None) -> str:
        """
        Unified FHIR timestamp creation

        Ensures consistent ISO format with Z suffix for UTC times.
        FHIR requires either Z suffix OR timezone offset, not both.
        """
        timestamp = dt or timezone.now()
        # Convert to UTC and format with Z suffix (not +00:00Z which is invalid)
        utc_timestamp = timestamp.astimezone(UTC)
        # Use strftime to avoid the +00:00 offset that isoformat() adds
        return utc_timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def log_transformation(self, resource_type: str, identifier: str):
        """
        Unified transformation logging

        Provides consistent logging across all transformers
        """
        logger.info(f"Transformed {identifier} to FHIR {resource_type}")

    # =====================================================
    # Backwards Compatibility Methods (inwithings support)
    # =====================================================

    def get_compatibility_config(self) -> dict[str, Any]:
        """
        Get FHIR compatibility configuration.

        Returns the compatibility settings for legacy inwithings support.
        """
        from django.conf import settings

        return getattr(settings, "FHIR_COMPATIBILITY_CONFIG", {})

    def get_loinc_code(self, data_type: str, default_codes: dict[str, str] | None = None) -> str | None:
        """
        Get LOINC code, respecting compatibility overrides.

        Args:
            data_type: The health data type (e.g., "steps", "heart_rate")
            default_codes: Default LOINC code mapping

        Returns:
            LOINC code string or None if not found
        """
        config = self.get_compatibility_config()
        overrides: dict[str, str] = config.get("LOINC_OVERRIDES", {})

        # Check for override first
        if data_type in overrides:
            return overrides[data_type]

        # Fall back to default codes
        if default_codes:
            return default_codes.get(data_type)

        return None

    def create_device_extensions(
        self,
        provider: str,
        device_id: str | None = None,
        device_model: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Create device-related extensions for legacy compatibility.

        In legacy mode (inwithings), device information is stored as extensions
        on the observation rather than as separate Device resources.

        Args:
            provider: Provider name (e.g., "withings", "fitbit")
            device_id: External device identifier
            device_model: Device model identifier

        Returns:
            List of FHIR extension dictionaries
        """
        config = self.get_compatibility_config()
        extensions = []

        if config.get("DEVICE_INFO_MODE") == "extension":
            # obtained-from extension (always present in legacy mode)
            extensions.append({"url": "obtained-from", "valueString": provider})

            # external-device-id extension
            if device_id:
                extensions.append({"url": "external-device-id", "valueString": device_id})

            # device-model extension (per PR review feedback)
            if device_model and config.get("INCLUDE_DEVICE_MODEL_EXTENSION"):
                extensions.append({"url": "device-model", "valueString": str(device_model)})

        return extensions

    def create_observation_identifier(
        self,
        provider: Provider,
        patient_id: str,
        timestamp: datetime,
        loinc_code: str,
        secondary_loinc_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Create observation identifier with compatibility support.

        Uses Jenkins hash in legacy mode for deterministic idempotent identifiers.

        Args:
            provider: Health data provider
            patient_id: Patient/user identifier
            timestamp: Measurement timestamp
            loinc_code: Primary LOINC code
            secondary_loinc_code: Secondary LOINC code (for blood pressure)

        Returns:
            List containing FHIR identifier dictionary
        """
        from .identifier_utils import generate_observation_identifier, get_identifier_system

        identifier_value = generate_observation_identifier(
            patient_id=patient_id,
            timestamp=timestamp,
            loinc_code=loinc_code,
            secondary_loinc_code=secondary_loinc_code,
        )

        return [
            {
                "use": "secondary",
                "system": get_identifier_system(provider.value),
                "value": identifier_value,
            }
        ]

    def get_observation_status(self) -> str:
        """
        Get observation status based on compatibility mode.

        Returns:
            "registered" in legacy mode, "final" in modern mode
        """
        config = self.get_compatibility_config()
        status: str = config.get("OBSERVATION_STATUS", "registered")
        return status

    def should_include_issued_field(self) -> bool:
        """
        Check if issued field should be included.

        Returns:
            True in legacy mode (inwithings includes issued timestamp)
        """
        config = self.get_compatibility_config()
        include: bool = config.get("INCLUDE_ISSUED_FIELD", True)
        return include

    def should_use_device_extensions(self) -> bool:
        """
        Check if device info should be stored as extensions.

        Returns:
            True in legacy mode (extensions), False in modern mode (Device reference)
        """
        config = self.get_compatibility_config()
        return config.get("DEVICE_INFO_MODE") == "extension"

    def create_base_observation(
        self,
        patient_reference: str,
        timestamp: datetime,
        provider: Provider,
        measurement_source: MeasurementSource | None = None,
        device_reference: str | None = None,
        device_id: str | None = None,
        device_model: str | None = None,
    ) -> dict[str, Any]:
        """
        Create base observation structure respecting compatibility mode.

        Args:
            patient_reference: FHIR patient reference (e.g., "Patient/123")
            timestamp: Measurement timestamp
            provider: Health data provider
            measurement_source: Source of measurement (device, user, unknown)
            device_reference: FHIR device reference (modern mode)
            device_id: External device ID (legacy mode)
            device_model: Device model identifier (legacy mode)

        Returns:
            Base observation dictionary
        """
        observation: dict[str, Any] = {
            "resourceType": "Observation",
            "status": self.get_observation_status(),
            "subject": {"reference": patient_reference},
            "effectiveDateTime": self.create_fhir_timestamp(timestamp),
            "meta": self.create_fhir_meta(provider, measurement_source),
        }

        # Add issued field in legacy mode
        if self.should_include_issued_field():
            observation["issued"] = self.create_fhir_timestamp()

        # Add device info based on mode
        if self.should_use_device_extensions():
            extensions = self.create_device_extensions(provider.value, device_id, device_model)
            if extensions:
                observation["extension"] = extensions
        elif device_reference:
            observation["device"] = {"reference": device_reference}

        return observation
