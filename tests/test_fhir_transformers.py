"""
Unit tests for FHIR transformers
"""
import pytest
from datetime import datetime
from unittest.mock import patch

from transformers.fhir_transformers import (
    DeviceTransformer, DeviceAssociationTransformer,
    FHIRSystem, DEVICE_TYPE_SNOMED,
    transform_device, transform_device_association
)
from ingestors.constants import DeviceData, DeviceType, Provider


@pytest.fixture
def sample_device():
    """Create a sample device for testing"""
    return DeviceData(
        provider_device_id="test-123",
        provider=Provider.WITHINGS,
        device_type=DeviceType.SCALE,
        manufacturer="Withings",
        model="Body+ Scale",
        battery_level=75,
        last_sync="2023-01-01T10:00:00Z",
        firmware_version="1.2.3",
        raw_data={"sync_status": "active"}
    )


@pytest.fixture
def device_transformer():
    """Create a device transformer instance"""
    return DeviceTransformer()


@pytest.fixture
def association_transformer():
    """Create a device association transformer instance"""
    return DeviceAssociationTransformer()


class TestDeviceTransformer:
    """Test cases for DeviceTransformer"""

    def test_transform_basic_device(self, device_transformer, sample_device):
        """Test basic device transformation"""
        result = device_transformer.transform(sample_device)

        # Basic structure
        assert result["resourceType"] == "Device"
        assert result["id"] == "device-withings-test-123"
        assert result["status"] == "active"
        assert result["manufacturer"] == "Withings"

    def test_transform_device_identifier(self, device_transformer, sample_device):
        """Test device identifier creation"""
        result = device_transformer.transform(sample_device)

        identifier = result["identifier"][0]
        assert identifier["use"] == "official"
        assert identifier["system"] == "https://api.withings.com/device-id"
        assert identifier["value"] == "test-123"
        assert identifier["assigner"]["display"] == "Withings Health Platform"

    def test_transform_device_type(self, device_transformer, sample_device):
        """Test device type coding"""
        result = device_transformer.transform(sample_device)

        device_type = result["type"][0]
        coding = device_type["coding"][0]
        snomed = DEVICE_TYPE_SNOMED[DeviceType.SCALE]

        assert coding["system"] == FHIRSystem.SNOMED
        assert coding["code"] == snomed.code
        assert coding["display"] == snomed.display
        assert device_type["text"] == snomed.display

    def test_transform_device_name(self, device_transformer, sample_device):
        """Test device name creation"""
        result = device_transformer.transform(sample_device)

        device_name = result["deviceName"][0]
        assert device_name["value"] == "Body+ Scale"

    def test_transform_version_info(self, device_transformer, sample_device):
        """Test firmware version transformation"""
        result = device_transformer.transform(sample_device)

        version = result["version"][0]
        assert version["value"] == "1.2.3"
        assert version["type"]["coding"][0]["code"] == "firmware-version"

    def test_transform_battery_property(self, device_transformer, sample_device):
        """Test battery level property"""
        result = device_transformer.transform(sample_device)

        properties = result["property"]
        battery_prop = next(
            p for p in properties
            if p["type"]["coding"][0]["code"] == "battery-level"
        )

        assert battery_prop["valueQuantity"]["value"] == 75
        assert battery_prop["valueQuantity"]["unit"] == "%"
        assert battery_prop["valueQuantity"]["system"] == FHIRSystem.UCUM

    def test_transform_last_sync_property(self, device_transformer, sample_device):
        """Test last sync property"""
        result = device_transformer.transform(sample_device)

        properties = result["property"]
        sync_prop = next(
            p for p in properties
            if p["type"]["text"] == "Last Sync Time"
        )

        assert sync_prop["valueDateTime"] == "2023-01-01T10:00:00Z"

    def test_transform_safety_info(self, device_transformer, sample_device):
        """Test MRI safety information"""
        result = device_transformer.transform(sample_device)

        safety = result["safety"][0]
        coding = safety["coding"][0]
        assert coding["system"] == FHIRSystem.MRI_SAFETY
        assert coding["code"] == "mr-unsafe"

    def test_transform_note(self, device_transformer, sample_device):
        """Test device note creation"""
        with patch('transformers.fhir_transformers.datetime') as mock_dt:
            mock_dt.utcnow.return_value = datetime(2023, 1, 1, 12, 0, 0)

            result = device_transformer.transform(sample_device)

            note = result["note"][0]
            assert note["time"] == "2023-01-01T12:00:00Z"
            assert "Withings Health Platform" in note["text"]

    def test_transform_minimal_device(self, device_transformer):
        """Test transformation with minimal device data"""
        minimal_device = DeviceData(
            provider_device_id="minimal-123",
            provider=Provider.FITBIT,
            device_type=DeviceType.UNKNOWN,
            manufacturer="Fitbit",
            model="Unknown"
        )

        result = device_transformer.transform(minimal_device)

        # Should still have basic fields
        assert result["resourceType"] == "Device"
        assert result["id"] == "device-fitbit-minimal-123"
        assert result["manufacturer"] == "Fitbit"

        # Should not have optional fields
        assert "version" not in result
        assert "property" not in result or len(result["property"]) == 0

    def test_transform_unknown_device_type(self, device_transformer, sample_device):
        """Test transformation with unknown device type"""
        sample_device.device_type = DeviceType.UNKNOWN

        result = device_transformer.transform(sample_device)

        device_type = result["type"][0]
        coding = device_type["coding"][0]
        snomed = DEVICE_TYPE_SNOMED[DeviceType.UNKNOWN]

        assert coding["code"] == snomed.code
        assert coding["display"] == snomed.display


class TestDeviceAssociationTransformer:
    """Test cases for DeviceAssociationTransformer"""

    def test_transform_basic_association(self, association_transformer, sample_device):
        """Test basic association transformation"""
        patient_ref = "Patient/test-patient-123"
        device_ref = "Device/test-device-456"

        result = association_transformer.transform(sample_device, patient_ref, device_ref)

        assert result["resourceType"] == "DeviceAssociation"
        assert result["id"] == "association-withings-test-123"
        assert result["device"]["reference"] == device_ref
        assert result["subject"]["reference"] == patient_ref

    def test_transform_identifiers(self, association_transformer, sample_device):
        """Test association identifier creation"""
        result = association_transformer.transform(
            sample_device, "Patient/123", "Device/456"
        )

        identifiers = result["identifier"]

        # Primary identifier
        primary = identifiers[0]
        assert primary["use"] == "official"
        assert primary["system"] == "https://api.withings.com/device-association"
        assert primary["value"] == "test-123-association"

        # Secondary identifier
        secondary = identifiers[1]
        assert secondary["use"] == "secondary"
        assert secondary["value"] == "test-123"

    def test_transform_category(self, association_transformer, sample_device):
        """Test association category"""
        result = association_transformer.transform(
            sample_device, "Patient/123", "Device/456"
        )

        category = result["category"][0]
        coding = category["coding"][0]
        assert coding["system"] == FHIRSystem.DEVICE_ASSOCIATION_CATEGORY
        assert coding["code"] == "home-use"

    def test_transform_status(self, association_transformer, sample_device):
        """Test association status"""
        result = association_transformer.transform(
            sample_device, "Patient/123", "Device/456"
        )

        status = result["status"]
        coding = status["coding"][0]
        assert coding["system"] == FHIRSystem.DEVICE_ASSOCIATION_STATUS
        assert coding["code"] == "attached"

    def test_transform_operation(self, association_transformer, sample_device):
        """Test operation information"""
        patient_ref = "Patient/test-patient-123"

        with patch('transformers.fhir_transformers.datetime') as mock_dt:
            mock_dt.utcnow.return_value = datetime(2023, 1, 1, 12, 0, 0)

            result = association_transformer.transform(
                sample_device, patient_ref, "Device/456"
            )

            operation = result["operation"][0]

            # Status
            status = operation["status"]
            assert status["coding"][0]["code"] == "active"

            # Operator
            operator = operation["operator"][0]
            assert operator["reference"] == patient_ref

            # Period
            period = operation["period"]
            assert period["start"] == "2023-01-01T12:00:00Z"

    def test_transform_period(self, association_transformer, sample_device):
        """Test association period"""
        with patch('transformers.fhir_transformers.datetime') as mock_dt:
            mock_dt.utcnow.return_value = datetime(2023, 1, 1, 12, 0, 0)

            result = association_transformer.transform(
                sample_device, "Patient/123", "Device/456"
            )

            period = result["period"]
            assert period["start"] == "2023-01-01T12:00:00Z"

    def test_transform_operator(self, association_transformer, sample_device):
        """Test operator reference"""
        patient_ref = "Patient/test-patient-123"

        result = association_transformer.transform(
            sample_device, patient_ref, "Device/456"
        )

        operator = result["operator"][0]
        assert operator["reference"] == patient_ref


class TestConvenienceFunctions:
    """Test convenience functions"""

    def test_transform_device_function(self, sample_device):
        """Test standalone transform_device function"""
        result = transform_device(sample_device)

        assert result["resourceType"] == "Device"
        assert result["id"] == "device-withings-test-123"

    def test_transform_device_association_function(self, sample_device):
        """Test standalone transform_device_association function"""
        patient_ref = "Patient/123"
        device_ref = "Device/456"

        result = transform_device_association(sample_device, patient_ref, device_ref)

        assert result["resourceType"] == "DeviceAssociation"
        assert result["subject"]["reference"] == patient_ref
        assert result["device"]["reference"] == device_ref


class TestFHIRSystems:
    """Test FHIR system constants"""

    def test_fhir_system_values(self):
        """Test that FHIR system URLs are correct"""
        assert FHIRSystem.SNOMED == "http://snomed.info/sct"
        assert FHIRSystem.UCUM == "http://unitsofmeasure.org"
        assert "device-association-category" in FHIRSystem.DEVICE_ASSOCIATION_CATEGORY

    def test_snomed_mappings(self):
        """Test SNOMED code mappings exist for all device types"""
        for device_type in DeviceType:
            assert device_type in DEVICE_TYPE_SNOMED
            snomed = DEVICE_TYPE_SNOMED[device_type]
            assert snomed.code
            assert snomed.display


if __name__ == "__main__":
    pytest.main([__file__])