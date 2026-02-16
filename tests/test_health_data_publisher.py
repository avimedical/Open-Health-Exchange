"""
Tests for health data publisher.
"""

from unittest.mock import MagicMock, patch

import pytest

from ingestors.health_data_constants import Provider
from publishers.fhir.health_data_publisher import HealthDataPublisher


class TestHealthDataPublisher:
    """Tests for HealthDataPublisher class."""

    @pytest.fixture
    def mock_fhir_client(self):
        """Mock FHIR client."""
        with patch("publishers.fhir.health_data_publisher.FHIRClient") as mock:
            mock_client = MagicMock()
            mock.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("publishers.fhir.health_data_publisher.settings") as mock:
            mock.HEALTH_DATA_CONFIG = {"BATCH_SIZES": {"PUBLISHER": 10}}
            yield mock

    @pytest.fixture
    def publisher(self, mock_fhir_client, mock_settings):
        """Create publisher instance with mocked dependencies."""
        return HealthDataPublisher()

    def test_publisher_initialization(self, publisher):
        """Test publisher initializes with FHIR client."""
        assert publisher.fhir_client is not None

    def test_publish_empty_observations(self, publisher, mock_settings):
        """Test publishing empty list returns empty result."""
        result = publisher.publish_health_observations([])

        assert result["total_observations"] == 0
        assert result["published_successfully"] == 0
        assert result["failed_observations"] == 0
        assert result["success"] is True

    def test_publish_single_observation_success(self, publisher, mock_fhir_client, mock_settings):
        """Test publishing a single observation successfully."""
        observation = {
            "resourceType": "Observation",
            "id": "obs-123",
            "identifier": [{"use": "secondary", "system": "https://test.com", "value": "test-id"}],
            "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
        }

        # Mock no existing observation
        mock_fhir_client.find_resource_by_identifier.return_value = None
        mock_fhir_client.create_resource.return_value = {"id": "obs-123"}

        result = publisher.publish_health_observations([observation])

        assert result["total_observations"] == 1
        assert result["published_successfully"] == 1
        assert result["failed_observations"] == 0
        assert result["success"] is True

    def test_publish_skips_duplicate_observation(self, publisher, mock_fhir_client, mock_settings):
        """Test that duplicate observations are skipped."""
        observation = {
            "resourceType": "Observation",
            "identifier": [{"use": "secondary", "system": "https://test.com", "value": "existing-id"}],
        }

        # Mock existing observation found
        mock_fhir_client.find_resource_by_identifier.return_value = {"id": "existing-obs-123"}

        result = publisher.publish_health_observations([observation])

        assert result["total_observations"] == 1
        assert result["published_successfully"] == 0  # Skipped
        mock_fhir_client.create_resource.assert_not_called()

    def test_publish_observation_failure(self, publisher, mock_fhir_client, mock_settings):
        """Test handling of observation publishing failure."""
        observation = {
            "resourceType": "Observation",
            "identifier": [{"use": "secondary", "system": "https://test.com", "value": "test-id"}],
        }

        mock_fhir_client.find_resource_by_identifier.return_value = None
        mock_fhir_client.create_resource.side_effect = Exception("FHIR server error")

        result = publisher.publish_health_observations([observation])

        assert result["failed_observations"] == 1
        assert len(result["errors"]) == 1
        assert "FHIR server error" in result["errors"][0]

    def test_publish_multiple_batches(self, publisher, mock_fhir_client, mock_settings):
        """Test publishing observations in multiple batches."""
        observations = [
            {"resourceType": "Observation", "identifier": [{"use": "secondary", "system": "s", "value": f"v{i}"}]}
            for i in range(15)
        ]

        mock_fhir_client.find_resource_by_identifier.return_value = None
        mock_fhir_client.create_resource.return_value = {"id": "obs-x"}

        result = publisher.publish_health_observations(observations, batch_size=5)

        assert result["total_observations"] == 15
        assert result["published_successfully"] == 15
        assert len(result["batch_results"]) == 3  # 3 batches of 5

    def test_publish_with_custom_batch_size(self, publisher, mock_fhir_client, mock_settings):
        """Test publishing with custom batch size."""
        observations = [
            {"resourceType": "Observation", "identifier": [{"use": "secondary", "system": "s", "value": f"v{i}"}]}
            for i in range(6)
        ]

        mock_fhir_client.find_resource_by_identifier.return_value = None
        mock_fhir_client.create_resource.return_value = {"id": "obs-x"}

        result = publisher.publish_health_observations(observations, batch_size=2)

        assert len(result["batch_results"]) == 3  # 3 batches of 2


class TestHealthBundlePublishing:
    """Tests for FHIR bundle publishing."""

    @pytest.fixture
    def mock_fhir_client(self):
        """Mock FHIR client."""
        with patch("publishers.fhir.health_data_publisher.FHIRClient") as mock:
            mock_client = MagicMock()
            mock.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("publishers.fhir.health_data_publisher.settings") as mock:
            mock.HEALTH_DATA_CONFIG = {"BATCH_SIZES": {"PUBLISHER": 10}}
            yield mock

    @pytest.fixture
    def publisher(self, mock_fhir_client, mock_settings):
        """Create publisher instance."""
        return HealthDataPublisher()

    def test_publish_bundle_success(self, publisher, mock_fhir_client):
        """Test successful bundle publishing."""
        bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                {"resource": {"resourceType": "Observation"}},
                {"resource": {"resourceType": "Observation"}},
            ],
        }

        mock_fhir_client.create_resource.return_value = {
            "id": "bundle-123",
            "entry": [
                {"response": {"status": "201 Created"}},
                {"response": {"status": "201 Created"}},
            ],
        }

        result = publisher.publish_health_bundle(bundle)

        assert result["success"] is True
        assert result["bundle_id"] == "bundle-123"
        assert result["published_successfully"] == 2
        assert result["failed_entries"] == 0

    def test_publish_bundle_partial_failure(self, publisher, mock_fhir_client):
        """Test bundle publishing with partial failure."""
        bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                {"resource": {"resourceType": "Observation"}},
                {"resource": {"resourceType": "Observation"}},
            ],
        }

        mock_fhir_client.create_resource.return_value = {
            "id": "bundle-456",
            "entry": [
                {"response": {"status": "201 Created"}},
                {"response": {"status": "400 Bad Request"}, "outcome": {"error": "Invalid data"}},
            ],
        }

        result = publisher.publish_health_bundle(bundle)

        assert result["success"] is False
        assert result["published_successfully"] == 1
        assert result["failed_entries"] == 1
        assert len(result["errors"]) == 1

    def test_publish_bundle_server_error(self, publisher, mock_fhir_client):
        """Test bundle publishing with server error."""
        bundle = {"resourceType": "Bundle", "type": "transaction", "entry": []}

        mock_fhir_client.create_resource.side_effect = Exception("Server unavailable")

        result = publisher.publish_health_bundle(bundle)

        assert result["success"] is False
        assert "Server unavailable" in result["error"]


class TestHealthDataStatistics:
    """Tests for health data statistics retrieval."""

    @pytest.fixture
    def mock_fhir_client(self):
        """Mock FHIR client."""
        with patch("publishers.fhir.health_data_publisher.FHIRClient") as mock:
            mock_client = MagicMock()
            mock.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("publishers.fhir.health_data_publisher.settings") as mock:
            mock.HEALTH_DATA_CONFIG = {"BATCH_SIZES": {"PUBLISHER": 10}}
            yield mock

    @pytest.fixture
    def publisher(self, mock_fhir_client, mock_settings):
        """Create publisher instance."""
        return HealthDataPublisher()

    def test_get_statistics_empty(self, publisher, mock_fhir_client):
        """Test getting statistics with no observations."""
        mock_fhir_client.search_resource.return_value = {"total": 0, "entry": []}

        stats = publisher.get_health_data_statistics("Patient/123")

        assert stats["total_observations"] == 0
        assert stats["observations_by_type"] == {}

    def test_get_statistics_with_observations(self, publisher, mock_fhir_client):
        """Test getting statistics with observations."""
        mock_fhir_client.search_resource.return_value = {
            "total": 2,
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
                        "effectiveDateTime": "2024-01-15T10:00:00Z",
                        "meta": {"tag": [{"system": "https://open-health-exchange.com/provider", "code": "withings"}]},
                    }
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
                        "effectiveDateTime": "2024-01-16T10:00:00Z",
                        "meta": {"tag": [{"system": "https://open-health-exchange.com/provider", "code": "withings"}]},
                    }
                },
            ],
        }

        stats = publisher.get_health_data_statistics("Patient/123")

        assert stats["total_observations"] == 2
        assert stats["observations_by_type"]["8867-4"] == 2
        assert stats["observations_by_provider"]["withings"] == 2

    def test_get_statistics_error(self, publisher, mock_fhir_client):
        """Test statistics retrieval handles errors."""
        mock_fhir_client.search_resource.side_effect = Exception("Search failed")

        stats = publisher.get_health_data_statistics("Patient/123")

        assert "error" in stats
        assert stats["total_observations"] == 0


class TestHealthDataDeletion:
    """Tests for health data deletion."""

    @pytest.fixture
    def mock_fhir_client(self):
        """Mock FHIR client."""
        with patch("publishers.fhir.health_data_publisher.FHIRClient") as mock:
            mock_client = MagicMock()
            mock.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("publishers.fhir.health_data_publisher.settings") as mock:
            mock.HEALTH_DATA_CONFIG = {"BATCH_SIZES": {"PUBLISHER": 10}}
            yield mock

    @pytest.fixture
    def publisher(self, mock_fhir_client, mock_settings):
        """Create publisher instance."""
        return HealthDataPublisher()

    def test_delete_health_data_success(self, publisher, mock_fhir_client):
        """Test successful health data deletion."""
        mock_fhir_client.search_resource.return_value = {
            "total": 2,
            "entry": [
                {"resource": {"id": "obs-1"}},
                {"resource": {"id": "obs-2"}},
            ],
        }

        result = publisher.delete_health_data_by_provider("Patient/123", Provider.WITHINGS)

        assert result["success"] is True
        assert result["total_found"] == 2
        assert result["deleted_count"] == 2
        assert mock_fhir_client.delete_resource.call_count == 2

    def test_delete_health_data_partial_failure(self, publisher, mock_fhir_client):
        """Test deletion with partial failure."""
        mock_fhir_client.search_resource.return_value = {
            "total": 2,
            "entry": [
                {"resource": {"id": "obs-1"}},
                {"resource": {"id": "obs-2"}},
            ],
        }
        mock_fhir_client.delete_resource.side_effect = [None, Exception("Delete failed")]

        result = publisher.delete_health_data_by_provider("Patient/123", Provider.FITBIT)

        assert result["success"] is False
        assert result["deleted_count"] == 1
        assert result["failed_count"] == 1

    def test_delete_health_data_none_found(self, publisher, mock_fhir_client):
        """Test deletion when no data found."""
        mock_fhir_client.search_resource.return_value = {"total": 0, "entry": []}

        result = publisher.delete_health_data_by_provider("Patient/123", Provider.WITHINGS)

        assert result["success"] is True
        assert result["total_found"] == 0
        assert result["deleted_count"] == 0


class TestFindExistingObservation:
    """Tests for duplicate observation detection."""

    @pytest.fixture
    def mock_fhir_client(self):
        """Mock FHIR client."""
        with patch("publishers.fhir.health_data_publisher.FHIRClient") as mock:
            mock_client = MagicMock()
            mock.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("publishers.fhir.health_data_publisher.settings") as mock:
            mock.HEALTH_DATA_CONFIG = {"BATCH_SIZES": {"PUBLISHER": 10}}
            yield mock

    @pytest.fixture
    def publisher(self, mock_fhir_client, mock_settings):
        """Create publisher instance."""
        return HealthDataPublisher()

    def test_find_existing_no_identifier(self, publisher):
        """Test with observation having no identifier."""
        observation = {"resourceType": "Observation"}

        result = publisher._find_existing_observation(observation)

        assert result is None

    def test_find_existing_no_secondary_identifier(self, publisher):
        """Test with observation having no secondary identifier."""
        observation = {
            "resourceType": "Observation",
            "identifier": [{"use": "official", "value": "test"}],
        }

        result = publisher._find_existing_observation(observation)

        assert result is None

    def test_find_existing_with_secondary_identifier(self, publisher, mock_fhir_client):
        """Test finding observation with secondary identifier."""
        observation = {
            "resourceType": "Observation",
            "identifier": [{"use": "secondary", "system": "https://test.com", "value": "test-123"}],
        }

        mock_fhir_client.find_resource_by_identifier.return_value = {"id": "existing-obs"}

        result = publisher._find_existing_observation(observation)

        assert result is not None
        assert result["id"] == "existing-obs"
        mock_fhir_client.find_resource_by_identifier.assert_called_once_with(
            "Observation", "https://test.com", "test-123"
        )

    def test_find_existing_handles_error(self, publisher, mock_fhir_client):
        """Test error handling during duplicate check."""
        observation = {
            "resourceType": "Observation",
            "identifier": [{"use": "secondary", "system": "https://test.com", "value": "test-123"}],
        }

        mock_fhir_client.find_resource_by_identifier.side_effect = Exception("Search error")

        result = publisher._find_existing_observation(observation)

        # Should return None on error (allowing the observation to be created)
        assert result is None
