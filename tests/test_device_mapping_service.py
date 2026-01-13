"""
Tests for device mapping service.
"""

from unittest.mock import MagicMock, patch

import pytest

from ingestors.constants import Provider
from ingestors.device_mapping_service import (
    DeviceMappingService,
    DeviceQuery,
    bulk_map_devices,
    get_device_mapping_service,
    get_fhir_device_reference,
)


class TestDeviceQuery:
    """Tests for DeviceQuery dataclass."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.device_mapping_service.settings") as mock:
            mock.DEVICE_MAPPING = {
                "CACHE_PREFIX": "device_map",
                "CACHE_TTL": 3600,
                "NEGATIVE_CACHE_TTL": 600,
                "BATCH_SIZE": 100,
                "IDENTIFIER_SYSTEMS": {
                    "withings": "https://api.withings.com/device-id",
                    "fitbit": "https://api.fitbit.com/device-id",
                },
            }
            yield mock

    def test_device_query_creation(self, mock_settings):
        """Test creating a DeviceQuery."""
        query = DeviceQuery(provider=Provider.WITHINGS, device_id="device-123")

        assert query.provider == Provider.WITHINGS
        assert query.device_id == "device-123"

    def test_device_query_cache_key(self, mock_settings):
        """Test cache key generation."""
        query = DeviceQuery(provider=Provider.WITHINGS, device_id="device-123")

        cache_key = query.cache_key
        assert cache_key == "device_map:withings:device-123"

    def test_device_query_cache_key_fitbit(self, mock_settings):
        """Test cache key for Fitbit provider."""
        query = DeviceQuery(provider=Provider.FITBIT, device_id="tracker-456")

        cache_key = query.cache_key
        assert cache_key == "device_map:fitbit:tracker-456"

    def test_device_query_is_frozen(self, mock_settings):
        """Test that DeviceQuery is immutable."""
        query = DeviceQuery(provider=Provider.WITHINGS, device_id="device-123")

        with pytest.raises(Exception):  # FrozenInstanceError
            query.device_id = "new-id"


class TestDeviceMappingService:
    """Tests for DeviceMappingService class."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.device_mapping_service.settings") as mock:
            mock.DEVICE_MAPPING = {
                "CACHE_PREFIX": "device_map",
                "CACHE_TTL": 3600,
                "NEGATIVE_CACHE_TTL": 600,
                "BATCH_SIZE": 100,
                "IDENTIFIER_SYSTEMS": {
                    "withings": "https://api.withings.com/device-id",
                    "fitbit": "https://api.fitbit.com/device-id",
                },
            }
            yield mock

    @pytest.fixture
    def mock_fhir_client(self):
        """Create mock FHIR client."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_settings, mock_fhir_client):
        """Create service instance."""
        return DeviceMappingService(fhir_client=mock_fhir_client)

    def test_initialization(self, service):
        """Test service initialization."""
        assert service.fhir_client is not None
        assert service.config is not None

    def test_get_fhir_device_reference_empty_id(self, service):
        """Test getting reference with empty device ID."""
        result = service.get_fhir_device_reference(Provider.WITHINGS, "")
        assert result is None

    def test_get_fhir_device_reference_none_id(self, service):
        """Test getting reference with None device ID."""
        result = service.get_fhir_device_reference(Provider.WITHINGS, None)
        assert result is None

    def test_get_fhir_device_reference_cache_hit(self, service, mock_fhir_client):
        """Test getting reference with cache hit."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.return_value = {"device_map:withings:device-123": "Device/uuid-123"}

            result = service.get_fhir_device_reference(Provider.WITHINGS, "device-123")

            assert result == "Device/uuid-123"
            mock_fhir_client.search_resource.assert_not_called()

    def test_get_fhir_device_reference_cache_miss_fhir_found(self, service, mock_fhir_client):
        """Test getting reference with cache miss but FHIR found."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.return_value = {}
            mock_fhir_client.search_resource.return_value = {"entry": [{"resource": {"id": "uuid-456"}}]}

            result = service.get_fhir_device_reference(Provider.WITHINGS, "device-123")

            assert result == "Device/uuid-456"
            mock_cache.set_many.assert_called()

    def test_get_fhir_device_reference_cache_miss_fhir_not_found(self, service, mock_fhir_client):
        """Test getting reference with cache miss and FHIR not found."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.return_value = {}
            mock_fhir_client.search_resource.return_value = {"entry": []}

            result = service.get_fhir_device_reference(Provider.WITHINGS, "device-123")

            assert result is None

    def test_bulk_map_devices_empty_list(self, service):
        """Test bulk mapping with empty list."""
        result = service.bulk_map_devices(Provider.WITHINGS, [])
        assert result == {}

    def test_bulk_map_devices_with_empty_strings(self, service, mock_fhir_client):
        """Test bulk mapping filters out empty strings."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.return_value = {"device_map:withings:device-1": "Device/uuid-1"}

            result = service.bulk_map_devices(Provider.WITHINGS, ["device-1", "", None])

            # Should only process device-1
            assert "device-1" in result

    def test_bulk_map_devices_multiple(self, service, mock_fhir_client):
        """Test bulk mapping multiple devices."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.return_value = {
                "device_map:withings:device-1": "Device/uuid-1",
                "device_map:withings:device-2": "Device/uuid-2",
            }

            result = service.bulk_map_devices(Provider.WITHINGS, ["device-1", "device-2"])

            assert result["device-1"] == "Device/uuid-1"
            assert result["device-2"] == "Device/uuid-2"

    def test_get_device_references_empty_queries(self, service):
        """Test getting references with empty query list."""
        result = service.get_device_references([])
        assert result == {}

    def test_get_device_references_exception_handling(self, service, mock_fhir_client):
        """Test exception handling returns empty results."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.side_effect = Exception("Cache error")

            queries = [DeviceQuery(Provider.WITHINGS, "device-1")]
            result = service.get_device_references(queries)

            # Should return None for all queries on error
            assert result["device-1"] is None


class TestBatchCacheLookup:
    """Tests for _batch_cache_lookup method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.device_mapping_service.settings") as mock:
            mock.DEVICE_MAPPING = {
                "CACHE_PREFIX": "device_map",
                "CACHE_TTL": 3600,
                "NEGATIVE_CACHE_TTL": 600,
                "BATCH_SIZE": 100,
                "IDENTIFIER_SYSTEMS": {
                    "withings": "https://api.withings.com/device-id",
                    "fitbit": "https://api.fitbit.com/device-id",
                },
            }
            yield mock

    @pytest.fixture
    def service(self, mock_settings):
        """Create service instance."""
        mock_client = MagicMock()
        return DeviceMappingService(fhir_client=mock_client)

    def test_batch_cache_lookup_all_hits(self, service):
        """Test cache lookup when all queries are hits."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.return_value = {
                "device_map:withings:device-1": "Device/uuid-1",
                "device_map:withings:device-2": "Device/uuid-2",
            }

            queries = [
                DeviceQuery(Provider.WITHINGS, "device-1"),
                DeviceQuery(Provider.WITHINGS, "device-2"),
            ]
            results, uncached = service._batch_cache_lookup(queries)

            assert len(results) == 2
            assert len(uncached) == 0

    def test_batch_cache_lookup_partial_hits(self, service):
        """Test cache lookup with partial hits."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.return_value = {
                "device_map:withings:device-1": "Device/uuid-1",
            }

            queries = [
                DeviceQuery(Provider.WITHINGS, "device-1"),
                DeviceQuery(Provider.WITHINGS, "device-2"),
            ]
            results, uncached = service._batch_cache_lookup(queries)

            assert len(results) == 1
            assert len(uncached) == 1
            assert uncached[0].device_id == "device-2"

    def test_batch_cache_lookup_all_misses(self, service):
        """Test cache lookup when all queries are misses."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.return_value = {}

            queries = [
                DeviceQuery(Provider.WITHINGS, "device-1"),
                DeviceQuery(Provider.WITHINGS, "device-2"),
            ]
            results, uncached = service._batch_cache_lookup(queries)

            assert len(results) == 0
            assert len(uncached) == 2

    def test_batch_cache_lookup_ignores_not_found_marker(self, service):
        """Test that NOT_FOUND marker is treated as cache miss."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.return_value = {
                "device_map:withings:device-1": "NOT_FOUND",
            }

            queries = [DeviceQuery(Provider.WITHINGS, "device-1")]
            results, uncached = service._batch_cache_lookup(queries)

            assert len(results) == 0
            assert len(uncached) == 1

    def test_batch_cache_lookup_cache_failure(self, service):
        """Test cache failure returns all queries as uncached."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.get_many.side_effect = Exception("Cache error")

            queries = [
                DeviceQuery(Provider.WITHINGS, "device-1"),
                DeviceQuery(Provider.WITHINGS, "device-2"),
            ]
            results, uncached = service._batch_cache_lookup(queries)

            assert len(results) == 0
            assert len(uncached) == 2


class TestBatchFHIRSearch:
    """Tests for _batch_fhir_search method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.device_mapping_service.settings") as mock:
            mock.DEVICE_MAPPING = {
                "CACHE_PREFIX": "device_map",
                "CACHE_TTL": 3600,
                "NEGATIVE_CACHE_TTL": 600,
                "BATCH_SIZE": 100,
                "IDENTIFIER_SYSTEMS": {
                    "withings": "https://api.withings.com/device-id",
                    "fitbit": "https://api.fitbit.com/device-id",
                },
            }
            yield mock

    @pytest.fixture
    def mock_fhir_client(self):
        """Create mock FHIR client."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_settings, mock_fhir_client):
        """Create service instance."""
        return DeviceMappingService(fhir_client=mock_fhir_client)

    def test_batch_fhir_search_found(self, service, mock_fhir_client):
        """Test FHIR search finds device."""
        mock_fhir_client.search_resource.return_value = {"entry": [{"resource": {"id": "uuid-123"}}]}

        queries = [DeviceQuery(Provider.WITHINGS, "device-1")]
        results = service._batch_fhir_search(queries)

        assert results["device-1"] == "Device/uuid-123"

    def test_batch_fhir_search_not_found(self, service, mock_fhir_client):
        """Test FHIR search when device not found."""
        mock_fhir_client.search_resource.return_value = {"entry": []}

        queries = [DeviceQuery(Provider.WITHINGS, "device-1")]
        results = service._batch_fhir_search(queries)

        assert results["device-1"] is None

    def test_batch_fhir_search_multiple_providers(self, service, mock_fhir_client):
        """Test FHIR search with multiple providers."""
        mock_fhir_client.search_resource.side_effect = [
            {"entry": [{"resource": {"id": "withings-uuid"}}]},
            {"entry": [{"resource": {"id": "fitbit-uuid"}}]},
        ]

        queries = [
            DeviceQuery(Provider.WITHINGS, "withings-device"),
            DeviceQuery(Provider.FITBIT, "fitbit-device"),
        ]
        results = service._batch_fhir_search(queries)

        assert results["withings-device"] == "Device/withings-uuid"
        assert results["fitbit-device"] == "Device/fitbit-uuid"

    def test_batch_fhir_search_error_handling(self, service, mock_fhir_client):
        """Test FHIR search error handling."""
        mock_fhir_client.search_resource.side_effect = Exception("FHIR error")

        queries = [DeviceQuery(Provider.WITHINGS, "device-1")]
        results = service._batch_fhir_search(queries)

        assert results["device-1"] is None


class TestBatchCacheStore:
    """Tests for _batch_cache_store method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.device_mapping_service.settings") as mock:
            mock.DEVICE_MAPPING = {
                "CACHE_PREFIX": "device_map",
                "CACHE_TTL": 3600,
                "NEGATIVE_CACHE_TTL": 600,
                "BATCH_SIZE": 100,
                "IDENTIFIER_SYSTEMS": {},
            }
            yield mock

    @pytest.fixture
    def service(self, mock_settings):
        """Create service instance."""
        mock_client = MagicMock()
        return DeviceMappingService(fhir_client=mock_client)

    def test_batch_cache_store_positive_results(self, service):
        """Test caching positive results."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            queries = [DeviceQuery(Provider.WITHINGS, "device-1")]
            results = {"device-1": "Device/uuid-1"}

            service._batch_cache_store(queries, results)

            # Should call set_many for positive results
            mock_cache.set_many.assert_called()

    def test_batch_cache_store_negative_results(self, service):
        """Test caching negative results."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            queries = [DeviceQuery(Provider.WITHINGS, "device-1")]
            results = {"device-1": None}

            service._batch_cache_store(queries, results)

            # Should call set_many for negative results
            mock_cache.set_many.assert_called()

    def test_batch_cache_store_mixed_results(self, service):
        """Test caching mixed positive and negative results."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            queries = [
                DeviceQuery(Provider.WITHINGS, "device-1"),
                DeviceQuery(Provider.WITHINGS, "device-2"),
            ]
            results = {
                "device-1": "Device/uuid-1",
                "device-2": None,
            }

            service._batch_cache_store(queries, results)

            # Should be called twice (positive and negative)
            assert mock_cache.set_many.call_count == 2

    def test_batch_cache_store_error_handling(self, service):
        """Test cache storage error handling."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.set_many.side_effect = Exception("Cache error")

            queries = [DeviceQuery(Provider.WITHINGS, "device-1")]
            results = {"device-1": "Device/uuid-1"}

            # Should not raise
            service._batch_cache_store(queries, results)


class TestGetIdentifierSystem:
    """Tests for _get_identifier_system method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.device_mapping_service.settings") as mock:
            mock.DEVICE_MAPPING = {
                "CACHE_PREFIX": "device_map",
                "CACHE_TTL": 3600,
                "NEGATIVE_CACHE_TTL": 600,
                "BATCH_SIZE": 100,
                "IDENTIFIER_SYSTEMS": {
                    "withings": "https://api.withings.com/device-id",
                    "fitbit": "https://api.fitbit.com/device-id",
                },
            }
            yield mock

    @pytest.fixture
    def service(self, mock_settings):
        """Create service instance."""
        mock_client = MagicMock()
        return DeviceMappingService(fhir_client=mock_client)

    def test_get_identifier_system_withings(self, service):
        """Test getting Withings identifier system."""
        system = service._get_identifier_system(Provider.WITHINGS)
        assert system == "https://api.withings.com/device-id"

    def test_get_identifier_system_fitbit(self, service):
        """Test getting Fitbit identifier system."""
        system = service._get_identifier_system(Provider.FITBIT)
        assert system == "https://api.fitbit.com/device-id"


class TestUtilityMethods:
    """Tests for utility methods."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.device_mapping_service.settings") as mock:
            mock.DEVICE_MAPPING = {
                "CACHE_PREFIX": "device_map",
                "CACHE_TTL": 7200,
                "NEGATIVE_CACHE_TTL": 1800,
                "BATCH_SIZE": 50,
                "IDENTIFIER_SYSTEMS": {
                    "withings": "https://api.withings.com/device-id",
                    "fitbit": "https://api.fitbit.com/device-id",
                },
            }
            yield mock

    @pytest.fixture
    def service(self, mock_settings):
        """Create service instance."""
        mock_client = MagicMock()
        return DeviceMappingService(fhir_client=mock_client)

    def test_clear_cache(self, service):
        """Test clear_cache logs warning."""
        # Should not raise, just log warning
        service.clear_cache()

    def test_get_cache_stats(self, service):
        """Test getting cache stats."""
        with patch("ingestors.device_mapping_service.cache") as mock_cache:
            mock_cache.__str__ = lambda self: "DummyCache"

            stats = service.get_cache_stats()

            assert "cache_backend" in stats
            assert stats["cache_ttl_hours"] == 2  # 7200 / 3600
            assert stats["negative_cache_ttl_hours"] == 0  # 1800 / 3600 rounded down
            assert stats["cache_prefix"] == "device_map"
            assert stats["batch_size"] == 50
            assert "withings" in stats["supported_providers"]
            assert "fitbit" in stats["supported_providers"]


class TestGlobalFunctions:
    """Tests for global convenience functions."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.device_mapping_service.settings") as mock:
            mock.DEVICE_MAPPING = {
                "CACHE_PREFIX": "device_map",
                "CACHE_TTL": 3600,
                "NEGATIVE_CACHE_TTL": 600,
                "BATCH_SIZE": 100,
                "IDENTIFIER_SYSTEMS": {
                    "withings": "https://api.withings.com/device-id",
                    "fitbit": "https://api.fitbit.com/device-id",
                },
            }
            yield mock

    def test_get_device_mapping_service_singleton(self, mock_settings):
        """Test that get_device_mapping_service returns singleton."""
        import ingestors.device_mapping_service as module

        module._device_mapping_service = None

        with patch.object(module, "FHIRClient"):
            service1 = get_device_mapping_service()
            service2 = get_device_mapping_service()

            assert service1 is service2

    def test_get_fhir_device_reference_function(self, mock_settings):
        """Test convenience function for single device mapping."""
        import ingestors.device_mapping_service as module

        module._device_mapping_service = None

        with patch.object(module, "FHIRClient"):
            with patch("ingestors.device_mapping_service.cache") as mock_cache:
                mock_cache.get_many.return_value = {"device_map:withings:device-123": "Device/uuid-123"}

                result = get_fhir_device_reference(Provider.WITHINGS, "device-123")

                assert result == "Device/uuid-123"

    def test_bulk_map_devices_function(self, mock_settings):
        """Test convenience function for bulk device mapping."""
        import ingestors.device_mapping_service as module

        module._device_mapping_service = None

        with patch.object(module, "FHIRClient"):
            with patch("ingestors.device_mapping_service.cache") as mock_cache:
                mock_cache.get_many.return_value = {
                    "device_map:withings:device-1": "Device/uuid-1",
                    "device_map:withings:device-2": "Device/uuid-2",
                }

                result = bulk_map_devices(Provider.WITHINGS, ["device-1", "device-2"])

                assert result["device-1"] == "Device/uuid-1"
                assert result["device-2"] == "Device/uuid-2"


class TestSearchSingleDevice:
    """Tests for _search_single_device method."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.device_mapping_service.settings") as mock:
            mock.DEVICE_MAPPING = {
                "CACHE_PREFIX": "device_map",
                "CACHE_TTL": 3600,
                "NEGATIVE_CACHE_TTL": 600,
                "BATCH_SIZE": 100,
                "IDENTIFIER_SYSTEMS": {},
            }
            yield mock

    @pytest.fixture
    def mock_fhir_client(self):
        """Create mock FHIR client."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_settings, mock_fhir_client):
        """Create service instance."""
        return DeviceMappingService(fhir_client=mock_fhir_client)

    def test_search_single_device_found(self, service, mock_fhir_client):
        """Test finding a single device."""
        mock_fhir_client.search_resource.return_value = {"entry": [{"resource": {"id": "uuid-123"}}]}

        result = service._search_single_device("https://api.withings.com/device-id", "device-123")

        assert result == "uuid-123"

    def test_search_single_device_not_found(self, service, mock_fhir_client):
        """Test when device not found."""
        mock_fhir_client.search_resource.return_value = {"entry": []}

        result = service._search_single_device("https://api.withings.com/device-id", "device-123")

        assert result is None

    def test_search_single_device_empty_resource(self, service, mock_fhir_client):
        """Test when entry has empty resource."""
        mock_fhir_client.search_resource.return_value = {"entry": [{"resource": {}}]}

        result = service._search_single_device("https://api.withings.com/device-id", "device-123")

        assert result is None

    def test_search_single_device_missing_id(self, service, mock_fhir_client):
        """Test when resource has no ID."""
        mock_fhir_client.search_resource.return_value = {"entry": [{"resource": {"resourceType": "Device"}}]}

        result = service._search_single_device("https://api.withings.com/device-id", "device-123")

        assert result is None
