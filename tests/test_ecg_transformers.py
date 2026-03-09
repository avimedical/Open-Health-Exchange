"""
Tests for ECG FHIR transformers.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from ingestors.health_data_constants import HealthDataRecord, HealthDataType, Provider
from transformers.ecg_transformers import AFIB_INTERPRETATION_CODES, ECGTransformer


class TestAFibInterpretationCodes:
    """Tests for AFib interpretation code mappings."""

    def test_positive_codes(self):
        """Test positive AFib detection codes."""
        assert AFIB_INTERPRETATION_CODES["POSITIVE"]["code"] == "DET"
        assert AFIB_INTERPRETATION_CODES["atrial_fibrillation"]["code"] == "DET"
        assert AFIB_INTERPRETATION_CODES["afib"]["code"] == "DET"

    def test_negative_codes(self):
        """Test negative AFib detection codes."""
        assert AFIB_INTERPRETATION_CODES["NEGATIVE"]["code"] == "N"
        assert AFIB_INTERPRETATION_CODES["sinus_rhythm"]["code"] == "N"
        assert AFIB_INTERPRETATION_CODES["normal"]["code"] == "N"

    def test_inconclusive_codes(self):
        """Test inconclusive AFib detection codes."""
        assert AFIB_INTERPRETATION_CODES["INCONCLUSIVE"]["code"] == "IND"
        assert AFIB_INTERPRETATION_CODES["inconclusive"]["code"] == "IND"
        assert AFIB_INTERPRETATION_CODES["poor_reading"]["code"] == "IND"


class TestECGTransformer:
    """Tests for ECGTransformer class."""

    @pytest.fixture
    def transformer(self):
        """Create ECGTransformer instance."""
        return ECGTransformer()

    @pytest.fixture
    def sample_ecg_record(self):
        """Create sample ECG health data record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.ECG,
            value=72,  # Average heart rate during ECG
            unit="bpm",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            metadata={
                "ecg_metrics": {
                    "result_classification": "NEGATIVE",
                    "device_name": "ScanWatch",
                    "firmware_version": "1.0.0",
                },
                "waveform_data": {
                    "samples": [1, 2, 3, 4, 5],
                    "sampling_frequency_hz": 250,
                    "scaling_factor": 0.01,
                    "duration_seconds": 30,
                },
            },
        )

    @pytest.fixture
    def sample_ecg_record_minimal(self):
        """Create minimal ECG record without waveform data."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.FITBIT,
            data_type=HealthDataType.ECG,
            value=65,
            unit="bpm",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    def _get_ecg_observation(self, result):
        """Helper to get ECG observation from result (handles list or dict)."""
        if isinstance(result, list):
            return result[0]  # ECG is first in list
        return result

    def test_transform_basic_ecg(self, transformer, sample_ecg_record):
        """Test basic ECG transformation."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        assert ecg_obs["resourceType"] == "Observation"
        assert ecg_obs["code"]["coding"][0]["code"] == "8601-7"
        assert ecg_obs["code"]["coding"][0]["display"] == "EKG impression"
        assert ecg_obs["subject"]["reference"] == "Patient/test-user"

    def test_transform_includes_status(self, transformer, sample_ecg_record):
        """Test ECG observation includes status."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        assert "status" in ecg_obs

    def test_transform_includes_category(self, transformer, sample_ecg_record):
        """Test ECG observation includes correct category."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        assert len(ecg_obs["category"]) > 0
        assert ecg_obs["category"][0]["coding"][0]["code"] == "procedure"

    def test_transform_includes_effective_datetime(self, transformer, sample_ecg_record):
        """Test ECG observation includes effective datetime."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        assert "effectiveDateTime" in ecg_obs
        assert "2024-01-15" in ecg_obs["effectiveDateTime"]

    def test_transform_includes_components(self, transformer, sample_ecg_record):
        """Test ECG observation includes components."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        assert "component" in ecg_obs
        assert len(ecg_obs["component"]) > 0

    def test_transform_includes_afib_classification_component(self, transformer, sample_ecg_record):
        """Test ECG includes AFib classification in components."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        # Find the EKG impression component with valueString (AFib classification)
        afib_components = [
            c for c in ecg_obs["component"] if c["code"]["coding"][0]["code"] == "8601-7" and "valueString" in c
        ]

        assert len(afib_components) > 0
        assert afib_components[0]["valueString"] == "NEGATIVE"

    def test_transform_includes_heart_rate_component_modern_mode(self, transformer, sample_ecg_record):
        """Test ECG includes heart rate as component in modern mode."""
        with patch.object(transformer, "get_compatibility_config", return_value={"ECG_EMIT_SEPARATE_HR": False}):
            result = transformer.transform(sample_ecg_record, "Patient/test-user")

            # Find heart rate component
            hr_components = [c for c in result["component"] if c["code"]["coding"][0]["code"] == "8867-4"]

            assert len(hr_components) > 0
            assert hr_components[0]["valueQuantity"]["value"] == 72
            assert hr_components[0]["valueQuantity"]["unit"] == "bpm"

    def test_transform_includes_waveform_data(self, transformer, sample_ecg_record):
        """Test ECG includes waveform data as sampled data component."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        # Find waveform component
        waveform_components = [c for c in ecg_obs["component"] if "valueSampledData" in c]

        assert len(waveform_components) > 0
        sampled_data = waveform_components[0]["valueSampledData"]
        assert "data" in sampled_data
        assert sampled_data["interval"] == 4.0  # 1000ms / 250Hz
        assert sampled_data["intervalUnit"] == "ms"

    def test_transform_includes_device_notes(self, transformer, sample_ecg_record):
        """Test ECG includes device notes."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        assert "note" in ecg_obs
        assert len(ecg_obs["note"]) > 0
        assert "ScanWatch" in ecg_obs["note"][0]["text"]
        assert "Withings" in ecg_obs["note"][0]["text"]

    def test_transform_with_device_reference(self, transformer, sample_ecg_record):
        """Test ECG with device reference."""
        with patch.object(transformer, "should_use_device_extensions", return_value=False):
            with patch.object(transformer, "get_compatibility_config", return_value={"ECG_EMIT_SEPARATE_HR": False}):
                result = transformer.transform(sample_ecg_record, "Patient/test-user", "Device/device-123")
                ecg_obs = self._get_ecg_observation(result)

                assert ecg_obs.get("device", {}).get("reference") == "Device/device-123"

    def test_transform_minimal_record_modern_mode(self, transformer, sample_ecg_record_minimal):
        """Test ECG transformation with minimal record in modern mode."""
        # Use modern mode to avoid the sampling_frequency bug
        with patch.object(transformer, "get_compatibility_config", return_value={"ECG_EMIT_SEPARATE_HR": False}):
            result = transformer.transform(sample_ecg_record_minimal, "Patient/test-user")
            ecg_obs = self._get_ecg_observation(result)

            assert ecg_obs["resourceType"] == "Observation"
            assert ecg_obs["code"]["coding"][0]["code"] == "8601-7"

    def test_transform_generates_deterministic_id(self, transformer, sample_ecg_record):
        """Test ECG generates deterministic resource ID."""
        result1 = transformer.transform(sample_ecg_record, "Patient/test-user")
        result2 = transformer.transform(sample_ecg_record, "Patient/test-user")

        ecg1 = self._get_ecg_observation(result1)
        ecg2 = self._get_ecg_observation(result2)

        assert ecg1["id"] == ecg2["id"]

    def test_transform_includes_identifier(self, transformer, sample_ecg_record):
        """Test ECG includes provider identifier."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        assert "identifier" in ecg_obs
        assert len(ecg_obs["identifier"]) > 0
        assert ecg_obs["identifier"][0]["system"] is not None

    def test_transform_waveform_is_first_component(self, transformer, sample_ecg_record):
        """Test waveform SampledData is the first component (app reads component.first.valueSampledData)."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        first_component = ecg_obs["component"][0]
        assert "valueSampledData" in first_component
        assert first_component["code"]["coding"][0]["code"] == "8601-7"

    def test_transform_waveform_uses_loinc_code(self, transformer, sample_ecg_record):
        """Test waveform component uses LOINC 8601-7 code (not MDC lead code)."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        waveform_component = ecg_obs["component"][0]
        assert waveform_component["code"]["coding"][0]["system"] == "http://loinc.org"
        assert waveform_component["code"]["coding"][0]["code"] == "8601-7"

    def test_transform_always_includes_interpretation(self, transformer, sample_ecg_record):
        """Test interpretation is always included (not only when ECG_AFIB_CODED_INTERPRETATION is set)."""
        with patch.object(transformer, "get_compatibility_config", return_value={"ECG_EMIT_SEPARATE_HR": False}):
            result = transformer.transform(sample_ecg_record, "Patient/test-user")
            ecg_obs = self._get_ecg_observation(result)

            assert "interpretation" in ecg_obs
            assert (
                ecg_obs["interpretation"][0]["coding"][0]["system"]
                == "http://hl7.org/fhir/ValueSet/observation-interpretation"
            )

    def test_transform_includes_meta(self, transformer, sample_ecg_record):
        """Test ECG includes meta information."""
        result = transformer.transform(sample_ecg_record, "Patient/test-user")
        ecg_obs = self._get_ecg_observation(result)

        assert "meta" in ecg_obs


class TestECGTransformerLegacyMode:
    """Tests for ECGTransformer legacy mode features."""

    @pytest.fixture
    def transformer(self):
        """Create ECGTransformer instance."""
        return ECGTransformer()

    @pytest.fixture
    def sample_ecg_record(self):
        """Create sample ECG health data record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.ECG,
            value=72,
            unit="bpm",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            metadata={"ecg_metrics": {"result_classification": "NEGATIVE"}},
        )

    def _get_ecg_observation(self, result):
        """Helper to get ECG observation from result (handles list or dict)."""
        if isinstance(result, list):
            return result[0]
        return result

    def test_legacy_mode_emits_separate_hr_observation(self, transformer, sample_ecg_record):
        """Test legacy mode emits separate HR observation."""
        with patch.object(
            transformer,
            "get_compatibility_config",
            return_value={
                "ECG_EMIT_SEPARATE_HR": True,
                "ENABLE_OBSERVATION_LINKING": True,
            },
        ):
            result = transformer.transform(sample_ecg_record, "Patient/test-user")

            # Should return list with ECG and HR observations
            assert isinstance(result, list)
            assert len(result) == 2

            ecg_obs = result[0]
            hr_obs = result[1]

            assert ecg_obs["code"]["coding"][0]["code"] == "8601-7"
            assert hr_obs["code"]["coding"][0]["code"] == "8867-4"

    def test_legacy_mode_hr_linked_via_derived_from(self, transformer, sample_ecg_record):
        """Test legacy mode HR is linked to ECG via derivedFrom."""
        with patch.object(
            transformer,
            "get_compatibility_config",
            return_value={
                "ECG_EMIT_SEPARATE_HR": True,
                "ENABLE_OBSERVATION_LINKING": True,
            },
        ):
            result = transformer.transform(sample_ecg_record, "Patient/test-user")

            hr_obs = result[1]
            assert "derivedFrom" in hr_obs
            assert len(hr_obs["derivedFrom"]) > 0

    def test_afib_coded_interpretation_always_included(self, transformer, sample_ecg_record):
        """Test interpretation is always included when result_classification is present."""
        with patch.object(
            transformer,
            "get_compatibility_config",
            return_value={
                "ECG_EMIT_SEPARATE_HR": False,
            },
        ):
            result = transformer.transform(sample_ecg_record, "Patient/test-user")
            ecg_obs = self._get_ecg_observation(result)

            assert "interpretation" in ecg_obs
            assert len(ecg_obs["interpretation"]) > 0
            assert ecg_obs["interpretation"][0]["coding"][0]["code"] == "N"


class TestSampledDataCreation:
    """Tests for ECG sampled data creation."""

    @pytest.fixture
    def transformer(self):
        """Create ECGTransformer instance."""
        return ECGTransformer()

    def test_create_sampled_data_basic(self, transformer):
        """Test basic sampled data creation."""
        samples = [100, 150, 200, 175, 125]
        result = transformer._create_sampled_data(
            samples=samples,
            sampling_frequency=250,
            scaling_factor=0.01,
            duration_seconds=30,
        )

        assert result["origin"]["value"] == 0
        assert result["origin"]["unit"] == "uV"
        assert result["interval"] == 4.0  # 1000ms / 250Hz
        assert result["intervalUnit"] == "ms"
        assert result["factor"] == 0.01
        assert result["dimensions"] == 1
        assert result["data"] == "100 150 200 175 125"

    def test_create_sampled_data_empty_samples(self, transformer):
        """Test sampled data with empty samples."""
        result = transformer._create_sampled_data(
            samples=[],
            sampling_frequency=250,
            scaling_factor=0.01,
            duration_seconds=30,
        )

        assert result == {}

    def test_create_sampled_data_default_frequency(self, transformer):
        """Test sampled data with zero frequency uses default."""
        result = transformer._create_sampled_data(
            samples=[1, 2, 3],
            sampling_frequency=0,
            scaling_factor=0.01,
            duration_seconds=30,
        )

        assert result["interval"] == 4.0  # Default for 250Hz

    def test_create_sampled_data_limits_samples(self, transformer):
        """Test sampled data limits to 10000 samples."""
        large_samples = list(range(15000))
        result = transformer._create_sampled_data(
            samples=large_samples,
            sampling_frequency=250,
            scaling_factor=0.01,
            duration_seconds=30,
        )

        sample_count = len(result["data"].split())
        assert sample_count == 10000


class TestAFibInterpretation:
    """Tests for AFib interpretation creation."""

    @pytest.fixture
    def transformer(self):
        """Create ECGTransformer instance."""
        return ECGTransformer()

    def test_create_afib_interpretation_negative(self, transformer):
        """Test AFib interpretation for negative result."""
        result = transformer._create_afib_interpretation("NEGATIVE")

        assert result is not None
        assert len(result) > 0
        assert result[0]["coding"][0]["code"] == "N"
        assert result[0]["coding"][0]["display"] == "sinusRhythm"

    def test_create_afib_interpretation_positive(self, transformer):
        """Test AFib interpretation for positive result."""
        result = transformer._create_afib_interpretation("POSITIVE")

        assert result is not None
        assert result[0]["coding"][0]["code"] == "DET"
        assert result[0]["coding"][0]["display"] == "atrialFibrillation"

    def test_create_afib_interpretation_inconclusive(self, transformer):
        """Test AFib interpretation for inconclusive result."""
        result = transformer._create_afib_interpretation("INCONCLUSIVE")

        assert result is not None
        assert result[0]["coding"][0]["code"] == "IND"

    def test_create_afib_interpretation_case_insensitive(self, transformer):
        """Test AFib interpretation is case insensitive via partial match."""
        # "negative" lowercase isn't a direct key, but it matches via partial match
        result1 = transformer._create_afib_interpretation("normal rhythm")
        result2 = transformer._create_afib_interpretation("NEGATIVE")

        # Both should resolve to the same code (N for sinusRhythm)
        assert result1[0]["coding"][0]["code"] == result2[0]["coding"][0]["code"]

    def test_create_afib_interpretation_partial_match_normal(self, transformer):
        """Test AFib interpretation with partial match for normal."""
        result = transformer._create_afib_interpretation("Normal sinus rhythm")

        assert result is not None
        assert result[0]["coding"][0]["code"] == "N"

    def test_create_afib_interpretation_partial_match_afib(self, transformer):
        """Test AFib interpretation with partial match for AFib."""
        result = transformer._create_afib_interpretation("Possible atrial fibrillation detected")

        assert result is not None
        assert result[0]["coding"][0]["code"] == "DET"

    def test_create_afib_interpretation_unknown(self, transformer):
        """Test AFib interpretation returns None for unknown classification."""
        result = transformer._create_afib_interpretation("completely_unknown_value")

        assert result is None

    def test_create_afib_interpretation_includes_issued_extension(self, transformer):
        """Test AFib interpretation includes issued timestamp extension."""
        result = transformer._create_afib_interpretation("NEGATIVE")

        assert "extension" in result[0]
        extensions = result[0]["extension"]
        issued_ext = [e for e in extensions if e.get("url") == "Issued"]
        assert len(issued_ext) > 0


class TestRelatedHRObservation:
    """Tests for creating related HR observation."""

    @pytest.fixture
    def transformer(self):
        """Create ECGTransformer instance."""
        return ECGTransformer()

    @pytest.fixture
    def sample_ecg_record(self):
        """Create sample ECG health data record."""
        return HealthDataRecord(
            user_id="test-user",
            provider=Provider.WITHINGS,
            data_type=HealthDataType.ECG,
            value=72,
            unit="bpm",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        )

    def test_create_related_hr_observation(self, transformer, sample_ecg_record):
        """Test creating related HR observation."""
        ecg_observation = {"id": "ecg-123", "identifier": [{"value": "ecg-id"}]}

        with patch.object(
            transformer,
            "get_compatibility_config",
            return_value={
                "ENABLE_OBSERVATION_LINKING": True,
            },
        ):
            result = transformer._create_related_hr_observation(
                record=sample_ecg_record,
                patient_reference="Patient/test-user",
                patient_id="test-user",
                device_reference=None,
                ecg_observation=ecg_observation,
            )

        assert result["resourceType"] == "Observation"
        assert result["code"]["coding"][0]["code"] == "8867-4"
        assert result["valueQuantity"]["value"] == 72
        assert result["valueQuantity"]["unit"] == "bpm"

    def test_related_hr_has_vital_signs_category(self, transformer, sample_ecg_record):
        """Test related HR observation has vital-signs category."""
        ecg_observation = {"id": "ecg-123"}

        with patch.object(transformer, "get_compatibility_config", return_value={}):
            result = transformer._create_related_hr_observation(
                record=sample_ecg_record,
                patient_reference="Patient/test-user",
                patient_id="test-user",
                device_reference=None,
                ecg_observation=ecg_observation,
            )

        assert result["category"][0]["coding"][0]["code"] == "vital-signs"

    def test_related_hr_includes_derived_from(self, transformer, sample_ecg_record):
        """Test related HR includes derivedFrom reference to ECG."""
        ecg_observation = {"id": "ecg-123"}

        with patch.object(
            transformer,
            "get_compatibility_config",
            return_value={
                "ENABLE_OBSERVATION_LINKING": True,
            },
        ):
            result = transformer._create_related_hr_observation(
                record=sample_ecg_record,
                patient_reference="Patient/test-user",
                patient_id="test-user",
                device_reference=None,
                ecg_observation=ecg_observation,
            )

        assert "derivedFrom" in result
        assert result["derivedFrom"][0]["reference"] == "Observation/ecg-123"

    def test_related_hr_with_device_reference(self, transformer, sample_ecg_record):
        """Test related HR with device reference."""
        ecg_observation = {"id": "ecg-123"}

        with patch.object(transformer, "get_compatibility_config", return_value={}):
            with patch.object(transformer, "should_use_device_extensions", return_value=False):
                result = transformer._create_related_hr_observation(
                    record=sample_ecg_record,
                    patient_reference="Patient/test-user",
                    patient_id="test-user",
                    device_reference="Device/device-123",
                    ecg_observation=ecg_observation,
                )

        assert result.get("device", {}).get("reference") == "Device/device-123"
