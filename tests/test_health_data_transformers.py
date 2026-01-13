"""
Tests for health data FHIR transformers.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from ingestors.health_data_constants import HealthDataRecord, HealthDataType, Provider
from transformers.health_data_transformers import (
    HealthDataBundle,
    HealthDataTransformer,
    _create_fhir_timestamp,
    create_health_data_bundle,
    transform_health_record,
    transform_multiple_health_records,
)


class TestCreateFhirTimestamp:
    """Tests for _create_fhir_timestamp helper function."""

    def test_creates_utc_timestamp_with_z_suffix(self):
        """Test timestamp is in UTC with Z suffix."""
        timestamp = _create_fhir_timestamp()

        assert timestamp.endswith("Z")
        assert "T" in timestamp

    def test_creates_timestamp_from_datetime(self):
        """Test timestamp from provided datetime."""
        dt = datetime(2024, 1, 15, 10, 30, 45, 123456, tzinfo=UTC)
        timestamp = _create_fhir_timestamp(dt)

        assert timestamp == "2024-01-15T10:30:45.123Z"


class TestHealthDataTransformer:
    """Tests for HealthDataTransformer class."""

    @pytest.fixture
    def transformer(self):
        """Create a HealthDataTransformer instance."""
        return HealthDataTransformer()

    @pytest.fixture
    def sample_heart_rate_record(self):
        """Create a sample heart rate record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.HEART_RATE,
            value=72.0,
            unit="bpm",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            device_id="device-123",
        )

    @pytest.fixture
    def sample_steps_record(self):
        """Create a sample steps record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.FITBIT,
            data_type=HealthDataType.STEPS,
            value=10000,
            unit="steps",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    @pytest.fixture
    def sample_weight_record(self):
        """Create a sample weight record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.WEIGHT,
            value=75.5,
            unit="kg",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    @pytest.fixture
    def sample_blood_pressure_record(self):
        """Create a sample blood pressure record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.BLOOD_PRESSURE,
            value={"systolic": 120, "diastolic": 80},
            unit="mmHg",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    @pytest.fixture
    def sample_temperature_record(self):
        """Create a sample temperature record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.TEMPERATURE,
            value=36.8,
            unit="°C",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    @pytest.fixture
    def sample_spo2_record(self):
        """Create a sample SpO2 record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.SPO2,
            value=98.0,
            unit="%",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    @pytest.fixture
    def sample_rr_intervals_record(self):
        """Create a sample RR intervals record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.RR_INTERVALS,
            value={"intervals": [800, 850, 820]},
            unit="ms",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    @pytest.fixture
    def sample_sleep_record(self):
        """Create a sample sleep record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.SLEEP,
            value={"total_sleep_time": 420, "sleep_efficiency": 85},
            unit="minutes",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    @pytest.fixture
    def sample_fat_mass_record(self):
        """Create a sample fat mass record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.FAT_MASS,
            value={"fat_mass": 15.5, "fat_percentage": 20.5, "muscle_mass": 35.0},
            unit="kg",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    def test_transform_initializes_ecg_transformer(self, transformer):
        """Test transformer initializes ECG transformer."""
        assert transformer.ecg_transformer is not None

    def test_transform_heart_rate(self, transformer, sample_heart_rate_record):
        """Test transforming heart rate record."""
        result = transformer.transform(sample_heart_rate_record, "Patient/test-user")

        assert result["resourceType"] == "Observation"
        assert result["status"] in ["final", "registered"]
        assert result["code"]["coding"][0]["code"] == "8867-4"  # Heart rate LOINC
        assert result["valueQuantity"]["value"] == 72.0
        assert result["valueQuantity"]["unit"] == "bpm"
        assert result["subject"]["reference"] == "Patient/test-user"

    def test_transform_steps(self, transformer, sample_steps_record):
        """Test transforming steps record."""
        result = transformer.transform(sample_steps_record, "Patient/test-user")

        assert result["resourceType"] == "Observation"
        assert result["valueQuantity"]["value"] == 10000
        assert result["valueQuantity"]["unit"] == "steps"
        assert result["valueQuantity"]["code"] == "[count]"

    def test_transform_weight(self, transformer, sample_weight_record):
        """Test transforming weight record."""
        result = transformer.transform(sample_weight_record, "Patient/test-user")

        assert result["resourceType"] == "Observation"
        assert result["valueQuantity"]["value"] == 75.5
        assert result["valueQuantity"]["unit"] == "kg"

    def test_transform_blood_pressure(self, transformer, sample_blood_pressure_record):
        """Test transforming blood pressure record with components."""
        result = transformer.transform(sample_blood_pressure_record, "Patient/test-user")

        assert result["resourceType"] == "Observation"
        assert "component" in result
        assert len(result["component"]) == 2

        # Check systolic component
        systolic = result["component"][0]
        assert systolic["code"]["coding"][0]["code"] == "8480-6"
        assert systolic["valueQuantity"]["value"] == 120

        # Check diastolic component
        diastolic = result["component"][1]
        assert diastolic["code"]["coding"][0]["code"] == "8462-4"
        assert diastolic["valueQuantity"]["value"] == 80

    def test_transform_blood_pressure_invalid_value(self, transformer):
        """Test blood pressure transform raises error for invalid value."""
        record = HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.BLOOD_PRESSURE,
            value="invalid",
            unit="mmHg",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

        with pytest.raises(ValueError, match="must be a dictionary"):
            transformer.transform(record, "Patient/test-user")

    def test_transform_blood_pressure_missing_values(self, transformer):
        """Test blood pressure transform raises error when missing systolic/diastolic."""
        record = HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.BLOOD_PRESSURE,
            value={"systolic": 120},  # Missing diastolic
            unit="mmHg",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

        with pytest.raises(ValueError, match="must include both"):
            transformer.transform(record, "Patient/test-user")

    def test_transform_temperature(self, transformer, sample_temperature_record):
        """Test transforming temperature record."""
        result = transformer.transform(sample_temperature_record, "Patient/test-user")

        assert result["resourceType"] == "Observation"
        assert result["valueQuantity"]["value"] == 36.8
        assert result["valueQuantity"]["unit"] == "°C"

    def test_transform_spo2(self, transformer, sample_spo2_record):
        """Test transforming SpO2 record."""
        result = transformer.transform(sample_spo2_record, "Patient/test-user")

        assert result["resourceType"] == "Observation"
        assert result["valueQuantity"]["value"] == 98.0
        assert result["valueQuantity"]["unit"] == "%"

    def test_transform_rr_intervals_with_array(self, transformer, sample_rr_intervals_record):
        """Test transforming RR intervals with array of values."""
        result = transformer.transform(sample_rr_intervals_record, "Patient/test-user")

        assert result["resourceType"] == "Observation"
        assert "component" in result
        assert "RR intervals" in result["component"][0]["valueString"]

    def test_transform_rr_intervals_single_value(self, transformer):
        """Test transforming single RR interval value."""
        record = HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.RR_INTERVALS,
            value=850,
            unit="ms",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

        result = transformer.transform(record, "Patient/test-user")

        assert result["valueQuantity"]["value"] == 850.0
        assert result["valueQuantity"]["unit"] == "ms"

    def test_transform_sleep_with_components(self, transformer, sample_sleep_record):
        """Test transforming sleep record with multiple metrics."""
        result = transformer.transform(sample_sleep_record, "Patient/test-user")

        assert result["resourceType"] == "Observation"
        assert "component" in result
        assert len(result["component"]) == 2

    def test_transform_sleep_simple_value(self, transformer):
        """Test transforming simple sleep duration value."""
        record = HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.SLEEP,
            value=420,
            unit="minutes",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

        result = transformer.transform(record, "Patient/test-user")

        assert result["valueQuantity"]["value"] == 420.0

    def test_transform_fat_mass_with_components(self, transformer, sample_fat_mass_record):
        """Test transforming fat mass record with body composition components."""
        result = transformer.transform(sample_fat_mass_record, "Patient/test-user")

        assert result["resourceType"] == "Observation"
        assert "component" in result
        assert len(result["component"]) == 3  # fat_mass, fat_percentage, muscle_mass

    def test_transform_fat_mass_simple_value(self, transformer):
        """Test transforming simple fat mass value."""
        record = HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.FAT_MASS,
            value=15.5,
            unit="kg",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

        result = transformer.transform(record, "Patient/test-user")

        assert result["valueQuantity"]["value"] == 15.5

    def test_transform_pulse_wave_velocity(self, transformer):
        """Test transforming pulse wave velocity record."""
        record = HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.PULSE_WAVE_VELOCITY,
            value=8.5,
            unit="m/s",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

        result = transformer.transform(record, "Patient/test-user")

        assert result["valueQuantity"]["value"] == 8.5
        assert result["valueQuantity"]["unit"] == "m/s"

    def test_transform_with_device_reference(self, transformer, sample_heart_rate_record):
        """Test transform includes device reference when provided."""
        result = transformer.transform(
            sample_heart_rate_record, "Patient/test-user", device_reference="Device/device-123"
        )

        # Device handling depends on compatibility mode
        # In modern mode, should have device reference
        # In legacy mode, should have extensions
        assert "device" in result or "extension" in result

    def test_transform_includes_provider_metadata(self, transformer, sample_heart_rate_record):
        """Test transform includes provider metadata in tags."""
        result = transformer.transform(sample_heart_rate_record, "Patient/test-user")

        tags = result["meta"]["tag"]
        provider_tags = [t for t in tags if "open-health-exchange.com/provider" in t.get("system", "")]
        assert len(provider_tags) > 0
        assert provider_tags[0]["code"] == "withings"

    def test_transform_includes_identifier(self, transformer, sample_heart_rate_record):
        """Test transform includes provider-specific identifier."""
        result = transformer.transform(sample_heart_rate_record, "Patient/test-user")

        assert "identifier" in result
        assert len(result["identifier"]) > 0

    def test_transform_with_metadata_adds_note(self, transformer):
        """Test transform adds note when record has metadata."""
        record = HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.HEART_RATE,
            value=72.0,
            unit="bpm",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            metadata={"device_model": "BPM Core"},
        )

        result = transformer.transform(record, "Patient/test-user")

        assert "note" in result
        assert "BPM Core" in result["note"][0]["text"]

    def test_transform_ecg_delegates_to_ecg_transformer(self, transformer):
        """Test ECG records are delegated to ECG transformer."""
        record = HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.ECG,
            value={"heart_rate": 72, "signal_data": [0.1, 0.2]},
            unit="mV",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

        with patch.object(transformer.ecg_transformer, "transform_ecg_to_fhir_panel") as mock_transform:
            mock_transform.return_value = {"resourceType": "Observation", "id": "ecg-123"}

            _result = transformer.transform(record, "Patient/test-user")

            mock_transform.assert_called_once()

    def test_transform_multiple_records(self, transformer, sample_heart_rate_record, sample_steps_record):
        """Test transforming multiple records."""
        records = [sample_heart_rate_record, sample_steps_record]

        results = transformer.transform_multiple_records(records, "Patient/test-user")

        assert len(results) == 2
        assert all(r["resourceType"] == "Observation" for r in results)

    def test_transform_multiple_records_handles_errors(self, transformer, sample_heart_rate_record):
        """Test transform_multiple_records continues on individual record errors."""
        bad_record = HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.BLOOD_PRESSURE,
            value="invalid",  # This will cause an error
            unit="mmHg",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

        records = [sample_heart_rate_record, bad_record]

        results = transformer.transform_multiple_records(records, "Patient/test-user")

        # Should have 1 successful transformation (heart rate)
        assert len(results) == 1

    def test_transform_raises_for_unknown_data_type_without_loinc(self, transformer):
        """Test transform raises error for data type without LOINC code."""
        # Create a mock record with an invalid data type
        record = MagicMock()
        record.data_type = MagicMock()
        record.data_type.value = "unknown_type"
        record.data_type.name = "UNKNOWN"

        with patch.object(transformer, "get_loinc_code", return_value=None):
            with patch.dict("transformers.health_data_transformers.HEALTH_DATA_LOINC_CODES", {}, clear=True):
                with pytest.raises(ValueError, match="No LOINC code defined"):
                    transformer.transform_health_record(record, "Patient/test-user")


class TestHealthDataBundle:
    """Tests for HealthDataBundle class."""

    def test_create_transaction_bundle(self):
        """Test creating a transaction bundle."""
        observations = [
            {"resourceType": "Observation", "id": "obs-1", "identifier": [{"value": "id-1"}]},
            {"resourceType": "Observation", "id": "obs-2", "identifier": [{"value": "id-2"}]},
        ]

        bundle = HealthDataBundle.create_transaction_bundle(observations)

        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] in ["batch", "transaction"]
        assert len(bundle["entry"]) == 2

    def test_create_transaction_bundle_with_custom_id(self):
        """Test creating bundle with custom ID."""
        observations = [{"resourceType": "Observation", "id": "obs-1"}]

        bundle = HealthDataBundle.create_transaction_bundle(observations, bundle_id="custom-bundle-123")

        assert bundle["id"] == "custom-bundle-123"

    def test_create_transaction_bundle_includes_metadata(self):
        """Test bundle includes proper metadata tags."""
        observations = [{"resourceType": "Observation", "id": "obs-1"}]

        bundle = HealthDataBundle.create_transaction_bundle(observations)

        assert "meta" in bundle
        assert "tag" in bundle["meta"]
        tag_codes = [t["code"] for t in bundle["meta"]["tag"]]
        assert "HDATA" in tag_codes


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture
    def sample_record(self):
        """Create a sample health record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.HEART_RATE,
            value=72.0,
            unit="bpm",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    def test_transform_health_record_function(self, sample_record):
        """Test transform_health_record convenience function."""
        result = transform_health_record(sample_record, "Patient/test-user")

        assert result["resourceType"] == "Observation"
        assert result["valueQuantity"]["value"] == 72.0

    def test_transform_multiple_health_records_function(self, sample_record):
        """Test transform_multiple_health_records convenience function."""
        results = transform_multiple_health_records([sample_record], "Patient/test-user")

        assert len(results) == 1
        assert results[0]["resourceType"] == "Observation"

    def test_create_health_data_bundle_function(self):
        """Test create_health_data_bundle convenience function."""
        observations = [{"resourceType": "Observation", "id": "obs-1"}]

        bundle = create_health_data_bundle(observations)

        assert bundle["resourceType"] == "Bundle"
        assert len(bundle["entry"]) == 1
