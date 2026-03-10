"""
Tests for unified health data manager.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from ingestors.constants import Provider
from ingestors.health_data_constants import (
    DateRange,
    HealthDataType,
    MeasurementSource,
    SyncTrigger,
)
from ingestors.unified_health_data_manager import (
    HealthDataManagerFactory,
    HealthDataQuery,
    ProviderHealthDataManager,
    UnifiedHealthDataManager,
    get_unified_health_data_manager,
)


class TestHealthDataQuery:
    """Tests for HealthDataQuery dataclass."""

    def test_query_creation(self):
        """Test creating a HealthDataQuery."""
        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )
        query = HealthDataQuery(
            provider=Provider.WITHINGS,
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE, HealthDataType.STEPS],
            date_range=date_range,
            sync_trigger=SyncTrigger.WEBHOOK,
        )

        assert query.provider == Provider.WITHINGS
        assert query.user_id == "test-user"
        assert len(query.data_types) == 2
        assert query.sync_trigger == SyncTrigger.WEBHOOK

    def test_cache_key_generation(self):
        """Test cache key generation."""
        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )
        query = HealthDataQuery(
            provider=Provider.WITHINGS,
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            date_range=date_range,
            sync_trigger=SyncTrigger.MANUAL,
        )

        cache_key = query.cache_key
        assert "withings" in cache_key
        assert "test-user" in cache_key
        assert "heart_rate" in cache_key
        assert "20240115" in cache_key
        assert "20240116" in cache_key

    def test_cache_key_sorts_data_types(self):
        """Test that cache key sorts data types for consistency."""
        date_range = DateRange(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        query1 = HealthDataQuery(
            provider=Provider.WITHINGS,
            user_id="test-user",
            data_types=[HealthDataType.STEPS, HealthDataType.HEART_RATE],
            date_range=date_range,
            sync_trigger=SyncTrigger.MANUAL,
        )

        query2 = HealthDataQuery(
            provider=Provider.WITHINGS,
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE, HealthDataType.STEPS],
            date_range=date_range,
            sync_trigger=SyncTrigger.MANUAL,
        )

        # Same data types should produce same cache key
        assert query1.cache_key == query2.cache_key


class TestUnifiedHealthDataManager:
    """Tests for UnifiedHealthDataManager class."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.unified_health_data_manager.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "SUPPORTED_DATA_TYPES": {},
                "MAX_RETRIES": 3,
            }
            yield mock

    @pytest.fixture
    def mock_client(self):
        """Create mock unified health data client."""
        return MagicMock()

    @pytest.fixture
    def manager(self, mock_settings, mock_client):
        """Create manager instance."""
        with patch("ingestors.unified_health_data_manager.get_unified_health_data_client", return_value=mock_client):
            return UnifiedHealthDataManager()

    def test_initialization(self, manager, mock_client):
        """Test manager initialization."""
        assert manager.client == mock_client

    def test_fetch_health_data_empty_types(self, manager):
        """Test fetching with empty data types."""
        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        result = manager.fetch_health_data(
            provider=Provider.WITHINGS,
            user_id="test-user",
            data_types=[],
            date_range=date_range,
            sync_trigger=SyncTrigger.MANUAL,
        )

        assert result == []

    def test_fetch_health_data_success(self, manager, mock_client):
        """Test successful health data fetching."""
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                "value": 72,
                "device_id": "device-123",
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )

        result = manager.fetch_health_data(
            provider=Provider.WITHINGS,
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            date_range=date_range,
            sync_trigger=SyncTrigger.WEBHOOK,
        )

        assert len(result) == 1
        assert result[0].data_type == HealthDataType.HEART_RATE
        assert result[0].value == 72.0

    def test_fetch_multiple_queries_empty(self, manager):
        """Test fetching with empty query list."""
        result = manager.fetch_multiple_queries([])
        assert result == {}

    def test_fetch_multiple_queries_single(self, manager, mock_client):
        """Test fetching with single query."""
        mock_client.get_health_data.return_value = [
            {
                "timestamp": datetime(2024, 1, 15, tzinfo=UTC),
                "value": 65,
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )
        query = HealthDataQuery(
            provider=Provider.WITHINGS,
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            date_range=date_range,
            sync_trigger=SyncTrigger.MANUAL,
        )

        result = manager.fetch_multiple_queries([query])

        assert query.cache_key in result
        assert len(result[query.cache_key]) == 1

    def test_fetch_filters_unsupported_types(self, manager, mock_client):
        """Test that unsupported data types are filtered out."""
        mock_client.get_health_data.return_value = []

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )
        query = HealthDataQuery(
            provider=Provider.WITHINGS,
            user_id="test-user",
            # RR_INTERVALS is not in Withings defaults
            data_types=[HealthDataType.RR_INTERVALS],
            date_range=date_range,
            sync_trigger=SyncTrigger.MANUAL,
        )

        result = manager.fetch_multiple_queries([query])

        # Should return empty list for unsupported type
        assert result[query.cache_key] == []

    def test_fetch_handles_api_error(self, manager, mock_client):
        """Test handling of API errors."""
        mock_client.get_health_data.side_effect = Exception("API error")

        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )
        query = HealthDataQuery(
            provider=Provider.WITHINGS,
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            date_range=date_range,
            sync_trigger=SyncTrigger.MANUAL,
        )

        result = manager.fetch_multiple_queries([query])

        # Should return empty list on error
        assert result[query.cache_key] == []


class TestSupportedDataTypes:
    """Tests for _get_supported_data_types method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.unified_health_data_manager.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "SUPPORTED_DATA_TYPES": {},
            }
            yield mock

    @pytest.fixture
    def manager(self, mock_settings):
        """Create manager instance."""
        with patch("ingestors.unified_health_data_manager.get_unified_health_data_client"):
            return UnifiedHealthDataManager()

    def test_withings_default_types(self, manager):
        """Test default Withings supported types."""
        types = manager._get_supported_data_types(Provider.WITHINGS)

        assert HealthDataType.HEART_RATE in types
        assert HealthDataType.STEPS in types
        assert HealthDataType.WEIGHT in types
        assert HealthDataType.BLOOD_PRESSURE in types

    def test_fitbit_default_types(self, manager):
        """Test default Fitbit supported types."""
        types = manager._get_supported_data_types(Provider.FITBIT)

        assert HealthDataType.HEART_RATE in types
        assert HealthDataType.STEPS in types
        assert HealthDataType.WEIGHT in types
        assert HealthDataType.SLEEP in types
        assert HealthDataType.ECG in types
        assert HealthDataType.RR_INTERVALS in types

    def test_get_supported_data_types_public(self, manager):
        """Test public get_supported_data_types method."""
        types = manager.get_supported_data_types(Provider.WITHINGS)
        assert len(types) > 0


class TestTransformRawData:
    """Tests for _transform_raw_data_to_records method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.unified_health_data_manager.settings") as mock:
            mock.API_CLIENT_CONFIG = {"SUPPORTED_DATA_TYPES": {}}
            yield mock

    @pytest.fixture
    def manager(self, mock_settings):
        """Create manager instance."""
        with patch("ingestors.unified_health_data_manager.get_unified_health_data_client"):
            return UnifiedHealthDataManager()

    def test_transform_withings_heart_rate(self, manager):
        """Test transforming Withings heart rate data."""
        raw_data = [
            {
                "timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                "value": 72,
                "device_id": "device-123",
                "measurement_id": "meas-1",
                "category": 1,
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        records = manager._transform_raw_data_to_records(
            Provider.WITHINGS, HealthDataType.HEART_RATE, "test-user", raw_data
        )

        assert len(records) == 1
        assert records[0].provider == Provider.WITHINGS
        assert records[0].data_type == HealthDataType.HEART_RATE
        assert records[0].value == 72.0
        assert records[0].unit == "bpm"

    def test_transform_fitbit_steps(self, manager):
        """Test transforming Fitbit steps data."""
        raw_data = [
            {
                "date": datetime(2024, 1, 15, tzinfo=UTC),
                "steps": 10000,
                "device_id": "tracker-123",
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        records = manager._transform_raw_data_to_records(Provider.FITBIT, HealthDataType.STEPS, "test-user", raw_data)

        assert len(records) == 1
        assert records[0].provider == Provider.FITBIT
        assert records[0].data_type == HealthDataType.STEPS
        assert records[0].value == 10000.0
        assert records[0].unit == "steps"

    def test_transform_skips_invalid_items(self, manager):
        """Test that invalid items are skipped."""
        raw_data = [
            {"invalid": "data"},  # Missing timestamp/value
            {
                "timestamp": datetime(2024, 1, 15, tzinfo=UTC),
                "value": 72,
                "measurement_source": MeasurementSource.DEVICE,
            },
        ]

        records = manager._transform_raw_data_to_records(
            Provider.WITHINGS, HealthDataType.HEART_RATE, "test-user", raw_data
        )

        # Only valid items should be returned
        assert len(records) == 1

    def test_transform_handles_string_timestamp(self, manager):
        """Test handling of ISO string timestamps."""
        raw_data = [
            {
                "timestamp": "2024-01-15T10:00:00Z",
                "value": 72,
                "measurement_source": MeasurementSource.DEVICE,
            }
        ]

        records = manager._transform_raw_data_to_records(
            Provider.WITHINGS, HealthDataType.HEART_RATE, "test-user", raw_data
        )

        assert len(records) == 1


class TestCreateHealthRecords:
    """Tests for health record creation methods."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.unified_health_data_manager.settings") as mock:
            mock.API_CLIENT_CONFIG = {"SUPPORTED_DATA_TYPES": {}}
            yield mock

    @pytest.fixture
    def manager(self, mock_settings):
        """Create manager instance."""
        with patch("ingestors.unified_health_data_manager.get_unified_health_data_client"):
            return UnifiedHealthDataManager()

    def test_create_withings_record_missing_timestamp(self, manager):
        """Test Withings record with missing timestamp."""
        raw_item = {"value": 72}

        result = manager._create_withings_health_record(HealthDataType.HEART_RATE, "test-user", raw_item)

        assert result is None

    def test_create_withings_record_missing_value(self, manager):
        """Test Withings record with missing value."""
        raw_item = {"timestamp": datetime(2024, 1, 15, tzinfo=UTC)}

        result = manager._create_withings_health_record(HealthDataType.HEART_RATE, "test-user", raw_item)

        assert result is None

    def test_create_fitbit_record_missing_timestamp(self, manager):
        """Test Fitbit record with missing timestamp."""
        raw_item = {"value": 72}

        result = manager._create_fitbit_health_record(HealthDataType.HEART_RATE, "test-user", raw_item)

        assert result is None

    def test_create_fitbit_steps_from_steps_field(self, manager):
        """Test Fitbit steps using steps field."""
        raw_item = {
            "date": datetime(2024, 1, 15, tzinfo=UTC),
            "steps": 10000,
        }

        result = manager._create_fitbit_health_record(HealthDataType.STEPS, "test-user", raw_item)

        assert result is not None
        assert result.value == 10000.0

    def test_create_fitbit_sleep_metadata(self, manager):
        """Test Fitbit sleep record includes sleep metrics."""
        raw_item = {
            "timestamp": datetime(2024, 1, 15, tzinfo=UTC),
            "value": 420,
            "sleep_metrics": {"efficiency": 90},
        }

        result = manager._create_fitbit_health_record(HealthDataType.SLEEP, "test-user", raw_item)

        assert result is not None
        assert result.metadata["sleep_metrics"] == {"efficiency": 90}

    def test_create_fitbit_ecg_metadata(self, manager):
        """Test Fitbit ECG record includes ECG metrics."""
        raw_item = {
            "timestamp": datetime(2024, 1, 15, tzinfo=UTC),
            "value": 72,
            "ecg_metrics": {"rhythm": "normal"},
            "waveform_data": {"samples": [1, 2, 3]},
        }

        result = manager._create_fitbit_health_record(HealthDataType.ECG, "test-user", raw_item)

        assert result is not None
        assert result.metadata["ecg_metrics"] == {"rhythm": "normal"}
        assert result.metadata["waveform_data"] == {"samples": [1, 2, 3]}

    def test_create_fitbit_rr_intervals_metadata(self, manager):
        """Test Fitbit RR intervals record includes HRV metrics."""
        raw_item = {
            "timestamp": datetime(2024, 1, 15, tzinfo=UTC),
            "value": 45.5,
            "hrv_metrics": {"coverage": 0.95},
        }

        result = manager._create_fitbit_health_record(HealthDataType.RR_INTERVALS, "test-user", raw_item)

        assert result is not None
        assert result.metadata["hrv_metrics"] == {"coverage": 0.95}


class TestGetUnitForDataType:
    """Tests for _get_unit_for_data_type method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.unified_health_data_manager.settings") as mock:
            mock.API_CLIENT_CONFIG = {"SUPPORTED_DATA_TYPES": {}}
            yield mock

    @pytest.fixture
    def manager(self, mock_settings):
        """Create manager instance."""
        with patch("ingestors.unified_health_data_manager.get_unified_health_data_client"):
            return UnifiedHealthDataManager()

    def test_heart_rate_unit(self, manager):
        """Test heart rate unit."""
        assert manager._get_unit_for_data_type(HealthDataType.HEART_RATE) == "bpm"

    def test_steps_unit(self, manager):
        """Test steps unit."""
        assert manager._get_unit_for_data_type(HealthDataType.STEPS) == "steps"

    def test_weight_unit(self, manager):
        """Test weight unit."""
        assert manager._get_unit_for_data_type(HealthDataType.WEIGHT) == "kg"

    def test_blood_pressure_unit(self, manager):
        """Test blood pressure unit."""
        assert manager._get_unit_for_data_type(HealthDataType.BLOOD_PRESSURE) == "mmHg"

    def test_sleep_unit(self, manager):
        """Test sleep unit."""
        assert manager._get_unit_for_data_type(HealthDataType.SLEEP) == "minutes"

    def test_ecg_unit(self, manager):
        """Test ECG unit."""
        assert manager._get_unit_for_data_type(HealthDataType.ECG) == "bpm"

    def test_rr_intervals_unit(self, manager):
        """Test RR intervals unit."""
        assert manager._get_unit_for_data_type(HealthDataType.RR_INTERVALS) == "ms"

    def test_unknown_type_unit(self, manager):
        """Test unknown type returns 'unknown'."""
        # Create a mock data type not in mapping
        assert manager._get_unit_for_data_type(HealthDataType.TEMPERATURE) == "unknown"


class TestGetManagerStats:
    """Tests for get_manager_stats method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.unified_health_data_manager.settings") as mock:
            mock.API_CLIENT_CONFIG = {"SUPPORTED_DATA_TYPES": {}}
            yield mock

    @pytest.fixture
    def manager(self, mock_settings):
        """Create manager instance."""
        with patch("ingestors.unified_health_data_manager.get_unified_health_data_client"):
            return UnifiedHealthDataManager()

    def test_get_manager_stats(self, manager):
        """Test getting manager stats."""
        stats = manager.get_manager_stats()

        assert "supported_providers" in stats
        assert "withings" in stats["supported_providers"]
        assert "fitbit" in stats["supported_providers"]
        assert "supported_data_types" in stats
        assert "withings" in stats["supported_data_types"]
        assert "fitbit" in stats["supported_data_types"]


class TestProviderHealthDataManager:
    """Tests for ProviderHealthDataManager class."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.unified_health_data_manager.settings") as mock:
            mock.API_CLIENT_CONFIG = {"SUPPORTED_DATA_TYPES": {}}
            yield mock

    @pytest.fixture
    def mock_unified_manager(self):
        """Create mock unified manager."""
        return MagicMock()

    def test_initialization(self, mock_settings, mock_unified_manager):
        """Test provider manager initialization."""
        with patch(
            "ingestors.unified_health_data_manager.get_unified_health_data_manager",
            return_value=mock_unified_manager,
        ):
            manager = ProviderHealthDataManager(Provider.WITHINGS)

            assert manager.provider == Provider.WITHINGS
            assert manager.unified_manager == mock_unified_manager

    def test_get_supported_data_types(self, mock_settings, mock_unified_manager):
        """Test getting supported data types."""
        mock_unified_manager.get_supported_data_types.return_value = [
            HealthDataType.HEART_RATE,
            HealthDataType.STEPS,
        ]

        with patch(
            "ingestors.unified_health_data_manager.get_unified_health_data_manager",
            return_value=mock_unified_manager,
        ):
            manager = ProviderHealthDataManager(Provider.WITHINGS)
            types = manager.get_supported_data_types()

            assert len(types) == 2
            mock_unified_manager.get_supported_data_types.assert_called_once_with(Provider.WITHINGS)

    def test_fetch_health_data(self, mock_settings, mock_unified_manager):
        """Test fetching health data delegates to unified manager."""
        mock_unified_manager.fetch_health_data.return_value = []

        with patch(
            "ingestors.unified_health_data_manager.get_unified_health_data_manager",
            return_value=mock_unified_manager,
        ):
            manager = ProviderHealthDataManager(Provider.WITHINGS)
            date_range = DateRange(
                start=datetime(2024, 1, 15, tzinfo=UTC),
                end=datetime(2024, 1, 16, tzinfo=UTC),
            )

            manager.fetch_health_data(
                user_id="test-user",
                data_types=[HealthDataType.HEART_RATE],
                date_range=date_range,
                sync_trigger=SyncTrigger.MANUAL,
            )

            mock_unified_manager.fetch_health_data.assert_called_once()


class TestHealthDataManagerFactory:
    """Tests for HealthDataManagerFactory class."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.unified_health_data_manager.settings") as mock:
            mock.API_CLIENT_CONFIG = {"SUPPORTED_DATA_TYPES": {}}
            yield mock

    def test_get_manager_withings(self, mock_settings):
        """Test getting Withings manager."""
        with patch("ingestors.unified_health_data_manager.get_unified_health_data_manager"):
            manager = HealthDataManagerFactory.get_manager(Provider.WITHINGS)

            assert isinstance(manager, ProviderHealthDataManager)
            assert manager.provider == Provider.WITHINGS

    def test_get_manager_fitbit(self, mock_settings):
        """Test getting Fitbit manager."""
        with patch("ingestors.unified_health_data_manager.get_unified_health_data_manager"):
            manager = HealthDataManagerFactory.get_manager(Provider.FITBIT)

            assert isinstance(manager, ProviderHealthDataManager)
            assert manager.provider == Provider.FITBIT

    def test_get_supported_providers(self):
        """Test getting supported providers."""
        providers = HealthDataManagerFactory.get_supported_providers()

        assert Provider.WITHINGS in providers
        assert Provider.FITBIT in providers


class TestGlobalFunction:
    """Tests for global singleton function."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.unified_health_data_manager.settings") as mock:
            mock.API_CLIENT_CONFIG = {"SUPPORTED_DATA_TYPES": {}}
            yield mock

    def test_get_unified_health_data_manager_singleton(self, mock_settings):
        """Test that get_unified_health_data_manager returns singleton."""
        import ingestors.unified_health_data_manager as module

        module._unified_manager = None

        with patch.object(module, "get_unified_health_data_client"):
            manager1 = get_unified_health_data_manager()
            manager2 = get_unified_health_data_manager()

            assert manager1 is manager2
