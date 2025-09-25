"""
Modern FHIR R5 transformers using Python 3.13+ features
Now inherits from BaseFHIRTransformer to eliminate duplication
"""
import logging
from datetime import datetime
from enum import StrEnum
from dataclasses import dataclass
from typing import Any, Protocol

from ingestors.constants import DeviceData, DeviceType, Provider
from .base_fhir_transformer import BaseFHIRTransformer


logger = logging.getLogger(__name__)


class FHIRSystem(StrEnum):
    """FHIR system URLs"""
    SNOMED = "http://snomed.info/sct"
    UCUM = "http://unitsofmeasure.org"
    DEVICE_VERSION_TYPE = "http://terminology.hl7.org/CodeSystem/device-version-type"
    DEVICE_PROPERTY_TYPE = "http://terminology.hl7.org/CodeSystem/device-property-type"
    DEVICE_ASSOCIATION_CATEGORY = "http://hl7.org/fhir/device-association-category"
    DEVICE_ASSOCIATION_STATUS = "http://hl7.org/fhir/device-association-status"
    DEVICE_ASSOCIATION_OPERATION_STATUS = "http://hl7.org/fhir/device-association-operation-status"
    MRI_SAFETY = "urn:oid:2.16.840.1.113883.3.26.1.1"


@dataclass(slots=True, frozen=True)
class SnomedCode:
    """SNOMED CT code mapping"""
    code: str
    display: str


# SNOMED CT mappings for device types
DEVICE_TYPE_SNOMED = {
    DeviceType.BP_MONITOR: SnomedCode("43770009", "Sphygmomanometer"),
    DeviceType.SCALE: SnomedCode("19892000", "Scale"),
    DeviceType.ACTIVITY_TRACKER: SnomedCode("466093008", "Activity tracker"),
    DeviceType.SMARTWATCH: SnomedCode("706767009", "Wearable device"),
    DeviceType.THERMOMETER: SnomedCode("86184003", "Thermometer"),
    DeviceType.PULSE_OXIMETER: SnomedCode("258185003", "Pulse oximeter"),
    DeviceType.UNKNOWN: SnomedCode("49062001", "Device"),
}


class FHIRTransformer(Protocol):
    """Protocol for FHIR transformers"""
    def transform(self, data: Any) -> dict[str, Any]: ...


class DeviceTransformer(BaseFHIRTransformer):
    """Transforms device data to FHIR R5 Device resources

    Inherits unified FHIR methods from BaseFHIRTransformer
    """

    def transform(self, device: DeviceData) -> dict[str, Any]:
        """Transform device data to FHIR Device resource"""
        # Use ONLY the raw device ID from the provider
        device_id = device.provider_device_id

        fhir_device = {
            "resourceType": "Device",
            "id": device_id,
            "identifier": [self.create_fhir_identifier(device.provider, device.provider_device_id, "device-id")],
            "status": "active",
            "manufacturer": device.manufacturer,
            "name": device.model,  # Model name in name attribute
            "displayName": device.model,  # Model name in displayName attribute
            "deviceName": [{"value": device.model}],
            "type": [self._create_device_type(device.device_type)],
            "safety": [self._create_safety_info()],
            "note": [self._create_note(device)],
        }

        # Add optional fields
        if device.firmware_version:
            fhir_device["version"] = [self._create_version(device.firmware_version)]

        if properties := self._create_properties(device):
            fhir_device["property"] = properties

        self.log_transformation("Device", device.provider_device_id)
        return fhir_device

    # _create_identifier removed - now using unified create_fhir_identifier from base class

    def _create_device_type(self, device_type: DeviceType) -> dict[str, Any]:
        """Create FHIR device type coding"""
        snomed = DEVICE_TYPE_SNOMED[device_type]
        return {
            "coding": [{
                "system": FHIRSystem.SNOMED,
                "code": snomed.code,
                "display": snomed.display
            }],
            "text": snomed.display
        }

    def _create_version(self, firmware_version: str) -> dict[str, Any]:
        """Create FHIR version information"""
        return {
            "type": {
                "coding": [{
                    "system": FHIRSystem.DEVICE_VERSION_TYPE,
                    "code": "firmware-version",
                    "display": "Firmware Version"
                }]
            },
            "value": firmware_version
        }

    def _create_properties(self, device: DeviceData) -> list[dict[str, Any]]:
        """Create FHIR device properties"""
        properties = []

        if device.battery_level is not None:
            properties.append({
                "type": {
                    "coding": [{
                        "system": FHIRSystem.DEVICE_PROPERTY_TYPE,
                        "code": "battery-level",
                        "display": "Battery Level"
                    }]
                },
                "valueQuantity": {
                    "value": device.battery_level,
                    "unit": "%",
                    "system": FHIRSystem.UCUM,
                    "code": "%"
                }
            })

        if device.last_sync:
            properties.append({
                "type": {"text": "Last Sync Time"},
                "valueDateTime": device.last_sync
            })

        return properties

    def _create_safety_info(self) -> dict[str, Any]:
        """Create MRI safety information"""
        return {
            "coding": [{
                "system": FHIRSystem.MRI_SAFETY,
                "code": "mr-unsafe",
                "display": "MR Unsafe"
            }]
        }

    def _create_note(self, device: DeviceData) -> dict[str, Any]:
        """Create device note"""
        return {
            "time": datetime.utcnow().isoformat() + "Z",
            "text": f"Device synchronized from {device.provider.title()} Health Platform"
        }


class DeviceAssociationTransformer(BaseFHIRTransformer):
    """Transforms device associations to FHIR R5 DeviceAssociation resources

    Inherits unified FHIR methods from BaseFHIRTransformer
    """

    def transform(self, device: DeviceData, patient_ref: str, device_ref: str) -> dict[str, Any]:
        """Transform to FHIR DeviceAssociation resource"""
        # Create unique association ID using device ID and patient ID
        patient_id = patient_ref.split('/')[-1]  # Extract patient ID from reference
        association_id = f"{device.provider_device_id}-{patient_id}"
        timestamp = self.create_fhir_timestamp()

        return {
            "resourceType": "DeviceAssociation",
            "id": association_id,
            "identifier": [
                self.create_fhir_identifier(device.provider, device.provider_device_id, "device-association")
            ],
            "device": {"reference": device_ref},
            "category": [self._create_category()],
            "status": self._create_status("attached"),
            "subject": {"reference": patient_ref},
            "period": {"start": timestamp},
            "operator": [{"reference": patient_ref}],
            "operation": [self._create_operation(patient_ref, timestamp)]
        }

    # _create_identifier removed - now using unified create_fhir_identifier from base class

    def _create_category(self) -> dict[str, Any]:
        """Create association category"""
        return {
            "coding": [{
                "system": FHIRSystem.DEVICE_ASSOCIATION_CATEGORY,
                "code": "home-use",
                "display": "Home Use"
            }]
        }

    def _create_status(self, status_code: str) -> dict[str, Any]:
        """Create association status"""
        return {
            "coding": [{
                "system": FHIRSystem.DEVICE_ASSOCIATION_STATUS,
                "code": status_code,
                "display": status_code.title()
            }]
        }

    def _create_operation(self, patient_ref: str, timestamp: str) -> dict[str, Any]:
        """Create operation information"""
        return {
            "status": {
                "coding": [{
                    "system": FHIRSystem.DEVICE_ASSOCIATION_OPERATION_STATUS,
                    "code": "active",
                    "display": "Active"
                }]
            },
            "operator": [{"reference": patient_ref}],
            "period": {"start": timestamp}
        }


# Convenience functions for backward compatibility
def transform_device(device: DeviceData) -> dict[str, Any]:
    """Transform device to FHIR Device resource"""
    return DeviceTransformer().transform(device)


def transform_device_association(
    device: DeviceData, patient_ref: str, device_ref: str
) -> dict[str, Any]:
    """Transform to FHIR DeviceAssociation resource"""
    return DeviceAssociationTransformer().transform(device, patient_ref, device_ref)