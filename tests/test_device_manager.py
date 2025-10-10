"""
Unit tests for the modern device manager
"""

from dataclasses import dataclass
from unittest.mock import Mock, patch

import pytest

from ingestors.constants import DeviceType, Provider
from ingestors.device_manager import (
    AuthenticationError,
    DeviceManager,
    DeviceManagerError,
    DeviceManagerFactory,
    OAuthCredentials,
)


@dataclass
class MockWithingsDevice:
    """Mock Withings device for testing"""

    deviceid: int
    type: str
    model: str
    battery: str
    timezone: str = "UTC"


@pytest.fixture
def mock_user_auth():
    """Mock UserSocialAuth object"""
    mock = Mock()
    mock.extra_data = {
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
        "userid": "test_user_id",
        "expires": 3600,
    }
    return mock


@pytest.fixture
def device_manager():
    """Create a test device manager"""
    return DeviceManager(Provider.WITHINGS)


class TestDeviceManager:
    """Test cases for DeviceManager"""

    def test_init(self):
        """Test DeviceManager initialization"""
        manager = DeviceManager(Provider.WITHINGS)
        assert manager.provider == Provider.WITHINGS
        assert manager.config.name == Provider.WITHINGS

    def test_init_invalid_provider(self):
        """Test DeviceManager with invalid provider"""
        with pytest.raises(KeyError):
            DeviceManager("invalid_provider")

    @patch("ingestors.device_manager.UserSocialAuth.objects.get")
    def test_get_user_credentials_success(self, mock_get, device_manager, mock_user_auth):
        """Test successful credential retrieval"""
        mock_get.return_value = mock_user_auth

        credentials = device_manager._get_user_credentials("test_user")

        assert credentials.access_token == "test_access_token"
        assert credentials.refresh_token == "test_refresh_token"
        assert credentials.user_id == "test_user_id"
        assert credentials.expires_in == 3600

    @patch("ingestors.device_manager.UserSocialAuth.objects.get")
    def test_get_user_credentials_not_found(self, mock_get, device_manager):
        """Test credential retrieval when user not found"""
        from social_django.models import UserSocialAuth

        mock_get.side_effect = UserSocialAuth.DoesNotExist()

        with pytest.raises(AuthenticationError, match="No withings credentials"):
            device_manager._get_user_credentials("nonexistent_user")

    @patch("ingestors.device_manager.UserSocialAuth.objects.get")
    def test_get_user_credentials_missing_token(self, mock_get, device_manager):
        """Test credential retrieval with missing access token"""
        mock_auth = Mock()
        mock_auth.extra_data = {"refresh_token": "test"}  # Missing access_token
        mock_get.return_value = mock_auth

        with pytest.raises(AuthenticationError, match="Missing credential field"):
            device_manager._get_user_credentials("test_user")

    @patch("ingestors.device_manager.WithingsApiAdapter")
    @patch.object(DeviceManager, "_get_user_credentials")
    def test_fetch_user_devices_success(self, mock_get_creds, mock_adapter, device_manager):
        """Test successful device fetching"""
        # Setup mocks
        mock_get_creds.return_value = OAuthCredentials("token")
        mock_client = Mock()
        mock_adapter.return_value = mock_client

        mock_devices = [
            MockWithingsDevice(123, "Scale", "Body+", "high"),
            MockWithingsDevice(456, "Blood Pressure Monitor", "BPM Core", "low"),
        ]
        mock_client.fetch_devices.return_value = mock_devices

        # Test
        devices = device_manager.fetch_user_devices("test_user")

        # Assertions
        assert len(devices) == 2
        assert devices[0].provider_device_id == "123"
        assert devices[0].device_type == DeviceType.SCALE
        assert devices[0].battery_level == 80  # "high" -> 80%

        assert devices[1].provider_device_id == "456"
        assert devices[1].device_type == DeviceType.BP_MONITOR
        assert devices[1].battery_level == 20  # "low" -> 20%

    @patch.object(DeviceManager, "_get_user_credentials")
    def test_fetch_user_devices_auth_error(self, mock_get_creds, device_manager):
        """Test device fetching with authentication error"""
        mock_get_creds.side_effect = AuthenticationError("Invalid token")

        with pytest.raises(AuthenticationError):
            device_manager.fetch_user_devices("test_user")

    def test_transform_withings_device(self, device_manager):
        """Test Withings device data transformation"""
        mock_device = MockWithingsDevice(deviceid=123, type="Scale", model="Body+", battery="medium")

        device_data = device_manager._transform_withings_device(mock_device)

        assert device_data.provider_device_id == "123"
        assert device_data.provider == Provider.WITHINGS
        assert device_data.device_type == DeviceType.SCALE
        assert device_data.manufacturer == "Withings"
        assert device_data.model == "Body+"
        assert device_data.battery_level == 50  # "medium" -> 50%
        assert device_data.raw_data["deviceid"] == 123
        assert device_data.raw_data["battery_text"] == "medium"

    def test_transform_fitbit_device(self, device_manager):
        """Test Fitbit device data transformation"""
        device_manager.provider = Provider.FITBIT
        device_manager.config = device_manager.config.__class__(
            name=Provider.FITBIT,
            client_id_setting="FITBIT_ID",
            client_secret_setting="FITBIT_SECRET",
            api_base_url="https://api.fitbit.com",
            device_endpoint="/devices",
            device_types_map={"TRACKER": DeviceType.ACTIVITY_TRACKER},
        )

        fitbit_data = {
            "id": "456",
            "type": "TRACKER",
            "deviceVersion": "Versa 3",
            "batteryLevel": "High",
            "lastSyncTime": "2023-01-01T10:00:00Z",
            "version": "1.2.3",
        }

        device_data = device_manager._transform_fitbit_device(fitbit_data)

        assert device_data.provider_device_id == "456"
        assert device_data.provider == Provider.FITBIT
        assert device_data.device_type == DeviceType.ACTIVITY_TRACKER
        assert device_data.manufacturer == "Fitbit"
        assert device_data.model == "Versa 3"
        assert device_data.battery_level == 80  # "High" -> 80%
        assert device_data.last_sync == "2023-01-01T10:00:00Z"
        assert device_data.firmware_version == "1.2.3"


class TestDeviceManagerFactory:
    """Test cases for DeviceManagerFactory"""

    def test_create_withings_manager(self):
        """Test creating Withings device manager"""
        manager = DeviceManagerFactory.create(Provider.WITHINGS)
        assert isinstance(manager, DeviceManager)
        assert manager.provider == Provider.WITHINGS

    def test_create_fitbit_manager(self):
        """Test creating Fitbit device manager"""
        manager = DeviceManagerFactory.create(Provider.FITBIT)
        assert isinstance(manager, DeviceManager)
        assert manager.provider == Provider.FITBIT

    def test_create_from_string(self):
        """Test creating manager from string provider name"""
        manager = DeviceManagerFactory.create("withings")
        assert manager.provider == Provider.WITHINGS

    def test_create_unsupported_provider(self):
        """Test creating manager for unsupported provider"""
        with pytest.raises(DeviceManagerError, match="Unsupported provider"):
            DeviceManagerFactory.create("unknown_provider")

    def test_get_supported_providers(self):
        """Test getting list of supported providers"""
        providers = DeviceManagerFactory.get_supported_providers()
        assert Provider.WITHINGS in providers
        assert Provider.FITBIT in providers
        assert len(providers) >= 2


class TestOAuthCredentials:
    """Test cases for OAuthCredentials dataclass"""

    def test_minimal_credentials(self):
        """Test creating credentials with minimal data"""
        creds = OAuthCredentials("access_token")
        assert creds.access_token == "access_token"
        assert creds.refresh_token is None
        assert creds.user_id is None
        assert creds.expires_in is None

    def test_full_credentials(self):
        """Test creating credentials with all data"""
        creds = OAuthCredentials(
            access_token="access_token", refresh_token="refresh_token", user_id="user123", expires_in=3600
        )
        assert creds.access_token == "access_token"
        assert creds.refresh_token == "refresh_token"
        assert creds.user_id == "user123"
        assert creds.expires_in == 3600


if __name__ == "__main__":
    pytest.main([__file__])
