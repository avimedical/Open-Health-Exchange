"""
Tests for health data managers.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from ingestors.constants import Provider
from ingestors.health_data_constants import (
    FHIR_UNITS,
    DateRange,
    HealthDataType,
    MeasurementSource,
    SyncTrigger,
)
from ingestors.health_data_manager import (
    BaseHealthDataManager,
    FitbitHealthDataManager,
    HealthDataManagerFactory,
    WithingsHealthDataManager,
)


class TestBaseHealthDataManager:
    """Tests for BaseHealthDataManager class."""

    def test_create_health_record(self):
        """Test creating a health data record."""
        # Create a concrete implementation for testing
        with patch.object(BaseHealthDataManager, "__abstractmethods__", set()):
            manager = BaseHealthDataManager(Provider.WITHINGS)

            record = manager._create_health_record(
                user_id="test-user",
                data_type=HealthDataType.HEART_RATE,
                timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                value=72.0,
                unit="bpm",
                device_id="device-123",
                metadata={"source": "test"},
                measurement_source=MeasurementSource.DEVICE,
            )

            assert record.provider == Provider.WITHINGS
            assert record.user_id == "test-user"
            assert record.data_type == HealthDataType.HEART_RATE
            assert record.value == 72.0
            assert record.unit == "bpm"
            assert record.device_id == "device-123"
            assert record.metadata == {"source": "test"}
            assert record.measurement_source == MeasurementSource.DEVICE

    def test_create_health_record_with_defaults(self):
        """Test creating health record with default values."""
        with patch.object(BaseHealthDataManager, "__abstractmethods__", set()):
            manager = BaseHealthDataManager(Provider.FITBIT)

            record = manager._create_health_record(
                user_id="test-user",
                data_type=HealthDataType.STEPS,
                timestamp=datetime(2024, 1, 15, tzinfo=UTC),
                value=10000.0,
                unit="steps",
            )

            assert record.device_id is None
            assert record.metadata == {}
            assert record.measurement_source == MeasurementSource.UNKNOWN


class TestWithingsHealthDataManager:
    """Tests for WithingsHealthDataManager class."""

    @pytest.fixture
    def manager(self):
        """Create WithingsHealthDataManager instance."""
        return WithingsHealthDataManager()

    def test_initialization(self, manager):
        """Test manager initializes with correct provider."""
        assert manager.provider == Provider.WITHINGS

    def test_get_supported_data_types(self, manager):
        """Test getting supported data types."""
        supported = manager.get_supported_data_types()

        assert HealthDataType.HEART_RATE in supported
        assert HealthDataType.STEPS in supported
        assert HealthDataType.WEIGHT in supported
        assert HealthDataType.BLOOD_PRESSURE in supported
        assert HealthDataType.ECG in supported
        assert HealthDataType.TEMPERATURE in supported
        assert HealthDataType.SPO2 in supported
        assert HealthDataType.SLEEP in supported
        assert HealthDataType.RR_INTERVALS in supported
        assert len(supported) == 9

    def test_fetch_health_data_heart_rate(self, manager):
        """Test fetching heart rate data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                "value": 72,
                "device_id": "device-123",
                "measurement_id": "meas-1",
                "category": 1,
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.HEART_RATE],
                date_range=date_range,
                sync_trigger=SyncTrigger.WEBHOOK,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.HEART_RATE
        assert records[0].value == 72.0
        assert records[0].unit == "bpm"

    def test_fetch_health_data_steps(self, manager):
        """Test fetching steps data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "date": datetime(2024, 1, 15, tzinfo=UTC),
                "steps": 10000,
                "distance": 8500,
                "calories": 350,
                "elevation": 50,
                "device_id": "device-123",
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.STEPS],
                date_range=date_range,
                sync_trigger=SyncTrigger.MANUAL,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.STEPS
        assert records[0].value == 10000.0
        assert records[0].unit == "steps"

    def test_fetch_health_data_weight(self, manager):
        """Test fetching weight data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC),
                "value": 75.5,
                "device_id": "scale-123",
                "measurement_id": "meas-2",
                "category": 1,
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.WEIGHT],
                date_range=date_range,
                sync_trigger=SyncTrigger.INITIAL,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.WEIGHT
        assert records[0].value == 75.5
        assert records[0].unit == "kg"

    def test_fetch_health_data_blood_pressure(self, manager):
        """Test fetching blood pressure data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 9, 0, 0, tzinfo=UTC),
                "value": 120,  # systolic
                "device_id": "bp-monitor-123",
                "measurement_id": "meas-3",
                "category": 1,
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.BLOOD_PRESSURE],
                date_range=date_range,
                sync_trigger=SyncTrigger.WEBHOOK,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.BLOOD_PRESSURE
        assert records[0].unit == "mmHg"

    def test_fetch_health_data_ecg(self, manager):
        """Test fetching ECG data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
                "heart_rate": 72,
                "signal_id": 12345,
                "afib_result": 0,
                "afib_classification": "Normal sinus rhythm",
                "device_id": "ecg-123",
                "device_model": 94,
                "modified": datetime(2024, 1, 15, 10, 31, 0, tzinfo=UTC),
                "qrs_interval": 100,
                "pr_interval": 160,
                "qt_interval": 400,
                "qtc_interval": 410,
                "waveform_samples": [-57, -62, -66, -71, 34],
                "sampling_frequency": 500,
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.ECG],
                date_range=date_range,
                sync_trigger=SyncTrigger.WEBHOOK,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.ECG
        assert records[0].unit == "uV"
        assert records[0].value == 72.0
        assert records[0].metadata["ecg_metrics"]["result_classification"] == "N"
        assert records[0].metadata["ecg_metrics"]["signal_id"] == 12345
        assert records[0].metadata["waveform_data"]["samples"] == [-57, -62, -66, -71, 34]
        assert records[0].metadata["waveform_data"]["sampling_frequency_hz"] == 500

    def test_fetch_health_data_temperature(self, manager):
        """Test fetching temperature data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 7, 0, 0, tzinfo=UTC),
                "value": 36.5,
                "device_id": "thermo-123",
                "measurement_id": "meas-4",
                "category": 1,
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.TEMPERATURE],
                date_range=date_range,
                sync_trigger=SyncTrigger.WEBHOOK,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.TEMPERATURE
        assert records[0].value == 36.5
        assert records[0].unit == FHIR_UNITS["temperature"]["display"]

    def test_fetch_health_data_spo2(self, manager):
        """Test fetching SpO2 data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 6, 0, 0, tzinfo=UTC),
                "value": 98,
                "device_id": "pulse-123",
                "measurement_id": "meas-5",
                "category": 1,
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.SPO2],
                date_range=date_range,
                sync_trigger=SyncTrigger.WEBHOOK,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.SPO2
        assert records[0].value == 98
        assert records[0].unit == "%"

    def test_fetch_health_data_sleep(self, manager):
        """Test fetching sleep data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC),
                "duration": 25200,
                "deep_sleep_duration": 7200,
                "light_sleep_duration": 14400,
                "rem_sleep_duration": 3600,
                "wake_up_count": 2,
                "end_timestamp": datetime(2024, 1, 15, 7, 0, 0, tzinfo=UTC),
                "device_id": "sleep-123",
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.SLEEP],
                date_range=date_range,
                sync_trigger=SyncTrigger.WEBHOOK,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.SLEEP
        assert records[0].unit == "seconds"
        assert records[0].value["duration"] == 25200

    def test_fetch_health_data_unsupported_type_skipped(self, manager):
        """Test that unsupported data types are skipped with warning."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = []

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        # RR_INTERVALS is not supported by Withings in the test manager
        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.RR_INTERVALS],
                date_range=date_range,
                sync_trigger=SyncTrigger.MANUAL,
            )

        # Should return empty list (unsupported type skipped)
        assert records == []

    def test_fetch_health_data_api_error_continues(self, manager):
        """Test that API errors don't stop processing other data types."""
        from ingestors.api_clients import APIError

        mock_client = MagicMock()
        # First call raises error, second returns data
        mock_client.get_health_data.side_effect = [
            APIError("API error"),
            [
                {
                    "date": datetime(2024, 1, 15, tzinfo=UTC),
                    "steps": 5000,
                }
            ],
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.HEART_RATE, HealthDataType.STEPS],
                date_range=date_range,
                sync_trigger=SyncTrigger.MANUAL,
            )

        # Should still get steps data despite heart rate error
        assert len(records) == 1
        assert records[0].data_type == HealthDataType.STEPS

    def test_fetch_health_data_multiple_types(self, manager):
        """Test fetching multiple data types at once."""
        mock_client = MagicMock()
        mock_client.get_health_data.side_effect = [
            [
                {
                    "timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                    "value": 72,
                    "measurement_source": MeasurementSource.DEVICE,
                }
            ],
            [
                {
                    "date": datetime(2024, 1, 15, tzinfo=UTC),
                    "steps": 10000,
                }
            ],
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.HEART_RATE, HealthDataType.STEPS],
                date_range=date_range,
                sync_trigger=SyncTrigger.MANUAL,
            )

        assert len(records) == 2


class TestFitbitHealthDataManager:
    """Tests for FitbitHealthDataManager class."""

    @pytest.fixture
    def manager(self):
        """Create FitbitHealthDataManager instance."""
        return FitbitHealthDataManager()

    def test_initialization(self, manager):
        """Test manager initializes with correct provider."""
        assert manager.provider == Provider.FITBIT

    def test_get_supported_data_types(self, manager):
        """Test getting supported data types."""
        supported = manager.get_supported_data_types()

        assert HealthDataType.HEART_RATE in supported
        assert HealthDataType.STEPS in supported
        assert HealthDataType.WEIGHT in supported
        assert HealthDataType.SLEEP in supported
        assert HealthDataType.ECG in supported
        assert HealthDataType.RR_INTERVALS in supported
        assert len(supported) == 6

    def test_fetch_health_data_heart_rate(self, manager):
        """Test fetching Fitbit heart rate data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, tzinfo=UTC),
                "value": 65,
                "device_id": "tracker-123",
                "heart_rate_type": "resting",
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.HEART_RATE],
                date_range=date_range,
                sync_trigger=SyncTrigger.WEBHOOK,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.HEART_RATE
        assert records[0].value == 65.0
        assert records[0].metadata["heart_rate_type"] == "resting"

    def test_fetch_health_data_steps(self, manager):
        """Test fetching Fitbit steps data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "date": datetime(2024, 1, 15, tzinfo=UTC),
                "steps": 8500,
                "device_id": "tracker-123",
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.STEPS],
                date_range=date_range,
                sync_trigger=SyncTrigger.MANUAL,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.STEPS
        assert records[0].value == 8500.0

    def test_fetch_health_data_weight(self, manager):
        """Test fetching Fitbit weight data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC),
                "value": 70.2,
                "device_id": "scale-123",
                "source": "Aria 2",
                "log_id": 123456,
                "bmi": 22.5,
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.WEIGHT],
                date_range=date_range,
                sync_trigger=SyncTrigger.INITIAL,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.WEIGHT
        assert records[0].value == 70.2
        assert records[0].metadata["fitbit_source"] == "Aria 2"

    def test_fetch_health_data_sleep(self, manager):
        """Test fetching Fitbit sleep data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 23, 0, 0, tzinfo=UTC),
                "value": 420,  # minutes asleep
                "unit": "minutes",
                "device_id": "tracker-123",
                "log_type": "auto_detected",
                "log_id": 789012,
                "end_time": datetime(2024, 1, 16, 6, 0, 0, tzinfo=UTC),
                "sleep_metrics": {"efficiency": 90},
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.SLEEP],
                date_range=date_range,
                sync_trigger=SyncTrigger.WEBHOOK,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.SLEEP
        assert records[0].value == 420.0
        assert records[0].metadata["fitbit_log_type"] == "auto_detected"

    def test_fetch_health_data_ecg(self, manager):
        """Test fetching Fitbit ECG data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                "value": 72,
                "unit": "uV",
                "device_id": "watch-123",
                "ecg_metrics": {"rhythm": "normal"},
                "waveform_data": {"samples": [1, 2, 3]},
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.ECG],
                date_range=date_range,
                sync_trigger=SyncTrigger.WEBHOOK,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.ECG
        assert records[0].value["heart_rate"] == 72

    def test_fetch_health_data_rr_intervals(self, manager):
        """Test fetching Fitbit RR intervals/HRV data."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 6, 0, 0, tzinfo=UTC),
                "value": 45.5,  # RMSSD
                "unit": "ms",
                "device_id": "tracker-123",
                "hrv_metrics": {"coverage": 0.95},
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.RR_INTERVALS],
                date_range=date_range,
                sync_trigger=SyncTrigger.WEBHOOK,
            )

        assert len(records) == 1
        assert records[0].data_type == HealthDataType.RR_INTERVALS
        assert records[0].value == 45.5
        assert records[0].unit == "ms"

    def test_fetch_health_data_unsupported_type_skipped(self, manager):
        """Test that unsupported data types are skipped."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = []

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        # BLOOD_PRESSURE is not in Fitbit's supported types
        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.BLOOD_PRESSURE],
                date_range=date_range,
                sync_trigger=SyncTrigger.MANUAL,
            )

        assert records == []

    def test_fetch_health_data_skips_zero_steps(self, manager):
        """Test that zero step counts are skipped."""
        mock_client = MagicMock()
        mock_client.get_health_data.return_value = [
            {
                "date": datetime(2024, 1, 15, tzinfo=UTC),
                "steps": 0,
            },
            {
                "date": datetime(2024, 1, 16, tzinfo=UTC),
                "steps": 5000,
            },
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 17, tzinfo=UTC),
        )

        with patch("ingestors.health_data_manager.get_unified_health_data_client", return_value=mock_client):
            records = manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.STEPS],
                date_range=date_range,
                sync_trigger=SyncTrigger.MANUAL,
            )

        # Only non-zero steps should be included
        assert len(records) == 1
        assert records[0].value == 5000.0


class TestHealthDataManagerFactory:
    """Tests for HealthDataManagerFactory class."""

    def test_create_withings_manager(self):
        """Test creating Withings manager."""
        manager = HealthDataManagerFactory.create(Provider.WITHINGS)

        assert isinstance(manager, WithingsHealthDataManager)
        assert manager.provider == Provider.WITHINGS

    def test_create_fitbit_manager(self):
        """Test creating Fitbit manager."""
        manager = HealthDataManagerFactory.create(Provider.FITBIT)

        assert isinstance(manager, FitbitHealthDataManager)
        assert manager.provider == Provider.FITBIT

    def test_create_unsupported_provider_raises(self):
        """Test that creating manager for unsupported provider raises error."""
        with pytest.raises(ValueError, match="Unsupported health data provider"):
            # Create a mock provider that's not in the factory
            class FakeProvider:
                value = "fake"

            HealthDataManagerFactory.create(FakeProvider())

    def test_get_supported_providers(self):
        """Test getting list of supported providers."""
        providers = HealthDataManagerFactory.get_supported_providers()

        assert Provider.WITHINGS in providers
        assert Provider.FITBIT in providers
        assert len(providers) == 2

    def test_get_supported_data_types_withings(self):
        """Test getting supported data types for Withings."""
        data_types = HealthDataManagerFactory.get_supported_data_types(Provider.WITHINGS)

        assert HealthDataType.HEART_RATE in data_types
        assert HealthDataType.ECG in data_types
        assert HealthDataType.RR_INTERVALS in data_types
        assert len(data_types) == 9

    def test_get_supported_data_types_fitbit(self):
        """Test getting supported data types for Fitbit."""
        data_types = HealthDataManagerFactory.get_supported_data_types(Provider.FITBIT)

        assert HealthDataType.HEART_RATE in data_types
        assert HealthDataType.RR_INTERVALS in data_types
        assert len(data_types) == 6


class TestHealthDataRecord:
    """Tests for HealthDataRecord dataclass behavior in managers."""

    def test_record_with_dict_value(self):
        """Test creating record with dict value (for ECG, blood pressure, etc)."""
        with patch.object(BaseHealthDataManager, "__abstractmethods__", set()):
            manager = BaseHealthDataManager(Provider.WITHINGS)

            record = manager._create_health_record(
                user_id="test-user",
                data_type=HealthDataType.BLOOD_PRESSURE,
                timestamp=datetime(2024, 1, 15, tzinfo=UTC),
                value={"systolic": 120, "diastolic": 80},
                unit="mmHg",
            )

            assert record.value["systolic"] == 120
            assert record.value["diastolic"] == 80

    def test_record_with_complex_metadata(self):
        """Test creating record with complex metadata."""
        with patch.object(BaseHealthDataManager, "__abstractmethods__", set()):
            manager = BaseHealthDataManager(Provider.FITBIT)

            complex_metadata = {
                "source": "fitbit_api",
                "nested": {"key": "value"},
                "list": [1, 2, 3],
            }

            record = manager._create_health_record(
                user_id="test-user",
                data_type=HealthDataType.SLEEP,
                timestamp=datetime(2024, 1, 15, tzinfo=UTC),
                value=420.0,
                unit="minutes",
                metadata=complex_metadata,
            )

            assert record.metadata["nested"]["key"] == "value"
            assert record.metadata["list"] == [1, 2, 3]
