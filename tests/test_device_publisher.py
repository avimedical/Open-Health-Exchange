"""
Tests for Device Publisher - FHIR Device resource management.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from ingestors.constants import DeviceData, Provider
from publishers.fhir.device_publisher import DevicePublisher


class TestDevicePublisher:
    """Tests for DevicePublisher class."""

    @pytest.fixture
    def publisher(self):
        """Create a DevicePublisher instance with mocked dependencies."""
        with (
            patch("publishers.fhir.device_publisher.FHIRClient") as mock_client,
            patch("publishers.fhir.device_publisher.DeviceTransformer") as mock_transformer,
        ):
            publisher = DevicePublisher()
            publisher.fhir_client = mock_client.return_value
            publisher.transformer = mock_transformer.return_value
            yield publisher

    @pytest.fixture
    def sample_device_data(self):
        """Create sample DeviceData for testing."""
        return DeviceData(
            provider=Provider.WITHINGS,
            provider_device_id="device-123",
            device_type="Blood Pressure Monitor",
            model="BPM Connect",
            manufacturer="Withings",
            firmware_version="1.0.0",
            battery_level=85.0,
            last_sync=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    def test_publish_device_success(self, publisher, sample_device_data):
        """Test successful device publication."""
        fhir_device = {
            "resourceType": "Device",
            "id": "fhir-device-123",
            "status": "active",
        }
        publisher.transformer.transform.return_value = fhir_device
        publisher.fhir_client.update_resource.return_value = {
            **fhir_device,
        }

        result = publisher.publish_device(sample_device_data, "Patient/test-user")

        assert result["id"] == "fhir-device-123"
        publisher.transformer.transform.assert_called_once_with(sample_device_data)
        publisher.fhir_client.update_resource.assert_called_once_with("Device", "fhir-device-123", fhir_device)

    def test_publish_device_without_patient_reference(self, publisher, sample_device_data):
        """Test device publication works without patient reference."""
        fhir_device = {"resourceType": "Device", "id": "device-456"}
        publisher.transformer.transform.return_value = fhir_device
        publisher.fhir_client.update_resource.return_value = fhir_device

        result = publisher.publish_device(sample_device_data)

        assert result is not None
        publisher.transformer.transform.assert_called_once()

    def test_publish_device_error_raises(self, publisher, sample_device_data):
        """Test that errors during publication are raised."""
        publisher.transformer.transform.side_effect = Exception("Transform error")

        with pytest.raises(Exception, match="Transform error"):
            publisher.publish_device(sample_device_data, "Patient/test-user")

    def test_publish_device_fhir_error(self, publisher, sample_device_data):
        """Test FHIR server error during device publication."""
        fhir_device = {"resourceType": "Device", "id": "device-123"}
        publisher.transformer.transform.return_value = fhir_device
        publisher.fhir_client.update_resource.side_effect = Exception("FHIR server error")

        with pytest.raises(Exception, match="FHIR server error"):
            publisher.publish_device(sample_device_data, "Patient/test-user")


class TestDevicePublisherBatch:
    """Tests for batch device operations."""

    @pytest.fixture
    def publisher(self):
        """Create a DevicePublisher instance with mocked dependencies."""
        with (
            patch("publishers.fhir.device_publisher.FHIRClient") as mock_client,
            patch("publishers.fhir.device_publisher.DeviceTransformer") as mock_transformer,
        ):
            publisher = DevicePublisher()
            publisher.fhir_client = mock_client.return_value
            publisher.transformer = mock_transformer.return_value
            yield publisher

    @pytest.fixture
    def multiple_devices(self):
        """Create multiple DeviceData for batch testing."""
        return [
            DeviceData(
                provider=Provider.WITHINGS,
                provider_device_id="device-1",
                device_type="Scale",
                model="Body+",
                manufacturer="Withings",
            ),
            DeviceData(
                provider=Provider.WITHINGS,
                provider_device_id="device-2",
                device_type="Blood Pressure Monitor",
                model="BPM Connect",
                manufacturer="Withings",
            ),
            DeviceData(
                provider=Provider.FITBIT,
                provider_device_id="device-3",
                device_type="Activity Tracker",
                model="Charge 5",
                manufacturer="Fitbit",
            ),
        ]

    def test_publish_devices_batch_all_success(self, publisher, multiple_devices):
        """Test batch publication when all devices succeed."""
        publisher.transformer.transform.side_effect = [
            {"resourceType": "Device", "id": "fhir-device-1"},
            {"resourceType": "Device", "id": "fhir-device-2"},
            {"resourceType": "Device", "id": "fhir-device-3"},
        ]
        publisher.fhir_client.update_resource.side_effect = [
            {"id": "fhir-device-1"},
            {"id": "fhir-device-2"},
            {"id": "fhir-device-3"},
        ]

        successful, errors = publisher.publish_devices_batch(multiple_devices, "Patient/test-user")

        assert len(successful) == 3
        assert len(errors) == 0
        assert publisher.fhir_client.update_resource.call_count == 3

        # Verify update_resource was called with correct IDs
        calls = publisher.fhir_client.update_resource.call_args_list
        assert calls[0].args[1] == "fhir-device-1"
        assert calls[1].args[1] == "fhir-device-2"
        assert calls[2].args[1] == "fhir-device-3"

    def test_publish_devices_batch_partial_failure(self, publisher, multiple_devices):
        """Test batch publication with partial failures."""
        publisher.transformer.transform.side_effect = [
            {"resourceType": "Device", "id": "fhir-device-1"},
            {"resourceType": "Device", "id": "fhir-device-2"},
            {"resourceType": "Device", "id": "fhir-device-3"},
        ]
        publisher.fhir_client.update_resource.side_effect = [
            {"id": "fhir-device-1"},
            Exception("FHIR error for device-2"),
            {"id": "fhir-device-3"},
        ]

        successful, errors = publisher.publish_devices_batch(multiple_devices, "Patient/test-user")

        assert len(successful) == 2
        assert len(errors) == 1
        assert "FHIR error for device-2" in str(errors[0])

        # Verify update_resource was called with correct IDs
        calls = publisher.fhir_client.update_resource.call_args_list
        assert calls[0].args[1] == "fhir-device-1"
        assert calls[1].args[1] == "fhir-device-2"
        assert calls[2].args[1] == "fhir-device-3"

    def test_publish_devices_batch_all_failures(self, publisher, multiple_devices):
        """Test batch publication when all devices fail."""
        publisher.transformer.transform.side_effect = Exception("Transform failed")

        successful, errors = publisher.publish_devices_batch(multiple_devices, "Patient/test-user")

        assert len(successful) == 0
        assert len(errors) == 3

    def test_publish_devices_batch_empty_list(self, publisher):
        """Test batch publication with empty device list."""
        successful, errors = publisher.publish_devices_batch([], "Patient/test-user")

        assert len(successful) == 0
        assert len(errors) == 0


class TestDevicePublisherSearch:
    """Tests for device search functionality."""

    @pytest.fixture
    def publisher(self):
        """Create a DevicePublisher instance with mocked dependencies."""
        with (
            patch("publishers.fhir.device_publisher.FHIRClient") as mock_client,
            patch("publishers.fhir.device_publisher.DeviceTransformer"),
        ):
            publisher = DevicePublisher()
            publisher.fhir_client = mock_client.return_value
            yield publisher

    def test_find_devices_by_provider_success(self, publisher):
        """Test finding devices by provider."""
        bundle = {
            "total": 2,
            "entry": [
                {"resource": {"id": "device-1", "manufacturer": "Withings"}},
                {"resource": {"id": "device-2", "manufacturer": "Withings"}},
            ],
        }
        publisher.fhir_client.search_resource.return_value = bundle

        devices = publisher.find_devices_by_provider("withings", "Patient/test-user")

        assert len(devices) == 2
        assert devices[0]["id"] == "device-1"
        publisher.fhir_client.search_resource.assert_called_once()

    def test_find_devices_by_provider_no_results(self, publisher):
        """Test finding devices when none exist."""
        bundle = {"total": 0, "entry": []}
        publisher.fhir_client.search_resource.return_value = bundle

        devices = publisher.find_devices_by_provider("withings", "Patient/test-user")

        assert len(devices) == 0

    def test_find_devices_by_provider_error(self, publisher):
        """Test error handling in device search."""
        publisher.fhir_client.search_resource.side_effect = Exception("Search failed")

        with pytest.raises(Exception, match="Search failed"):
            publisher.find_devices_by_provider("withings", "Patient/test-user")

    def test_get_device_by_provider_id_found(self, publisher):
        """Test getting a device by provider ID when found."""
        device = {"id": "fhir-device-123", "status": "active"}
        publisher.fhir_client.find_resource_by_identifier.return_value = device

        result = publisher.get_device_by_provider_id("withings", "provider-device-123")

        assert result == device
        publisher.fhir_client.find_resource_by_identifier.assert_called_once_with(
            "Device", "https://api.withings.com/device-id", "provider-device-123"
        )

    def test_get_device_by_provider_id_not_found(self, publisher):
        """Test getting a device by provider ID when not found."""
        publisher.fhir_client.find_resource_by_identifier.return_value = None

        result = publisher.get_device_by_provider_id("fitbit", "unknown-device")

        assert result is None

    def test_get_device_by_provider_id_error(self, publisher):
        """Test error handling in get device by provider ID."""
        publisher.fhir_client.find_resource_by_identifier.side_effect = Exception("FHIR error")

        with pytest.raises(Exception, match="FHIR error"):
            publisher.get_device_by_provider_id("withings", "device-123")


class TestDevicePublisherDeactivation:
    """Tests for device deactivation functionality."""

    @pytest.fixture
    def publisher(self):
        """Create a DevicePublisher instance with mocked dependencies."""
        with (
            patch("publishers.fhir.device_publisher.FHIRClient") as mock_client,
            patch("publishers.fhir.device_publisher.DeviceTransformer"),
        ):
            publisher = DevicePublisher()
            publisher.fhir_client = mock_client.return_value
            yield publisher

    def test_deactivate_missing_devices_success(self, publisher):
        """Test deactivating devices that are no longer active."""
        existing_devices = [
            {
                "id": "fhir-device-1",
                "status": "active",
                "identifier": [{"system": "https://api.withings.com/device-id", "value": "device-1"}],
            },
            {
                "id": "fhir-device-2",
                "status": "active",
                "identifier": [{"system": "https://api.withings.com/device-id", "value": "device-2"}],
            },
        ]
        publisher.fhir_client.search_resource.return_value = {
            "total": 2,
            "entry": [{"resource": d} for d in existing_devices],
        }
        publisher.fhir_client.update_resource.return_value = {
            **existing_devices[1],
            "status": "inactive",
        }

        # Only device-1 is still active in provider API
        deactivated = publisher.deactivate_missing_devices(["device-1"], "withings", "Patient/test-user")

        assert len(deactivated) == 1
        publisher.fhir_client.update_resource.assert_called_once()
        # Verify the device status was set to inactive
        call_args = publisher.fhir_client.update_resource.call_args
        assert call_args[0][2]["status"] == "inactive"

    def test_deactivate_missing_devices_none_to_deactivate(self, publisher):
        """Test when all devices are still active in provider."""
        existing_devices = [
            {
                "id": "fhir-device-1",
                "status": "active",
                "identifier": [{"system": "https://api.withings.com/device-id", "value": "device-1"}],
            },
        ]
        publisher.fhir_client.search_resource.return_value = {
            "total": 1,
            "entry": [{"resource": existing_devices[0]}],
        }

        # All devices are still active
        deactivated = publisher.deactivate_missing_devices(["device-1"], "withings", "Patient/test-user")

        assert len(deactivated) == 0
        publisher.fhir_client.update_resource.assert_not_called()

    def test_deactivate_missing_devices_error(self, publisher):
        """Test error handling in deactivation."""
        publisher.fhir_client.search_resource.side_effect = Exception("Search failed")

        with pytest.raises(Exception, match="Search failed"):
            publisher.deactivate_missing_devices([], "withings", "Patient/test-user")


class TestDevicePublisherStatistics:
    """Tests for device statistics functionality."""

    @pytest.fixture
    def publisher(self):
        """Create a DevicePublisher instance with mocked dependencies."""
        with (
            patch("publishers.fhir.device_publisher.FHIRClient") as mock_client,
            patch("publishers.fhir.device_publisher.DeviceTransformer"),
        ):
            publisher = DevicePublisher()
            publisher.fhir_client = mock_client.return_value
            yield publisher

    def test_get_device_statistics_success(self, publisher):
        """Test getting device statistics."""
        devices = [
            {
                "id": "device-1",
                "status": "active",
                "identifier": [{"system": "https://api.withings.com/device-id", "value": "w1"}],
                "type": [{"text": "Scale"}],
            },
            {
                "id": "device-2",
                "status": "active",
                "identifier": [{"system": "https://api.withings.com/device-id", "value": "w2"}],
                "type": [{"text": "Blood Pressure Monitor"}],
            },
            {
                "id": "device-3",
                "status": "inactive",
                "identifier": [{"system": "https://api.fitbit.com/device-id", "value": "f1"}],
                "type": [{"text": "Activity Tracker"}],
            },
        ]
        publisher.fhir_client.search_resource.return_value = {
            "total": 3,
            "entry": [{"resource": d} for d in devices],
        }

        stats = publisher.get_device_statistics("Patient/test-user")

        assert stats["total_devices"] == 3
        assert stats["active_devices"] == 2
        assert stats["inactive_devices"] == 1
        assert stats["devices_by_provider"]["withings"] == 2
        assert stats["devices_by_provider"]["fitbit"] == 1
        assert stats["devices_by_type"]["Scale"] == 1
        assert stats["devices_by_type"]["Blood Pressure Monitor"] == 1
        assert stats["devices_by_type"]["Activity Tracker"] == 1

    def test_get_device_statistics_empty(self, publisher):
        """Test statistics when no devices exist."""
        publisher.fhir_client.search_resource.return_value = {"total": 0, "entry": []}

        stats = publisher.get_device_statistics("Patient/test-user")

        assert stats["total_devices"] == 0
        assert stats["active_devices"] == 0
        assert stats["inactive_devices"] == 0
        assert stats["devices_by_provider"] == {}
        assert stats["devices_by_type"] == {}

    def test_get_device_statistics_error(self, publisher):
        """Test error handling in statistics."""
        publisher.fhir_client.search_resource.side_effect = Exception("FHIR error")

        with pytest.raises(Exception, match="FHIR error"):
            publisher.get_device_statistics("Patient/test-user")


class TestDevicePublisherHelpers:
    """Tests for helper methods."""

    @pytest.fixture
    def publisher(self):
        """Create a DevicePublisher instance with mocked dependencies."""
        with (
            patch("publishers.fhir.device_publisher.FHIRClient"),
            patch("publishers.fhir.device_publisher.DeviceTransformer"),
        ):
            yield DevicePublisher()

    def test_extract_provider_device_id_found(self, publisher):
        """Test extracting provider device ID from FHIR device."""
        device = {
            "identifier": [
                {"system": "https://api.withings.com/device-id", "value": "device-123"},
                {"system": "http://other.system", "value": "other-id"},
            ]
        }

        result = publisher._extract_provider_device_id(device, "withings")

        assert result == "device-123"

    def test_extract_provider_device_id_not_found(self, publisher):
        """Test extracting provider device ID when not present."""
        device = {
            "identifier": [
                {"system": "http://other.system", "value": "other-id"},
            ]
        }

        result = publisher._extract_provider_device_id(device, "withings")

        assert result is None

    def test_extract_provider_device_id_no_identifiers(self, publisher):
        """Test extracting provider device ID with no identifiers."""
        device = {}

        result = publisher._extract_provider_device_id(device, "withings")

        assert result is None

    def test_get_device_provider_withings(self, publisher):
        """Test extracting provider from Withings device."""
        device = {"identifier": [{"system": "https://api.withings.com/device-id", "value": "w123"}]}

        result = publisher._get_device_provider(device)

        assert result == "withings"

    def test_get_device_provider_fitbit(self, publisher):
        """Test extracting provider from Fitbit device."""
        device = {"identifier": [{"system": "https://api.fitbit.com/device-id", "value": "f123"}]}

        result = publisher._get_device_provider(device)

        assert result == "fitbit"

    def test_get_device_provider_unknown(self, publisher):
        """Test extracting provider from unknown device."""
        device = {"identifier": [{"system": "https://api.unknown.com/device-id", "value": "u123"}]}

        result = publisher._get_device_provider(device)

        assert result is None

    def test_get_device_type_present(self, publisher):
        """Test extracting device type when present."""
        device = {"type": [{"text": "Blood Pressure Monitor"}]}

        result = publisher._get_device_type(device)

        assert result == "Blood Pressure Monitor"

    def test_get_device_type_empty(self, publisher):
        """Test extracting device type when empty."""
        device = {"type": []}

        result = publisher._get_device_type(device)

        assert result is None

    def test_get_device_type_missing(self, publisher):
        """Test extracting device type when missing."""
        device = {}

        result = publisher._get_device_type(device)

        assert result is None

    def test_get_device_type_unknown_text(self, publisher):
        """Test extracting device type with missing text field."""
        device = {"type": [{"coding": [{"code": "123"}]}]}

        result = publisher._get_device_type(device)

        assert result == "unknown"

    def test_cache_device_mapping(self, publisher):
        """Test caching device mapping (currently disabled)."""
        # This should not raise even though caching is disabled
        device_data = MagicMock()
        publisher._cache_device_mapping(device_data, "fhir-device-123")

    def test_get_cached_device_id(self, publisher):
        """Test getting cached device ID (currently returns None)."""
        result = publisher._get_cached_device_id("withings", "device-123")

        assert result is None

    def test_remove_device_from_cache(self, publisher):
        """Test removing device from cache (currently no-op)."""
        # Should not raise
        publisher._remove_device_from_cache("withings", "device-123")
