"""
Unit tests for constants and enums
"""

import pytest

from ingestors.constants import PROVIDER_CONFIGS, BatteryLevel, DeviceData, DeviceType, Provider, ProviderConfig


class TestDeviceType:
    """Test DeviceType enum"""

    def test_device_type_values(self):
        """Test that all device types have expected values"""
        assert DeviceType.BP_MONITOR == "bp_monitor"
        assert DeviceType.SCALE == "scale"
        assert DeviceType.ACTIVITY_TRACKER == "activity_tracker"
        assert DeviceType.SMARTWATCH == "smartwatch"
        assert DeviceType.THERMOMETER == "thermometer"
        assert DeviceType.PULSE_OXIMETER == "pulse_oximeter"
        assert DeviceType.UNKNOWN == "unknown"

    def test_device_type_is_string_enum(self):
        """Test that DeviceType values are strings"""
        for device_type in DeviceType:
            assert isinstance(device_type.value, str)


class TestBatteryLevel:
    """Test BatteryLevel enum"""

    def test_battery_level_values(self):
        """Test battery level percentage values"""
        assert BatteryLevel.HIGH.value == 80
        assert BatteryLevel.MEDIUM.value == 50
        assert BatteryLevel.LOW.value == 20
        assert BatteryLevel.CRITICAL.value == 5
        assert BatteryLevel.EMPTY.value == 5

    def test_from_text_valid_inputs(self):
        """Test battery level conversion from text"""
        assert BatteryLevel.from_text("high") == 80
        assert BatteryLevel.from_text("HIGH") == 80
        assert BatteryLevel.from_text("medium") == 50
        assert BatteryLevel.from_text("low") == 20
        assert BatteryLevel.from_text("critical") == 5
        assert BatteryLevel.from_text("empty") == 5

    def test_from_text_invalid_inputs(self):
        """Test battery level conversion with invalid inputs"""
        assert BatteryLevel.from_text(None) is None
        assert BatteryLevel.from_text("") is None
        assert BatteryLevel.from_text("invalid") is None
        assert BatteryLevel.from_text("123") is None

    def test_from_text_case_insensitive(self):
        """Test that battery level conversion is case insensitive"""
        test_cases = ["High", "MEDIUM", "Low", "CRITICAL", "Empty"]
        expected = [80, 50, 20, 5, 5]

        for text, expected_value in zip(test_cases, expected, strict=False):
            assert BatteryLevel.from_text(text) == expected_value


class TestProvider:
    """Test Provider enum"""

    def test_provider_values(self):
        """Test provider string values"""
        assert Provider.WITHINGS == "withings"
        assert Provider.FITBIT == "fitbit"

    def test_provider_is_string_enum(self):
        """Test that Provider values are strings"""
        for provider in Provider:
            assert isinstance(provider.value, str)


class TestProviderConfig:
    """Test ProviderConfig dataclass"""

    def test_provider_config_creation(self):
        """Test creating a provider config"""
        config = ProviderConfig(
            name=Provider.WITHINGS,
            client_id_setting="TEST_CLIENT_ID",
            client_secret_setting="TEST_CLIENT_SECRET",
            api_base_url="https://api.test.com",
            device_endpoint="/devices",
            device_types_map={"Scale": DeviceType.SCALE},
        )

        assert config.name == Provider.WITHINGS
        assert config.client_id_setting == "TEST_CLIENT_ID"
        assert config.client_secret_setting == "TEST_CLIENT_SECRET"
        assert config.api_base_url == "https://api.test.com"
        assert config.device_endpoint == "/devices"
        assert config.device_types_map["Scale"] == DeviceType.SCALE

    def test_provider_config_frozen(self):
        """Test that ProviderConfig is immutable"""
        config = ProviderConfig(
            name=Provider.WITHINGS,
            client_id_setting="TEST_CLIENT_ID",
            client_secret_setting="TEST_CLIENT_SECRET",
            api_base_url="https://api.test.com",
            device_endpoint="/devices",
            device_types_map={},
        )

        with pytest.raises(Exception):  # Should be frozen
            config.name = Provider.FITBIT


class TestProviderConfigs:
    """Test PROVIDER_CONFIGS constant"""

    def test_all_providers_configured(self):
        """Test that all providers have configurations"""
        for provider in Provider:
            assert provider in PROVIDER_CONFIGS

    def test_withings_config(self):
        """Test Withings provider configuration"""
        config = PROVIDER_CONFIGS[Provider.WITHINGS]

        assert config.name == Provider.WITHINGS
        assert config.client_id_setting == "SOCIAL_AUTH_WITHINGS_KEY"
        assert config.client_secret_setting == "SOCIAL_AUTH_WITHINGS_SECRET"
        assert "withings" in config.api_base_url.lower()
        assert config.device_endpoint
        assert isinstance(config.device_types_map, dict)

    def test_fitbit_config(self):
        """Test Fitbit provider configuration"""
        config = PROVIDER_CONFIGS[Provider.FITBIT]

        assert config.name == Provider.FITBIT
        assert config.client_id_setting == "SOCIAL_AUTH_FITBIT_KEY"
        assert config.client_secret_setting == "SOCIAL_AUTH_FITBIT_SECRET"
        assert "fitbit" in config.api_base_url.lower()
        assert config.device_endpoint
        assert isinstance(config.device_types_map, dict)

    def test_device_type_mappings(self):
        """Test that device type mappings are valid"""
        for _provider, config in PROVIDER_CONFIGS.items():
            for provider_type, device_type in config.device_types_map.items():
                assert isinstance(provider_type, str)
                assert isinstance(device_type, DeviceType)


class TestDeviceData:
    """Test DeviceData dataclass"""

    def test_device_data_creation_minimal(self):
        """Test creating DeviceData with minimal required fields"""
        device = DeviceData(
            provider_device_id="test-123",
            provider=Provider.WITHINGS,
            device_type=DeviceType.SCALE,
            manufacturer="Test Corp",
            model="Test Model",
        )

        assert device.provider_device_id == "test-123"
        assert device.provider == Provider.WITHINGS
        assert device.device_type == DeviceType.SCALE
        assert device.manufacturer == "Test Corp"
        assert device.model == "Test Model"

        # Test defaults
        assert device.battery_level is None
        assert device.last_sync is None
        assert device.firmware_version is None
        assert device.serial_number is None
        assert device.status == "active"
        assert device.raw_data == {}

    def test_device_data_creation_full(self):
        """Test creating DeviceData with all fields"""
        raw_data = {"test": "data"}
        device = DeviceData(
            provider_device_id="test-456",
            provider=Provider.FITBIT,
            device_type=DeviceType.ACTIVITY_TRACKER,
            manufacturer="Fitbit",
            model="Versa 3",
            battery_level=85,
            last_sync="2023-01-01T10:00:00Z",
            firmware_version="1.2.3",
            serial_number="SN123456",
            status="inactive",
            raw_data=raw_data,
        )

        assert device.provider_device_id == "test-456"
        assert device.provider == Provider.FITBIT
        assert device.device_type == DeviceType.ACTIVITY_TRACKER
        assert device.manufacturer == "Fitbit"
        assert device.model == "Versa 3"
        assert device.battery_level == 85
        assert device.last_sync == "2023-01-01T10:00:00Z"
        assert device.firmware_version == "1.2.3"
        assert device.serial_number == "SN123456"
        assert device.status == "inactive"
        assert device.raw_data == raw_data

    def test_device_data_post_init(self):
        """Test DeviceData post_init behavior"""
        # Test with None raw_data
        device = DeviceData(
            provider_device_id="test-789",
            provider=Provider.WITHINGS,
            device_type=DeviceType.SCALE,
            manufacturer="Test",
            model="Test",
            raw_data=None,
        )

        assert device.raw_data == {}

    def test_device_data_immutability(self):
        """Test that DeviceData is mutable (slots=True but not frozen)"""
        device = DeviceData(
            provider_device_id="test-123",
            provider=Provider.WITHINGS,
            device_type=DeviceType.SCALE,
            manufacturer="Test",
            model="Test",
        )

        # Should be able to modify fields (not frozen)
        device.battery_level = 50
        assert device.battery_level == 50

    def test_device_data_slots(self):
        """Test that DeviceData uses slots for memory efficiency"""
        device = DeviceData(
            provider_device_id="test-123",
            provider=Provider.WITHINGS,
            device_type=DeviceType.SCALE,
            manufacturer="Test",
            model="Test",
        )

        # Should not be able to add arbitrary attributes due to slots
        with pytest.raises(AttributeError):
            device.unknown_attribute = "value"

    def test_device_data_type_hints(self):
        """Test that DeviceData accepts correct types"""
        # This test mainly verifies the type annotations work correctly
        device = DeviceData(
            provider_device_id="test-123",
            provider=Provider.WITHINGS,
            device_type=DeviceType.SCALE,
            manufacturer="Test",
            model="Test",
            battery_level=85,  # int
            last_sync="2023-01-01T10:00:00Z",  # str
            firmware_version="1.0.0",  # str
            serial_number="SN123",  # str
            status="active",  # str
            raw_data={"key": "value"},  # dict
        )

        assert isinstance(device.battery_level, int)
        assert isinstance(device.last_sync, str)
        assert isinstance(device.firmware_version, str)
        assert isinstance(device.serial_number, str)
        assert isinstance(device.status, str)
        assert isinstance(device.raw_data, dict)


if __name__ == "__main__":
    pytest.main([__file__])
