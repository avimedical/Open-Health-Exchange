"""
Tests for base FHIR transformer.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from ingestors.constants import Provider
from transformers.base_fhir_transformer import BaseFHIRTransformer


class ConcreteFHIRTransformer(BaseFHIRTransformer):
    """Concrete implementation of BaseFHIRTransformer for testing."""

    def transform(self, *args, **kwargs):
        """Implement abstract method."""
        return {"resourceType": "Test"}


class TestCreateFhirCoding:
    """Tests for create_fhir_coding method."""

    @pytest.fixture
    def transformer(self):
        """Create transformer instance."""
        return ConcreteFHIRTransformer()

    def test_creates_coding_structure(self, transformer):
        """Test creates proper coding structure."""
        result = transformer.create_fhir_coding(
            system="http://snomed.info/sct",
            code="27113001",
            display="Body weight",
        )

        assert result["coding"][0]["system"] == "http://snomed.info/sct"
        assert result["coding"][0]["code"] == "27113001"
        assert result["coding"][0]["display"] == "Body weight"
        assert result["text"] == "Body weight"

    def test_creates_single_coding_in_list(self, transformer):
        """Test creates exactly one coding in list."""
        result = transformer.create_fhir_coding("http://loinc.org", "29463-7", "Weight")

        assert len(result["coding"]) == 1


class TestSafeConvertValue:
    """Tests for safe_convert_value method."""

    @pytest.fixture
    def transformer(self):
        """Create transformer instance."""
        return ConcreteFHIRTransformer()

    def test_converts_int_to_float(self, transformer):
        """Test converts integer to float."""
        result = transformer.safe_convert_value(42, float)

        assert result == 42.0
        assert isinstance(result, float)

    def test_converts_float_to_float(self, transformer):
        """Test passes through float."""
        result = transformer.safe_convert_value(3.14, float)

        assert result == 3.14

    def test_converts_string_to_float(self, transformer):
        """Test converts string to float."""
        result = transformer.safe_convert_value("72.5", float)

        assert result == 72.5

    def test_converts_string_to_int(self, transformer):
        """Test converts string to int."""
        result = transformer.safe_convert_value("42", int)

        assert result == 42
        assert isinstance(result, int)

    def test_invalid_string_to_float_returns_zero(self, transformer):
        """Test invalid string returns 0.0 for float."""
        result = transformer.safe_convert_value("invalid", float)

        assert result == 0.0

    def test_invalid_string_to_int_returns_zero(self, transformer):
        """Test invalid string returns 0 for int."""
        result = transformer.safe_convert_value("invalid", int)

        assert result == 0

    def test_invalid_string_to_str_returns_empty(self, transformer):
        """Test string conversion of non-numeric string."""
        result = transformer.safe_convert_value("hello", str)

        assert result == "hello"

    def test_dict_to_float_returns_zero(self, transformer):
        """Test dict returns 0.0 for float."""
        result = transformer.safe_convert_value({"key": "value"}, float)

        assert result == 0.0

    def test_dict_to_int_returns_zero(self, transformer):
        """Test dict returns 0 for int."""
        result = transformer.safe_convert_value({"key": "value"}, int)

        assert result == 0

    def test_dict_to_str_returns_empty(self, transformer):
        """Test dict returns empty string for str."""
        result = transformer.safe_convert_value({"key": "value"}, str)

        assert result == ""


class TestGetLoincCode:
    """Tests for get_loinc_code method."""

    @pytest.fixture
    def transformer(self):
        """Create transformer instance."""
        return ConcreteFHIRTransformer()

    def test_returns_override_when_present(self, transformer):
        """Test returns override LOINC code when configured."""
        with patch.object(transformer, "get_compatibility_config") as mock_config:
            mock_config.return_value = {"LOINC_OVERRIDES": {"steps": "55423-8"}}

            result = transformer.get_loinc_code("steps", {"steps": "default-code"})

            assert result == "55423-8"

    def test_returns_default_when_no_override(self, transformer):
        """Test returns default LOINC code when no override."""
        with patch.object(transformer, "get_compatibility_config") as mock_config:
            mock_config.return_value = {"LOINC_OVERRIDES": {}}

            result = transformer.get_loinc_code("steps", {"steps": "default-steps"})

            assert result == "default-steps"

    def test_returns_none_when_not_found(self, transformer):
        """Test returns None when data type not found."""
        with patch.object(transformer, "get_compatibility_config") as mock_config:
            mock_config.return_value = {"LOINC_OVERRIDES": {}}

            result = transformer.get_loinc_code("unknown_type", {"steps": "steps-code"})

            assert result is None

    def test_returns_none_with_no_defaults(self, transformer):
        """Test returns None when no defaults provided."""
        with patch.object(transformer, "get_compatibility_config") as mock_config:
            mock_config.return_value = {}

            result = transformer.get_loinc_code("steps", None)

            assert result is None


class TestCreateBaseObservation:
    """Tests for create_base_observation method."""

    @pytest.fixture
    def transformer(self):
        """Create transformer instance."""
        return ConcreteFHIRTransformer()

    def test_creates_basic_observation(self, transformer):
        """Test creates basic observation structure."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

        with (
            patch.object(transformer, "get_observation_status", return_value="final"),
            patch.object(transformer, "should_include_issued_field", return_value=False),
            patch.object(transformer, "should_use_device_extensions", return_value=False),
        ):
            result = transformer.create_base_observation(
                patient_reference="Patient/123",
                timestamp=timestamp,
                provider=Provider.WITHINGS,
            )

        assert result["resourceType"] == "Observation"
        assert result["status"] == "final"
        assert result["subject"]["reference"] == "Patient/123"
        assert "effectiveDateTime" in result
        assert "meta" in result

    def test_includes_issued_field_when_enabled(self, transformer):
        """Test includes issued field when enabled."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

        with (
            patch.object(transformer, "get_observation_status", return_value="registered"),
            patch.object(transformer, "should_include_issued_field", return_value=True),
            patch.object(transformer, "should_use_device_extensions", return_value=False),
        ):
            result = transformer.create_base_observation(
                patient_reference="Patient/123",
                timestamp=timestamp,
                provider=Provider.WITHINGS,
            )

        assert "issued" in result

    def test_includes_device_extensions_when_legacy_mode(self, transformer):
        """Test includes device extensions in legacy mode."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

        with (
            patch.object(transformer, "get_observation_status", return_value="registered"),
            patch.object(transformer, "should_include_issued_field", return_value=False),
            patch.object(transformer, "should_use_device_extensions", return_value=True),
            patch.object(transformer, "create_device_extensions", return_value=[{"url": "test"}]),
        ):
            result = transformer.create_base_observation(
                patient_reference="Patient/123",
                timestamp=timestamp,
                provider=Provider.WITHINGS,
                device_id="device-1",
            )

        assert "extension" in result
        assert len(result["extension"]) == 1

    def test_includes_device_reference_when_modern_mode(self, transformer):
        """Test includes device reference in modern mode."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

        with (
            patch.object(transformer, "get_observation_status", return_value="final"),
            patch.object(transformer, "should_include_issued_field", return_value=False),
            patch.object(transformer, "should_use_device_extensions", return_value=False),
        ):
            result = transformer.create_base_observation(
                patient_reference="Patient/123",
                timestamp=timestamp,
                provider=Provider.WITHINGS,
                device_reference="Device/456",
            )

        assert result["device"]["reference"] == "Device/456"

    def test_no_device_info_when_not_provided(self, transformer):
        """Test no device info when not provided."""
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

        with (
            patch.object(transformer, "get_observation_status", return_value="final"),
            patch.object(transformer, "should_include_issued_field", return_value=False),
            patch.object(transformer, "should_use_device_extensions", return_value=False),
        ):
            result = transformer.create_base_observation(
                patient_reference="Patient/123",
                timestamp=timestamp,
                provider=Provider.WITHINGS,
            )

        assert "device" not in result
        assert "extension" not in result


class TestCreateDeviceExtensions:
    """Tests for create_device_extensions method."""

    @pytest.fixture
    def transformer(self):
        """Create transformer instance."""
        return ConcreteFHIRTransformer()

    def test_returns_empty_when_not_extension_mode(self, transformer):
        """Test returns empty list when not in extension mode."""
        with patch.object(transformer, "get_compatibility_config", return_value={}):
            result = transformer.create_device_extensions("withings", "device-1", "model-1")

        assert result == []

    def test_creates_obtained_from_extension(self, transformer):
        """Test creates obtained-from extension in extension mode."""
        with patch.object(transformer, "get_compatibility_config", return_value={"DEVICE_INFO_MODE": "extension"}):
            result = transformer.create_device_extensions("withings")

        assert len(result) == 1
        assert result[0]["url"] == "obtained-from"
        assert result[0]["valueString"] == "withings"

    def test_creates_device_id_extension(self, transformer):
        """Test creates device-id extension when provided."""
        with patch.object(transformer, "get_compatibility_config", return_value={"DEVICE_INFO_MODE": "extension"}):
            result = transformer.create_device_extensions("withings", "device-123")

        assert any(ext["url"] == "external-device-id" and ext["valueString"] == "device-123" for ext in result)

    def test_creates_device_model_extension_when_enabled(self, transformer):
        """Test creates device-model extension when enabled."""
        config = {
            "DEVICE_INFO_MODE": "extension",
            "INCLUDE_DEVICE_MODEL_EXTENSION": True,
        }
        with patch.object(transformer, "get_compatibility_config", return_value=config):
            result = transformer.create_device_extensions("withings", "device-123", "BPM Connect")

        assert any(ext["url"] == "device-model" and ext["valueString"] == "BPM Connect" for ext in result)


class TestGetObservationStatus:
    """Tests for get_observation_status method."""

    @pytest.fixture
    def transformer(self):
        """Create transformer instance."""
        return ConcreteFHIRTransformer()

    def test_returns_configured_status(self, transformer):
        """Test returns configured status."""
        with patch.object(transformer, "get_compatibility_config", return_value={"OBSERVATION_STATUS": "final"}):
            result = transformer.get_observation_status()

        assert result == "final"

    def test_returns_default_status(self, transformer):
        """Test returns default registered status."""
        with patch.object(transformer, "get_compatibility_config", return_value={}):
            result = transformer.get_observation_status()

        assert result == "registered"


class TestShouldIncludeIssuedField:
    """Tests for should_include_issued_field method."""

    @pytest.fixture
    def transformer(self):
        """Create transformer instance."""
        return ConcreteFHIRTransformer()

    def test_returns_configured_value(self, transformer):
        """Test returns configured value."""
        with patch.object(transformer, "get_compatibility_config", return_value={"INCLUDE_ISSUED_FIELD": False}):
            result = transformer.should_include_issued_field()

        assert result is False

    def test_returns_default_true(self, transformer):
        """Test returns default True."""
        with patch.object(transformer, "get_compatibility_config", return_value={}):
            result = transformer.should_include_issued_field()

        assert result is True


class TestShouldUseDeviceExtensions:
    """Tests for should_use_device_extensions method."""

    @pytest.fixture
    def transformer(self):
        """Create transformer instance."""
        return ConcreteFHIRTransformer()

    def test_returns_true_in_extension_mode(self, transformer):
        """Test returns True in extension mode."""
        with patch.object(transformer, "get_compatibility_config", return_value={"DEVICE_INFO_MODE": "extension"}):
            result = transformer.should_use_device_extensions()

        assert result is True

    def test_returns_false_in_reference_mode(self, transformer):
        """Test returns False in reference mode."""
        with patch.object(transformer, "get_compatibility_config", return_value={"DEVICE_INFO_MODE": "reference"}):
            result = transformer.should_use_device_extensions()

        assert result is False


class TestFhirSystems:
    """Tests for FHIR_SYSTEMS constants."""

    @pytest.fixture
    def transformer(self):
        """Create transformer instance."""
        return ConcreteFHIRTransformer()

    def test_contains_snomed_system(self, transformer):
        """Test contains SNOMED system URL."""
        assert transformer.FHIR_SYSTEMS["SNOMED"] == "http://snomed.info/sct"

    def test_contains_loinc_system(self, transformer):
        """Test contains LOINC system URL."""
        assert transformer.FHIR_SYSTEMS["LOINC"] == "http://loinc.org"

    def test_contains_ucum_system(self, transformer):
        """Test contains UCUM system URL."""
        assert transformer.FHIR_SYSTEMS["UCUM"] == "http://unitsofmeasure.org"
