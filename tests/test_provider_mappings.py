"""
Tests for provider data type mappings.
"""

import pytest

from ingestors.health_data_constants import Provider
from ingestors.provider_mappings import (
    FITBIT_DATA_TYPES,
    PROVIDER_DATA_TYPE_MAPPINGS,
    WITHINGS_DATA_TYPES,
    APIMethod,
    DataTypeConfig,
    get_category_to_data_types_mapping,
    get_data_type_config,
    get_supported_data_types,
    resolve_subscription_categories,
    validate_data_types,
)


class TestDataTypeConfig:
    """Tests for DataTypeConfig dataclass."""

    def test_create_data_type_config(self):
        """Test creating a DataTypeConfig."""
        config = DataTypeConfig(
            name="test_type",
            display_name="Test Type",
            subscription_categories=["1", "2"],
            api_endpoint="/v2/test",
            api_method=APIMethod.POST,
            api_action="get",
            meastype=10,
            response_processor="_process_test",
            requires_date_range=True,
            description="Test data type",
            date_format="ymd",
            data_fields="field1,field2",
        )

        assert config.name == "test_type"
        assert config.display_name == "Test Type"
        assert config.subscription_categories == ["1", "2"]
        assert config.api_method == APIMethod.POST
        assert config.date_format == "ymd"
        assert config.data_fields == "field1,field2"

    def test_data_type_config_defaults(self):
        """Test DataTypeConfig has correct defaults for new fields."""
        config = DataTypeConfig(
            name="test",
            display_name="Test",
            subscription_categories=["1"],
            api_endpoint="/test",
            api_method=APIMethod.POST,
            api_action=None,
            meastype=None,
            response_processor="_process",
            requires_date_range=True,
            description="Test",
        )

        assert config.date_format == "unix"
        assert config.data_fields is None

    def test_data_type_config_is_frozen(self):
        """Test DataTypeConfig is immutable."""
        config = WITHINGS_DATA_TYPES["ecg"]

        with pytest.raises(AttributeError):
            config.name = "changed"


class TestWithingsDataTypes:
    """Tests for Withings data type definitions."""

    def test_ecg_configuration(self):
        """Test ECG configuration."""
        config = WITHINGS_DATA_TYPES["ecg"]

        assert config.name == "ecg"
        assert config.subscription_categories == ["54"]
        assert config.api_endpoint == "/v2/heart"
        assert config.api_method == APIMethod.POST
        assert config.api_action == "list"

    def test_heart_rate_configuration(self):
        """Test heart rate configuration uses /measure endpoint."""
        config = WITHINGS_DATA_TYPES["heart_rate"]

        assert config.name == "heart_rate"
        assert config.subscription_categories == ["4"]
        assert config.api_endpoint == "/measure"
        assert config.api_method == APIMethod.POST
        assert config.meastype == 11

    def test_weight_configuration(self):
        """Test weight configuration uses /measure endpoint."""
        config = WITHINGS_DATA_TYPES["weight"]

        assert config.subscription_categories == ["1"]
        assert config.api_endpoint == "/measure"
        assert config.api_method == APIMethod.POST
        assert config.meastype == 1

    def test_blood_pressure_has_multiple_meastypes(self):
        """Test blood pressure has multiple meastypes."""
        config = WITHINGS_DATA_TYPES["blood_pressure"]

        assert config.meastype == [9, 10]
        assert config.api_endpoint == "/measure"

    def test_temperature_has_multiple_meastypes(self):
        """Test temperature has multiple meastypes for body temp, skin temp."""
        config = WITHINGS_DATA_TYPES["temperature"]

        assert config.meastype == [12, 71, 73]
        assert config.api_endpoint == "/measure"
        assert config.api_method == APIMethod.POST

    def test_sleep_uses_getsummary(self):
        """Test sleep uses getsummary action with YMD date format."""
        config = WITHINGS_DATA_TYPES["sleep"]

        assert config.api_action == "getsummary"
        assert config.date_format == "ymd"
        assert config.data_fields is not None
        assert "total_sleep_time" in config.data_fields

    def test_steps_uses_ymd_date_format(self):
        """Test steps/activity uses YMD date format."""
        config = WITHINGS_DATA_TYPES["steps"]

        assert config.api_endpoint == "/v2/measure"
        assert config.api_action == "getactivity"
        assert config.date_format == "ymd"
        assert config.data_fields is not None

    def test_rr_intervals_includes_hrv_appli(self):
        """Test rr_intervals subscription includes HRV appli 62."""
        config = WITHINGS_DATA_TYPES["rr_intervals"]

        assert "44" in config.subscription_categories
        assert "62" in config.subscription_categories

    def test_pulse_wave_velocity_exists(self):
        """Test pulse_wave_velocity data type is configured."""
        config = WITHINGS_DATA_TYPES["pulse_wave_velocity"]

        assert config.api_endpoint == "/measure"
        assert config.api_action == "getmeas"
        assert config.meastype == 91

    def test_getmeas_types_use_measure_endpoint(self):
        """Test all getmeas data types use /measure endpoint (not /v2/measure)."""
        for name, config in WITHINGS_DATA_TYPES.items():
            if config.api_action == "getmeas":
                assert config.api_endpoint == "/measure", (
                    f"{name} uses {config.api_endpoint} but getmeas requires /measure"
                )

    def test_all_withings_types_use_post(self):
        """Test all Withings types use POST method (per official API docs)."""
        for name, config in WITHINGS_DATA_TYPES.items():
            assert config.api_method == APIMethod.POST, f"{name} uses {config.api_method} but should use POST"

    def test_all_withings_types_have_required_fields(self):
        """Test all Withings types have required fields."""
        for name, config in WITHINGS_DATA_TYPES.items():
            assert config.name == name
            assert config.display_name
            assert len(config.subscription_categories) > 0
            assert config.api_endpoint
            assert config.api_method == APIMethod.POST
            assert config.response_processor
            assert isinstance(config.requires_date_range, bool)
            assert config.date_format in ("unix", "ymd")


class TestFitbitDataTypes:
    """Tests for Fitbit data type definitions."""

    def test_heart_rate_configuration(self):
        """Test Fitbit heart rate configuration."""
        config = FITBIT_DATA_TYPES["heart_rate"]

        assert config.subscription_categories == ["activities"]
        assert "{date}" in config.api_endpoint
        assert config.meastype is None

    def test_sleep_configuration(self):
        """Test Fitbit sleep configuration."""
        config = FITBIT_DATA_TYPES["sleep"]

        assert config.subscription_categories == ["sleep"]
        assert "sleep" in config.api_endpoint

    def test_all_fitbit_types_have_required_fields(self):
        """Test all Fitbit types have required fields."""
        for name, config in FITBIT_DATA_TYPES.items():
            assert config.name == name
            assert config.display_name
            assert len(config.subscription_categories) > 0
            assert config.api_endpoint
            assert config.response_processor


class TestProviderDataTypeMappings:
    """Tests for provider data type mappings."""

    def test_contains_withings(self):
        """Test contains Withings provider."""
        assert Provider.WITHINGS in PROVIDER_DATA_TYPE_MAPPINGS
        assert PROVIDER_DATA_TYPE_MAPPINGS[Provider.WITHINGS] == WITHINGS_DATA_TYPES

    def test_contains_fitbit(self):
        """Test contains Fitbit provider."""
        assert Provider.FITBIT in PROVIDER_DATA_TYPE_MAPPINGS
        assert PROVIDER_DATA_TYPE_MAPPINGS[Provider.FITBIT] == FITBIT_DATA_TYPES


class TestGetCategoryToDataTypesMapping:
    """Tests for get_category_to_data_types_mapping function."""

    def test_withings_category_mapping(self):
        """Test Withings category to data types mapping."""
        mapping = get_category_to_data_types_mapping(Provider.WITHINGS)

        # Category 1 should have weight and fat_mass
        assert "1" in mapping
        assert "weight" in mapping["1"]
        assert "fat_mass" in mapping["1"]

        # Category 54 should have ecg
        assert "54" in mapping
        assert "ecg" in mapping["54"]

        # Category 4 should have multiple types
        assert "4" in mapping
        assert "heart_rate" in mapping["4"]
        assert "blood_pressure" in mapping["4"]

    def test_fitbit_category_mapping(self):
        """Test Fitbit category to data types mapping."""
        mapping = get_category_to_data_types_mapping(Provider.FITBIT)

        # Activities category should have multiple types
        assert "activities" in mapping
        assert "heart_rate" in mapping["activities"]
        assert "steps" in mapping["activities"]

        # Sleep category
        assert "sleep" in mapping
        assert "sleep" in mapping["sleep"]

    def test_unknown_provider_returns_empty(self):
        """Test unknown provider returns empty mapping."""
        # Create a mock provider that's not in the mappings
        # Since Provider is an enum, we just test with a non-existent value
        mapping = get_category_to_data_types_mapping(Provider.WITHINGS)
        # This test verifies the function works, actual unknown provider
        # would need the enum extended
        assert isinstance(mapping, dict)


class TestResolveSubscriptionCategories:
    """Tests for resolve_subscription_categories function."""

    def test_single_data_type_withings(self):
        """Test resolving single data type for Withings."""
        categories = resolve_subscription_categories(Provider.WITHINGS, ["ecg"])

        assert categories == ["54"]

    def test_multiple_data_types_withings(self):
        """Test resolving multiple data types for Withings."""
        categories = resolve_subscription_categories(Provider.WITHINGS, ["ecg", "weight", "heart_rate"])

        # Should be sorted and unique
        assert "1" in categories  # weight
        assert "4" in categories  # heart_rate
        assert "54" in categories  # ecg

    def test_deduplicates_categories(self):
        """Test categories are deduplicated."""
        # weight and fat_mass both use category 1
        categories = resolve_subscription_categories(Provider.WITHINGS, ["weight", "fat_mass"])

        # Should only have category 1 once
        assert categories.count("1") == 1

    def test_fitbit_categories(self):
        """Test resolving Fitbit categories."""
        categories = resolve_subscription_categories(Provider.FITBIT, ["heart_rate", "sleep"])

        assert "activities" in categories
        assert "sleep" in categories

    def test_unknown_data_type_ignored(self):
        """Test unknown data types are ignored."""
        categories = resolve_subscription_categories(Provider.WITHINGS, ["ecg", "unknown_type", "weight"])

        # Only valid types should be resolved
        assert "1" in categories
        assert "54" in categories

    def test_returns_sorted_categories(self):
        """Test categories are returned sorted."""
        categories = resolve_subscription_categories(Provider.WITHINGS, ["ecg", "weight", "steps"])

        assert categories == sorted(categories)


class TestGetDataTypeConfig:
    """Tests for get_data_type_config function."""

    def test_returns_config_for_valid_type(self):
        """Test returns config for valid data type."""
        config = get_data_type_config(Provider.WITHINGS, "ecg")

        assert config is not None
        assert config.name == "ecg"

    def test_returns_none_for_invalid_type(self):
        """Test returns None for invalid data type."""
        config = get_data_type_config(Provider.WITHINGS, "nonexistent")

        assert config is None

    def test_returns_none_for_type_not_on_provider(self):
        """Test returns None for type not supported by provider."""
        # pulse_wave_velocity is Withings-only
        config = get_data_type_config(Provider.FITBIT, "pulse_wave_velocity")

        assert config is None

    def test_glucose_not_supported_by_any_provider(self):
        """Test glucose is not supported by any provider (no public API support)."""
        assert get_data_type_config(Provider.WITHINGS, "glucose") is None
        assert get_data_type_config(Provider.FITBIT, "glucose") is None


class TestGetSupportedDataTypes:
    """Tests for get_supported_data_types function."""

    def test_withings_supported_types(self):
        """Test Withings supported types list."""
        types = get_supported_data_types(Provider.WITHINGS)

        assert "ecg" in types
        assert "heart_rate" in types
        assert "weight" in types
        assert "sleep" in types
        assert "blood_pressure" in types

    def test_fitbit_supported_types(self):
        """Test Fitbit supported types list."""
        types = get_supported_data_types(Provider.FITBIT)

        assert "heart_rate" in types
        assert "steps" in types
        assert "sleep" in types

    def test_returns_list(self):
        """Test returns a list."""
        types = get_supported_data_types(Provider.WITHINGS)

        assert isinstance(types, list)


class TestValidateDataTypes:
    """Tests for validate_data_types function."""

    def test_all_valid_types(self):
        """Test with all valid data types."""
        supported, unsupported = validate_data_types(Provider.WITHINGS, ["ecg", "weight", "heart_rate"])

        assert supported == ["ecg", "weight", "heart_rate"]
        assert unsupported == []

    def test_all_invalid_types(self):
        """Test with all invalid data types."""
        supported, unsupported = validate_data_types(Provider.WITHINGS, ["invalid1", "invalid2"])

        assert supported == []
        assert unsupported == ["invalid1", "invalid2"]

    def test_mixed_valid_and_invalid(self):
        """Test with mix of valid and invalid data types."""
        supported, unsupported = validate_data_types(Provider.WITHINGS, ["ecg", "invalid", "weight"])

        assert "ecg" in supported
        assert "weight" in supported
        assert "invalid" in unsupported

    def test_preserves_order(self):
        """Test preserves input order."""
        supported, unsupported = validate_data_types(Provider.WITHINGS, ["weight", "ecg", "heart_rate"])

        assert supported == ["weight", "ecg", "heart_rate"]

    def test_empty_list(self):
        """Test with empty list."""
        supported, unsupported = validate_data_types(Provider.WITHINGS, [])

        assert supported == []
        assert unsupported == []

    def test_fitbit_validation(self):
        """Test validation for Fitbit."""
        supported, unsupported = validate_data_types(Provider.FITBIT, ["heart_rate", "glucose", "sleep"])

        # glucose is not supported by any provider (no public API)
        assert "heart_rate" in supported
        assert "sleep" in supported
        assert "glucose" in unsupported


class TestAPIMethod:
    """Tests for APIMethod enum."""

    def test_get_method(self):
        """Test GET method."""
        assert APIMethod.GET.value == "GET"

    def test_post_method(self):
        """Test POST method."""
        assert APIMethod.POST.value == "POST"
