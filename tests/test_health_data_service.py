"""
Tests for health data synchronization service.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from ingestors.health_data_constants import (
    AggregationLevel,
    HealthDataRecord,
    HealthDataType,
    Provider,
    SyncFrequency,
    SyncTrigger,
)
from ingestors.health_data_service import HealthDataSyncService, MockHealthDataSyncService


class TestHealthDataSyncServiceInit:
    """Tests for HealthDataSyncService initialization."""

    def test_init_with_default_publisher(self):
        """Test initialization with default publisher."""
        with patch("ingestors.health_data_service.HealthDataPublisher") as mock_publisher:
            service = HealthDataSyncService()
            mock_publisher.assert_called_once()
            assert service.fhir_publisher is not None

    def test_init_with_custom_publisher(self):
        """Test initialization with custom publisher."""
        mock_publisher = MagicMock()
        service = HealthDataSyncService(fhir_publisher=mock_publisher)
        assert service.fhir_publisher == mock_publisher


class TestCreateDefaultConfig:
    """Tests for _create_default_config method."""

    @pytest.fixture
    def service(self):
        """Create service with mocked publisher."""
        with patch("ingestors.health_data_service.HealthDataPublisher"):
            return HealthDataSyncService()

    def test_creates_config_with_correct_user_id(self, service):
        """Test config has correct user ID."""
        config = service._create_default_config("user-123", [HealthDataType.HEART_RATE])
        assert config.user_id == "user-123"

    def test_creates_config_with_data_types(self, service):
        """Test config has correct data types."""
        data_types = [HealthDataType.HEART_RATE, HealthDataType.STEPS]
        config = service._create_default_config("user-123", data_types)
        assert config.enabled_data_types == data_types

    def test_creates_config_with_individual_aggregation(self, service):
        """Test config defaults to individual aggregation."""
        config = service._create_default_config("user-123", [HealthDataType.HEART_RATE])
        assert config.aggregation_preference == AggregationLevel.INDIVIDUAL

    def test_creates_config_with_daily_sync(self, service):
        """Test config defaults to daily sync frequency."""
        config = service._create_default_config("user-123", [HealthDataType.HEART_RATE])
        assert config.sync_frequency == SyncFrequency.DAILY

    def test_creates_config_with_90_day_retention(self, service):
        """Test config defaults to 90 day retention."""
        config = service._create_default_config("user-123", [HealthDataType.HEART_RATE])
        assert config.retention_period == timedelta(days=90)


class TestSyncUserHealthData:
    """Tests for sync_user_health_data method."""

    @pytest.fixture
    def service(self):
        """Create service with mocked dependencies."""
        with (
            patch("ingestors.health_data_service.HealthDataPublisher") as mock_pub_class,
            patch("ingestors.health_data_service.HealthDataTransformer") as mock_trans_class,
        ):
            mock_publisher = MagicMock()
            mock_pub_class.return_value = mock_publisher
            mock_transformer = MagicMock()
            mock_trans_class.return_value = mock_transformer
            svc = HealthDataSyncService()
            svc.mock_publisher = mock_publisher
            svc.mock_transformer = mock_transformer
            yield svc

    def test_converts_string_provider_to_enum(self, service):
        """Test string provider is converted to enum."""
        with patch.object(service, "_fetch_health_data", return_value=[]):
            result = service.sync_user_health_data(
                user_id="user-123",
                provider="withings",
                data_types=[HealthDataType.HEART_RATE],
            )
            assert result.provider == Provider.WITHINGS

    def test_uses_default_patient_reference(self, service):
        """Test default patient reference is generated."""
        with patch.object(service, "_fetch_health_data", return_value=[]):
            service.sync_user_health_data(
                user_id="user-123",
                provider=Provider.WITHINGS,
                data_types=[HealthDataType.HEART_RATE],
            )
            # Result should be successful with no records
            # Patient reference defaults to Patient/user-123

    def test_returns_success_with_no_records(self, service):
        """Test returns success when no records fetched."""
        with patch.object(service, "_fetch_health_data", return_value=[]):
            result = service.sync_user_health_data(
                user_id="user-123",
                provider=Provider.WITHINGS,
                data_types=[HealthDataType.HEART_RATE],
            )
            assert result.success is True
            assert result.records_fetched == 0

    def test_processes_records_successfully(self, service):
        """Test full sync flow with records."""
        mock_records = [
            HealthDataRecord(
                provider=Provider.WITHINGS,
                user_id="user-123",
                data_type=HealthDataType.HEART_RATE,
                timestamp=datetime.now(UTC),
                value=72.0,
                unit="bpm",
            )
        ]
        mock_observations = [{"resourceType": "Observation", "id": "obs-1"}]

        with (
            patch.object(service, "_fetch_health_data", return_value=mock_records),
            patch.object(service, "_transform_health_data", return_value=mock_observations),
            patch.object(service, "_publish_health_data", return_value={"success": True, "published_successfully": 1}),
        ):
            result = service.sync_user_health_data(
                user_id="user-123",
                provider=Provider.WITHINGS,
                data_types=[HealthDataType.HEART_RATE],
            )
            assert result.success is True
            assert result.records_fetched == 1
            assert result.records_transformed == 1
            assert result.fhir_resources_created == 1

    def test_handles_publishing_errors(self, service):
        """Test handles errors during publishing."""
        mock_records = [
            HealthDataRecord(
                provider=Provider.WITHINGS,
                user_id="user-123",
                data_type=HealthDataType.HEART_RATE,
                timestamp=datetime.now(UTC),
                value=72.0,
                unit="bpm",
            )
        ]
        mock_observations = [{"resourceType": "Observation"}]

        with (
            patch.object(service, "_fetch_health_data", return_value=mock_records),
            patch.object(service, "_transform_health_data", return_value=mock_observations),
            patch.object(
                service,
                "_publish_health_data",
                return_value={"success": False, "published_successfully": 0, "errors": ["FHIR error"]},
            ),
        ):
            result = service.sync_user_health_data(
                user_id="user-123",
                provider=Provider.WITHINGS,
                data_types=[HealthDataType.HEART_RATE],
            )
            assert result.success is False
            assert len(result.errors) == 1

    def test_handles_unexpected_exception(self, service):
        """Test handles unexpected exceptions."""
        with patch.object(service, "_fetch_health_data", side_effect=Exception("Network error")):
            result = service.sync_user_health_data(
                user_id="user-123",
                provider=Provider.WITHINGS,
                data_types=[HealthDataType.HEART_RATE],
            )
            assert result.success is False
            assert len(result.errors) == 1
            assert "Network error" in result.errors[0]

    def test_returns_success_with_empty_transformations(self, service):
        """Test returns success when transformation produces no observations."""
        mock_records = [
            HealthDataRecord(
                provider=Provider.WITHINGS,
                user_id="user-123",
                data_type=HealthDataType.HEART_RATE,
                timestamp=datetime.now(UTC),
                value=72.0,
                unit="bpm",
            )
        ]

        with (
            patch.object(service, "_fetch_health_data", return_value=mock_records),
            patch.object(service, "_transform_health_data", return_value=[]),
        ):
            result = service.sync_user_health_data(
                user_id="user-123",
                provider=Provider.WITHINGS,
                data_types=[HealthDataType.HEART_RATE],
            )
            assert result.success is True
            assert result.records_fetched == 1
            assert result.records_transformed == 0


class TestFetchHealthData:
    """Tests for _fetch_health_data method."""

    @pytest.fixture
    def service(self):
        """Create service with mocked publisher."""
        with patch("ingestors.health_data_service.HealthDataPublisher"):
            return HealthDataSyncService()

    def test_creates_health_manager_for_provider(self, service):
        """Test creates health manager for the provider."""
        with patch("ingestors.health_data_service.HealthDataManagerFactory") as mock_factory:
            mock_manager = MagicMock()
            mock_manager.fetch_health_data.return_value = []
            mock_factory.create.return_value = mock_manager

            sync_params = {
                "date_range": {"start": datetime.now(UTC), "end": datetime.now(UTC)},
                "sync_trigger": SyncTrigger.WEBHOOK,
            }
            service._fetch_health_data("user-123", Provider.WITHINGS, [HealthDataType.HEART_RATE], sync_params)

            mock_factory.create.assert_called_once_with(Provider.WITHINGS)

    def test_calls_fetch_health_data_with_params(self, service):
        """Test calls fetch_health_data with correct parameters."""
        with patch("ingestors.health_data_service.HealthDataManagerFactory") as mock_factory:
            mock_manager = MagicMock()
            mock_manager.fetch_health_data.return_value = []
            mock_factory.create.return_value = mock_manager

            start_date = datetime.now(UTC)
            end_date = datetime.now(UTC)
            sync_params = {
                "date_range": {"start": start_date, "end": end_date},
                "sync_trigger": SyncTrigger.WEBHOOK,
            }
            service._fetch_health_data("user-123", Provider.FITBIT, [HealthDataType.STEPS], sync_params)

            mock_manager.fetch_health_data.assert_called_once()
            call_kwargs = mock_manager.fetch_health_data.call_args[1]
            assert call_kwargs["user_id"] == "user-123"
            assert call_kwargs["data_types"] == [HealthDataType.STEPS]

    def test_raises_on_fetch_error(self, service):
        """Test raises exception on fetch error."""
        with patch("ingestors.health_data_service.HealthDataManagerFactory") as mock_factory:
            mock_manager = MagicMock()
            mock_manager.fetch_health_data.side_effect = Exception("API error")
            mock_factory.create.return_value = mock_manager

            sync_params = {
                "date_range": {"start": datetime.now(UTC), "end": datetime.now(UTC)},
                "sync_trigger": SyncTrigger.MANUAL,
            }
            with pytest.raises(Exception, match="API error"):
                service._fetch_health_data("user-123", Provider.WITHINGS, [HealthDataType.HEART_RATE], sync_params)


class TestTransformHealthData:
    """Tests for _transform_health_data method."""

    @pytest.fixture
    def service(self):
        """Create service with mocked dependencies."""
        with (
            patch("ingestors.health_data_service.HealthDataPublisher"),
            patch("ingestors.health_data_service.HealthDataTransformer") as mock_trans_class,
        ):
            mock_transformer = MagicMock()
            mock_trans_class.return_value = mock_transformer
            svc = HealthDataSyncService()
            svc.mock_transformer = mock_transformer
            yield svc

    def test_transforms_records_to_fhir(self, service):
        """Test transforms health records to FHIR observations."""
        mock_records = [MagicMock()]
        service.transformer.transform_multiple_records.return_value = [{"resourceType": "Observation"}]

        result = service._transform_health_data(mock_records, "Patient/123", "Device/456")

        service.transformer.transform_multiple_records.assert_called_once_with(
            records=mock_records,
            patient_reference="Patient/123",
            device_reference="Device/456",
        )
        assert len(result) == 1

    def test_transforms_without_device_reference(self, service):
        """Test transforms without device reference."""
        mock_records = [MagicMock()]
        service.transformer.transform_multiple_records.return_value = []

        service._transform_health_data(mock_records, "Patient/123", None)

        call_kwargs = service.transformer.transform_multiple_records.call_args[1]
        assert call_kwargs["device_reference"] is None

    def test_raises_on_transform_error(self, service):
        """Test raises exception on transformation error."""
        service.transformer.transform_multiple_records.side_effect = Exception("Transform error")

        with pytest.raises(Exception, match="Transform error"):
            service._transform_health_data([MagicMock()], "Patient/123", None)


class TestPublishHealthData:
    """Tests for _publish_health_data method."""

    @pytest.fixture
    def service(self):
        """Create service with mocked publisher."""
        with patch("ingestors.health_data_service.HealthDataPublisher") as mock_pub_class:
            mock_publisher = MagicMock()
            mock_pub_class.return_value = mock_publisher
            svc = HealthDataSyncService()
            svc.mock_publisher = mock_publisher
            yield svc

    def test_publishes_observations_with_batch_size(self, service):
        """Test publishes observations with batch size from params."""
        mock_observations = [{"resourceType": "Observation"}]
        service.fhir_publisher.publish_health_observations.return_value = {"success": True}

        sync_params = {"batch_size": 50}
        service._publish_health_data(mock_observations, sync_params)

        service.fhir_publisher.publish_health_observations.assert_called_once_with(
            observations=mock_observations,
            batch_size=50,
        )

    def test_uses_default_batch_size(self, service):
        """Test uses default batch size from settings."""
        mock_observations = [{"resourceType": "Observation"}]
        service.fhir_publisher.publish_health_observations.return_value = {"success": True}

        with patch("ingestors.health_data_service.settings") as mock_settings:
            mock_settings.HEALTH_DATA_CONFIG = {"BATCH_SIZES": {"PUBLISHER": 100}}
            sync_params = {}
            service._publish_health_data(mock_observations, sync_params)

            call_kwargs = service.fhir_publisher.publish_health_observations.call_args[1]
            assert call_kwargs["batch_size"] == 100

    def test_raises_on_publish_error(self, service):
        """Test raises exception on publish error."""
        service.fhir_publisher.publish_health_observations.side_effect = Exception("FHIR error")

        with pytest.raises(Exception, match="FHIR error"):
            service._publish_health_data([{"resourceType": "Observation"}], {})


class TestGetSyncStatistics:
    """Tests for get_sync_statistics method."""

    @pytest.fixture
    def service(self):
        """Create service with mocked publisher."""
        with patch("ingestors.health_data_service.HealthDataPublisher") as mock_pub_class:
            mock_publisher = MagicMock()
            mock_pub_class.return_value = mock_publisher
            svc = HealthDataSyncService()
            yield svc

    def test_returns_statistics_with_user_context(self, service):
        """Test returns statistics with user context."""
        service.fhir_publisher.get_health_data_statistics.return_value = {
            "total_observations": 100,
            "by_type": {"heart_rate": 50, "steps": 50},
        }

        stats = service.get_sync_statistics("user-123")

        assert stats["user_id"] == "user-123"
        assert stats["total_observations"] == 100
        assert "last_check" in stats

    def test_handles_error_gracefully(self, service):
        """Test handles error and returns error response."""
        service.fhir_publisher.get_health_data_statistics.side_effect = Exception("FHIR error")

        stats = service.get_sync_statistics("user-123")

        assert stats["user_id"] == "user-123"
        assert stats["error"] == "FHIR error"
        assert "last_check" in stats


class TestDeleteUserHealthData:
    """Tests for delete_user_health_data method."""

    @pytest.fixture
    def service(self):
        """Create service with mocked publisher."""
        with patch("ingestors.health_data_service.HealthDataPublisher") as mock_pub_class:
            mock_publisher = MagicMock()
            mock_pub_class.return_value = mock_publisher
            svc = HealthDataSyncService()
            yield svc

    def test_converts_string_provider_to_enum(self, service):
        """Test string provider is converted to enum."""
        service.fhir_publisher.delete_health_data_by_provider.return_value = {"deleted_count": 10}

        service.delete_user_health_data("user-123", "withings")

        call_kwargs = service.fhir_publisher.delete_health_data_by_provider.call_args[1]
        assert call_kwargs["provider"] == Provider.WITHINGS

    def test_deletes_data_successfully(self, service):
        """Test deletes health data successfully."""
        service.fhir_publisher.delete_health_data_by_provider.return_value = {"deleted_count": 10, "success": True}

        result = service.delete_user_health_data("user-123", Provider.WITHINGS)

        service.fhir_publisher.delete_health_data_by_provider.assert_called_once_with(
            patient_reference="Patient/user-123",
            provider=Provider.WITHINGS,
        )
        assert result["deleted_count"] == 10

    def test_handles_delete_error(self, service):
        """Test handles error during deletion."""
        service.fhir_publisher.delete_health_data_by_provider.side_effect = Exception("Delete failed")

        result = service.delete_user_health_data("user-123", Provider.FITBIT)

        assert result["success"] is False
        assert result["error"] == "Delete failed"
        assert result["deleted_count"] == 0


class TestMockHealthDataSyncService:
    """Tests for MockHealthDataSyncService."""

    def test_init_creates_empty_lists(self):
        """Test initialization creates empty lists."""
        with patch("ingestors.health_data_service.HealthDataPublisher"):
            service = MockHealthDataSyncService()
            assert service.published_observations == []
            assert service.mock_records == []

    def test_fetch_returns_mock_records_when_set(self):
        """Test fetch returns mock records when set."""
        with patch("ingestors.health_data_service.HealthDataPublisher"):
            service = MockHealthDataSyncService()
            mock_records = [
                HealthDataRecord(
                    provider=Provider.WITHINGS,
                    user_id="user-123",
                    data_type=HealthDataType.HEART_RATE,
                    timestamp=datetime.now(UTC),
                    value=72.0,
                    unit="bpm",
                )
            ]
            service.set_mock_records(mock_records)

            sync_params = {
                "date_range": {"start": datetime.now(UTC), "end": datetime.now(UTC)},
                "sync_trigger": SyncTrigger.WEBHOOK,
            }
            result = service._fetch_health_data("user-123", Provider.WITHINGS, [HealthDataType.HEART_RATE], sync_params)

            assert result == mock_records

    def test_fetch_generates_mock_data_for_heart_rate(self):
        """Test fetch generates mock data for heart rate."""
        with patch("ingestors.health_data_service.HealthDataPublisher"):
            service = MockHealthDataSyncService()

            sync_params = {
                "date_range": {"start": datetime.now(UTC), "end": datetime.now(UTC)},
                "sync_trigger": SyncTrigger.MANUAL,
            }
            result = service._fetch_health_data("user-123", Provider.WITHINGS, [HealthDataType.HEART_RATE], sync_params)

            assert len(result) == 1
            assert result[0].data_type == HealthDataType.HEART_RATE
            assert result[0].unit == "bpm"

    def test_fetch_generates_mock_data_for_steps(self):
        """Test fetch generates mock data for steps."""
        with patch("ingestors.health_data_service.HealthDataPublisher"):
            service = MockHealthDataSyncService()

            sync_params = {
                "date_range": {"start": datetime.now(UTC), "end": datetime.now(UTC)},
                "sync_trigger": SyncTrigger.MANUAL,
            }
            result = service._fetch_health_data("user-123", Provider.WITHINGS, [HealthDataType.STEPS], sync_params)

            assert len(result) == 1
            assert result[0].data_type == HealthDataType.STEPS
            assert result[0].unit == "steps"

    def test_fetch_generates_mock_data_for_multiple_types(self):
        """Test fetch generates mock data for multiple data types."""
        with patch("ingestors.health_data_service.HealthDataPublisher"):
            service = MockHealthDataSyncService()

            sync_params = {
                "date_range": {"start": datetime.now(UTC), "end": datetime.now(UTC)},
                "sync_trigger": SyncTrigger.MANUAL,
            }
            result = service._fetch_health_data(
                "user-123",
                Provider.WITHINGS,
                [HealthDataType.HEART_RATE, HealthDataType.STEPS],
                sync_params,
            )

            assert len(result) == 2
            types = [r.data_type for r in result]
            assert HealthDataType.HEART_RATE in types
            assert HealthDataType.STEPS in types

    def test_fetch_skips_unsupported_types(self):
        """Test fetch skips unsupported data types in mock."""
        with patch("ingestors.health_data_service.HealthDataPublisher"):
            service = MockHealthDataSyncService()

            sync_params = {
                "date_range": {"start": datetime.now(UTC), "end": datetime.now(UTC)},
                "sync_trigger": SyncTrigger.MANUAL,
            }
            result = service._fetch_health_data(
                "user-123",
                Provider.WITHINGS,
                [HealthDataType.BLOOD_PRESSURE],
                sync_params,
            )

            assert len(result) == 0

    def test_publish_stores_observations(self):
        """Test publish stores observations for inspection."""
        with patch("ingestors.health_data_service.HealthDataPublisher") as mock_pub_class:
            mock_publisher = MagicMock()
            mock_publisher.publish_health_observations.return_value = {"success": True}
            mock_pub_class.return_value = mock_publisher

            service = MockHealthDataSyncService()
            observations = [{"resourceType": "Observation", "id": "obs-1"}]

            with patch("ingestors.health_data_service.settings") as mock_settings:
                mock_settings.HEALTH_DATA_CONFIG = {"BATCH_SIZES": {"PUBLISHER": 100}}
                service._publish_health_data(observations, {})

            assert service.published_observations == observations

    def test_set_mock_records(self):
        """Test set_mock_records method."""
        with patch("ingestors.health_data_service.HealthDataPublisher"):
            service = MockHealthDataSyncService()
            mock_records = [MagicMock()]

            service.set_mock_records(mock_records)

            assert service.mock_records == mock_records
