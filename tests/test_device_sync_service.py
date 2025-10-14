"""
Unit tests for the modern device sync service
"""

from unittest.mock import Mock, patch

import pytest

from ingestors.constants import DeviceData, DeviceType, Provider
from ingestors.device_sync_service import DeviceSyncService, MockDeviceSyncService, SyncResult
from publishers.fhir.client import FHIRClient


@pytest.fixture
def mock_fhir_client():
    """Mock FHIR client for testing"""
    client = Mock(spec=FHIRClient)
    client.create_resource.return_value = {"id": "test-resource-123"}
    client.search_resource.return_value = {"total": 5, "entry": []}
    return client


@pytest.fixture
def device_sync_service(mock_fhir_client):
    """Create device sync service with mocked dependencies"""
    return DeviceSyncService(fhir_client=mock_fhir_client)


@pytest.fixture
def sample_devices():
    """Create sample device data for testing"""
    return [
        DeviceData(
            provider_device_id="device-1",
            provider=Provider.WITHINGS,
            device_type=DeviceType.SCALE,
            manufacturer="Withings",
            model="Body+ Scale",
            battery_level=80,
        ),
        DeviceData(
            provider_device_id="device-2",
            provider=Provider.WITHINGS,
            device_type=DeviceType.BP_MONITOR,
            manufacturer="Withings",
            model="BPM Core",
            battery_level=60,
        ),
    ]


class TestSyncResult:
    """Test SyncResult dataclass"""

    def test_sync_result_creation_minimal(self):
        """Test creating SyncResult with minimal data"""
        result = SyncResult(user_id="test-user", provider=Provider.WITHINGS)

        assert result.user_id == "test-user"
        assert result.provider == Provider.WITHINGS
        assert result.processed_devices == 0
        assert result.processed_associations == 0
        assert result.deactivated_devices == 0
        assert result.deactivated_associations == 0
        assert result.errors == []
        assert result.success is False
        assert result.sync_timestamp is not None

    def test_sync_result_creation_full(self):
        """Test creating SyncResult with all data"""
        errors = ["Error 1", "Error 2"]
        timestamp = "2023-01-01T10:00:00"

        result = SyncResult(
            user_id="test-user",
            provider=Provider.FITBIT,
            processed_devices=5,
            processed_associations=5,
            deactivated_devices=2,
            deactivated_associations=1,
            errors=errors,
            success=True,
            sync_timestamp=timestamp,
        )

        assert result.user_id == "test-user"
        assert result.provider == Provider.FITBIT
        assert result.processed_devices == 5
        assert result.processed_associations == 5
        assert result.deactivated_devices == 2
        assert result.deactivated_associations == 1
        assert result.errors == errors
        assert result.success is True
        assert result.sync_timestamp == timestamp

    def test_sync_result_post_init(self):
        """Test SyncResult post_init behavior"""
        # Test with None values
        result = SyncResult(user_id="test-user", provider=Provider.WITHINGS, errors=None, sync_timestamp=None)

        assert result.errors == []
        assert result.sync_timestamp is not None


class TestDeviceSyncService:
    """Test DeviceSyncService"""

    def test_init_default_client(self):
        """Test service initialization with default FHIR client"""
        with patch("ingestors.device_sync_service.FHIRClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            service = DeviceSyncService()

            assert service.fhir_client == mock_client
            assert service.device_transformer is not None
            assert service.association_transformer is not None

    def test_init_custom_client(self, mock_fhir_client):
        """Test service initialization with custom FHIR client"""
        service = DeviceSyncService(fhir_client=mock_fhir_client)

        assert service.fhir_client == mock_fhir_client

    @patch.object(DeviceSyncService, "_fetch_devices")
    @patch.object(DeviceSyncService, "_publish_device")
    @patch.object(DeviceSyncService, "_publish_association")
    def test_sync_user_devices_success(
        self, mock_publish_association, mock_publish_device, mock_fetch_devices, device_sync_service, sample_devices
    ):
        """Test successful device synchronization"""
        # Setup mocks
        mock_fetch_devices.return_value = sample_devices
        mock_publish_device.side_effect = [{"id": "device-fhir-1"}, {"id": "device-fhir-2"}]
        mock_publish_association.side_effect = [{"id": "association-fhir-1"}, {"id": "association-fhir-2"}]

        # Test
        result = device_sync_service.sync_user_devices(user_id="test-user", provider=Provider.WITHINGS)

        # Assertions
        assert result.user_id == "test-user"
        assert result.provider == Provider.WITHINGS
        assert result.processed_devices == 2
        assert result.processed_associations == 2
        assert result.errors == []
        assert result.success is True

        # Verify method calls
        mock_fetch_devices.assert_called_once_with("test-user", Provider.WITHINGS)
        assert mock_publish_device.call_count == 2
        assert mock_publish_association.call_count == 2

    @patch.object(DeviceSyncService, "_fetch_devices")
    def test_sync_user_devices_no_devices(self, mock_fetch_devices, device_sync_service):
        """Test synchronization when no devices are found"""
        mock_fetch_devices.return_value = []

        result = device_sync_service.sync_user_devices(user_id="test-user", provider=Provider.WITHINGS)

        assert result.processed_devices == 0
        assert result.processed_associations == 0
        assert result.success is True

    @patch.object(DeviceSyncService, "_fetch_devices")
    def test_sync_user_devices_fetch_error(self, mock_fetch_devices, device_sync_service):
        """Test synchronization when device fetching fails"""
        mock_fetch_devices.side_effect = Exception("API Error")

        result = device_sync_service.sync_user_devices(user_id="test-user", provider=Provider.WITHINGS)

        assert result.success is False
        assert len(result.errors) == 1
        assert "API Error" in result.errors[0]

    @patch.object(DeviceSyncService, "_fetch_devices")
    @patch.object(DeviceSyncService, "_publish_device")
    def test_sync_user_devices_partial_failure(
        self, mock_publish_device, mock_fetch_devices, device_sync_service, sample_devices
    ):
        """Test synchronization with partial device failures"""
        mock_fetch_devices.return_value = sample_devices
        mock_publish_device.side_effect = [{"id": "device-fhir-1"}, Exception("FHIR Error")]

        result = device_sync_service.sync_user_devices(user_id="test-user", provider=Provider.WITHINGS)

        assert result.processed_devices == 1  # Only one device succeeded
        assert result.processed_associations == 1  # Only one association succeeded
        assert len(result.errors) == 1
        assert result.success is False

    def test_sync_user_devices_string_provider(self, device_sync_service):
        """Test synchronization with string provider name"""
        with patch.object(device_sync_service, "_fetch_devices") as mock_fetch:
            mock_fetch.return_value = []

            result = device_sync_service.sync_user_devices(
                user_id="test-user",
                provider="withings",  # String instead of enum
            )

            assert result.provider == Provider.WITHINGS

    def test_sync_user_devices_custom_patient_reference(self, device_sync_service):
        """Test synchronization with custom patient reference"""
        with patch.object(device_sync_service, "_fetch_devices") as mock_fetch:
            mock_fetch.return_value = []

            result = device_sync_service.sync_user_devices(
                user_id="test-user", provider=Provider.WITHINGS, patient_reference="Patient/custom-123"
            )

            # Patient reference should be passed to association publishing
            assert result.user_id == "test-user"

    @patch("ingestors.device_sync_service.DeviceManagerFactory")
    def test_fetch_devices(self, mock_factory, device_sync_service, sample_devices):
        """Test device fetching"""
        mock_manager = Mock()
        mock_manager.fetch_user_devices.return_value = sample_devices
        mock_factory.create.return_value = mock_manager

        devices = device_sync_service._fetch_devices("test-user", Provider.WITHINGS)

        assert devices == sample_devices
        mock_factory.create.assert_called_once_with(Provider.WITHINGS)
        mock_manager.fetch_user_devices.assert_called_once_with("test-user")

    def test_publish_device(self, device_sync_service, sample_devices):
        """Test device publishing"""
        device = sample_devices[0]

        result = device_sync_service._publish_device(device)

        assert result["id"] == "test-resource-123"
        device_sync_service.fhir_client.create_resource.assert_called_once()
        call_args = device_sync_service.fhir_client.create_resource.call_args
        assert call_args[0][0] == "Device"
        assert call_args[0][1]["resourceType"] == "Device"

    def test_publish_association(self, device_sync_service, sample_devices):
        """Test association publishing"""
        device = sample_devices[0]

        result = device_sync_service._publish_association(device, "Patient/test-123", "Device/test-456")

        assert result["id"] == "test-resource-123"
        device_sync_service.fhir_client.create_resource.assert_called_once()
        call_args = device_sync_service.fhir_client.create_resource.call_args
        assert call_args[0][0] == "DeviceAssociation"
        assert call_args[0][1]["resourceType"] == "DeviceAssociation"

    def test_get_sync_statistics(self, device_sync_service):
        """Test sync statistics retrieval"""
        stats = device_sync_service.get_sync_statistics("test-user")

        assert stats["user_id"] == "test-user"
        assert "total_devices_in_system" in stats
        assert "user_device_associations" in stats
        assert "last_check" in stats

        # Verify FHIR queries
        assert device_sync_service.fhir_client.search_resource.call_count == 2

    def test_get_sync_statistics_error(self, device_sync_service):
        """Test sync statistics with FHIR error"""
        device_sync_service.fhir_client.search_resource.side_effect = Exception("FHIR Error")

        stats = device_sync_service.get_sync_statistics("test-user")

        assert stats["user_id"] == "test-user"
        assert "error" in stats
        assert "FHIR Error" in stats["error"]


class TestMockDeviceSyncService:
    """Test MockDeviceSyncService"""

    def test_mock_service_initialization(self):
        """Test mock service initialization"""
        mock_service = MockDeviceSyncService()

        # fhir_client is auto-created by parent class even when None is passed
        assert mock_service.fhir_client is not None
        assert isinstance(mock_service.fhir_client, FHIRClient)
        assert mock_service.published_devices == []
        assert mock_service.published_associations == []

    @patch.object(MockDeviceSyncService, "_fetch_devices")
    def test_mock_service_sync(self, mock_fetch_devices, sample_devices):
        """Test mock service synchronization"""
        mock_service = MockDeviceSyncService()
        mock_fetch_devices.return_value = sample_devices

        result = mock_service.sync_user_devices(user_id="test-user", provider=Provider.WITHINGS)

        assert result.processed_devices == 2
        assert result.processed_associations == 2
        assert len(mock_service.published_devices) == 2
        assert len(mock_service.published_associations) == 2

    def test_mock_publish_device(self, sample_devices):
        """Test mock device publishing"""
        mock_service = MockDeviceSyncService()
        device = sample_devices[0]

        result = mock_service._publish_device(device)

        assert result["id"] == "mock-device-0"
        assert result["resourceType"] == "Device"
        assert len(mock_service.published_devices) == 1

    def test_mock_publish_association(self, sample_devices):
        """Test mock association publishing"""
        mock_service = MockDeviceSyncService()
        device = sample_devices[0]

        result = mock_service._publish_association(device, "Patient/test-123", "Device/test-456")

        assert result["id"] == "mock-association-0"
        assert result["resourceType"] == "DeviceAssociation"
        assert len(mock_service.published_associations) == 1


if __name__ == "__main__":
    pytest.main([__file__])
