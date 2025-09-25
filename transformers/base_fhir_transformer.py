"""
Unified base FHIR transformer - Eliminates duplication across all transformer files
Provides common FHIR structure creation methods and validation patterns
"""
import logging
from datetime import datetime
from typing import Any, Union
from abc import ABC, abstractmethod

from ingestors.constants import DeviceData, Provider
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
        'SNOMED': "http://snomed.info/sct",
        'LOINC': "http://loinc.org",
        'UCUM': "http://unitsofmeasure.org",
        'OBSERVATION_CATEGORY': "http://terminology.hl7.org/CodeSystem/observation-category",
        'OBSERVATION_VALUE': "http://terminology.hl7.org/CodeSystem/v3-ObservationValue",
        'DEVICE_VERSION_TYPE': "http://terminology.hl7.org/CodeSystem/device-version-type",
        'DEVICE_PROPERTY_TYPE': "http://terminology.hl7.org/CodeSystem/device-property-type",
        'DEVICE_ASSOCIATION_CATEGORY': "http://hl7.org/fhir/device-association-category",
        'DEVICE_ASSOCIATION_STATUS': "http://hl7.org/fhir/device-association-status",
        'DEVICE_ASSOCIATION_OPERATION_STATUS': "http://hl7.org/fhir/device-association-operation-status",
        'PROVIDER_SYSTEM': "https://open-health-exchange.com/provider",
        'MEASUREMENT_SOURCE': "https://open-health-exchange.com/measurement-source"
    }

    @abstractmethod
    def transform(self, *args, **kwargs) -> dict[str, Any]:
        """Abstract method for transformation - must be implemented by subclasses"""
        pass

    def create_fhir_coding(self, system: str, code: str, display: str) -> dict[str, Any]:
        """
        Unified FHIR coding structure creation

        Eliminates duplication across all transformer classes
        """
        return {
            "coding": [{
                "system": system,
                "code": code,
                "display": display
            }],
            "text": display
        }

    def create_provider_system_url(self, provider: Provider, endpoint_type: str) -> str:
        """
        Unified provider system URL creation

        Args:
            provider: Provider enum (withings, fitbit, etc.)
            endpoint_type: Type of endpoint (device-id, device-association, etc.)
        """
        return f"https://api.{provider.value}.com/{endpoint_type}"

    def create_fhir_identifier(
        self,
        provider: Provider,
        value: str,
        endpoint_type: str,
        use: str = "official"
    ) -> dict[str, Any]:
        """
        Unified FHIR identifier creation

        Eliminates duplication between DeviceTransformer and DeviceAssociationTransformer
        """
        return {
            "use": use,
            "system": self.create_provider_system_url(provider, endpoint_type),
            "value": value,
            "assigner": {"display": provider.value.title()}
        }

    def create_measurement_source_tags(self, measurement_source: MeasurementSource) -> list[dict[str, Any]]:
        """
        Unified measurement source tags creation

        Eliminates exact duplication between HealthDataTransformer and ECGTransformer
        """
        source_display_map = {
            MeasurementSource.DEVICE: "Device measurement",
            MeasurementSource.USER: "User-entered measurement",
            MeasurementSource.UNKNOWN: "Unknown source"
        }

        source_display = source_display_map.get(measurement_source, "Unknown source")

        return [{
            "system": self.FHIR_SYSTEMS['MEASUREMENT_SOURCE'],
            "code": measurement_source.value,
            "display": source_display
        }]

    def create_provider_tags(self, provider: Provider) -> list[dict[str, Any]]:
        """
        Unified provider tag creation

        Standardizes provider tagging across all transformers
        """
        return [
            {
                "system": self.FHIR_SYSTEMS['OBSERVATION_VALUE'],
                "code": "auto-generated",
                "display": "Auto-generated"
            },
            {
                "system": self.FHIR_SYSTEMS['PROVIDER_SYSTEM'],
                "code": provider.value,
                "display": provider.value.title()
            }
        ]

    def create_fhir_meta(
        self,
        provider: Provider,
        measurement_source: MeasurementSource | None = None
    ) -> dict[str, Any]:
        """
        Unified FHIR meta section creation

        Combines provider tags and measurement source tags consistently
        """
        tags = self.create_provider_tags(provider)

        if measurement_source:
            tags.extend(self.create_measurement_source_tags(measurement_source))

        return {
            "source": f"#{provider.value}",
            "tag": tags
        }

    def safe_convert_value(self, value: Union[float, dict, str, int], target_type: type = float):
        """
        Unified safe value conversion

        Handles type conversion with fallback for FHIR data consistency
        """
        if isinstance(value, (int, float)) and target_type == float:
            return float(value)
        elif isinstance(value, str):
            try:
                if target_type == float:
                    return float(value)
                elif target_type == int:
                    return int(value)
                else:
                    return str(value)
            except ValueError:
                return 0.0 if target_type == float else 0 if target_type == int else ""
        else:
            return 0.0 if target_type == float else 0 if target_type == int else ""

    def create_fhir_timestamp(self, dt: datetime | None = None) -> str:
        """
        Unified FHIR timestamp creation

        Ensures consistent ISO format with Z suffix
        """
        timestamp = dt or datetime.utcnow()
        return timestamp.isoformat() + "Z"

    def log_transformation(self, resource_type: str, identifier: str):
        """
        Unified transformation logging

        Provides consistent logging across all transformers
        """
        logger.info(f"Transformed {identifier} to FHIR {resource_type}")