"""
Tests for FHIR Client.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from publishers.fhir.client import FHIRClient


@pytest.fixture
def mock_settings():
    """Mock Django settings for FHIR configuration."""
    with patch("publishers.fhir.client.settings") as mock:
        mock.FHIR_BASE_URL = "https://fhir.example.com/api/"
        mock.FHIR_AUTH_TOKEN_HEADER = "Authorization"
        mock.FHIR_AUTH_TOKEN_VALUE = "Bearer test-token"
        mock.FHIR_CLIENT_CONFIG = {"TIMEOUT": 30}
        yield mock


class TestFHIRClientInit:
    """Tests for FHIRClient initialization."""

    def test_init_with_default_settings(self, mock_settings):
        """Test client initializes with default settings."""
        client = FHIRClient()

        assert client.base_url == "https://fhir.example.com/api/"
        assert client.auth_header == "Authorization"
        assert client.auth_value == "Bearer test-token"

    def test_init_with_custom_values(self, mock_settings):
        """Test client initializes with custom values."""
        client = FHIRClient(
            base_url="https://custom.fhir.com/",
            auth_token="custom-token",
            auth_header="X-API-Key",
        )

        assert client.base_url == "https://custom.fhir.com/"
        assert client.auth_header == "X-API-Key"
        assert client.auth_value == "custom-token"

    def test_init_adds_trailing_slash(self, mock_settings):
        """Test client adds trailing slash to base URL."""
        mock_settings.FHIR_BASE_URL = "https://fhir.example.com/api"
        client = FHIRClient()

        assert client.base_url == "https://fhir.example.com/api/"

    def test_init_raises_without_base_url(self, mock_settings):
        """Test client raises error without base URL."""
        mock_settings.FHIR_BASE_URL = None

        with pytest.raises(ValueError, match="FHIR_BASE_URL not configured"):
            FHIRClient()

    def test_init_raises_without_auth_token(self, mock_settings):
        """Test client raises error without auth token."""
        mock_settings.FHIR_AUTH_TOKEN_VALUE = None

        with pytest.raises(ValueError, match="FHIR_AUTH_TOKEN_VALUE not configured"):
            FHIRClient()


class TestFHIRClientHeaders:
    """Tests for FHIRClient header generation."""

    def test_get_headers_includes_auth(self, mock_settings):
        """Test headers include authentication."""
        client = FHIRClient()
        headers = client._get_headers()

        assert headers["Authorization"] == "Bearer test-token"

    def test_get_headers_includes_fhir_content_type(self, mock_settings):
        """Test headers include FHIR content type."""
        client = FHIRClient()
        headers = client._get_headers()

        assert headers["Accept"] == "application/fhir+json"
        assert headers["Content-Type"] == "application/fhir+json"

    def test_get_headers_includes_cache_control(self, mock_settings):
        """Test headers include cache control."""
        client = FHIRClient()
        headers = client._get_headers()

        assert "Cache-Control" in headers
        assert "no-cache" in headers["Cache-Control"]


class TestFHIRClientSearch:
    """Tests for FHIRClient search operations."""

    @pytest.fixture
    def client(self, mock_settings):
        """Create FHIR client instance."""
        return FHIRClient()

    def test_search_resource_success(self, client, mock_settings):
        """Test successful resource search."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "resourceType": "Bundle",
            "total": 2,
            "entry": [
                {"resource": {"id": "1"}},
                {"resource": {"id": "2"}},
            ],
        }

        with patch("publishers.fhir.client.requests.get", return_value=mock_response) as mock_get:
            result = client.search_resource("Device", {"patient": "Patient/123"})

            assert result["total"] == 2
            assert len(result["entry"]) == 2
            mock_get.assert_called_once()

    def test_search_resource_with_params(self, client, mock_settings):
        """Test search passes parameters correctly."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"total": 0}

        with patch("publishers.fhir.client.requests.get", return_value=mock_response) as mock_get:
            client.search_resource("Observation", {"code": "8867-4"})

            call_args = mock_get.call_args
            assert call_args.kwargs["params"] == {"code": "8867-4"}

    def test_search_resource_error(self, client, mock_settings):
        """Test search handles request errors."""
        with patch("publishers.fhir.client.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.RequestException("Network error")

            with pytest.raises(requests.exceptions.RequestException):
                client.search_resource("Device")


class TestFHIRClientGet:
    """Tests for FHIRClient get operations."""

    @pytest.fixture
    def client(self, mock_settings):
        """Create FHIR client instance."""
        return FHIRClient()

    def test_get_resource_success(self, client, mock_settings):
        """Test successful resource retrieval."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "resourceType": "Device",
            "id": "device-123",
            "status": "active",
        }

        with patch("publishers.fhir.client.requests.get", return_value=mock_response):
            result = client.get_resource("Device", "device-123")

            assert result["id"] == "device-123"
            assert result["status"] == "active"

    def test_get_resource_error(self, client, mock_settings):
        """Test get handles request errors."""
        with patch("publishers.fhir.client.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.RequestException("Not found")

            with pytest.raises(requests.exceptions.RequestException):
                client.get_resource("Device", "nonexistent")


class TestFHIRClientCreate:
    """Tests for FHIRClient create operations."""

    @pytest.fixture
    def client(self, mock_settings):
        """Create FHIR client instance."""
        return FHIRClient()

    def test_create_resource_success(self, client, mock_settings):
        """Test successful resource creation."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "resourceType": "Device",
            "id": "new-device-123",
            "status": "active",
        }

        with patch("publishers.fhir.client.requests.post", return_value=mock_response):
            result = client.create_resource("Device", {"status": "active"})

            assert result["id"] == "new-device-123"

    def test_create_resource_sets_resource_type(self, client, mock_settings):
        """Test create sets resourceType in data."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "1"}

        with patch("publishers.fhir.client.requests.post", return_value=mock_response) as mock_post:
            client.create_resource("Device", {"status": "active"})

            call_args = mock_post.call_args
            assert call_args.kwargs["json"]["resourceType"] == "Device"

    def test_create_resource_error(self, client, mock_settings):
        """Test create handles request errors."""
        mock_error = requests.exceptions.RequestException("Server error")
        mock_error.response = MagicMock()
        mock_error.response.text = "Internal Server Error"

        with patch("publishers.fhir.client.requests.post") as mock_post:
            mock_post.side_effect = mock_error

            with pytest.raises(requests.exceptions.RequestException):
                client.create_resource("Device", {"status": "active"})


class TestFHIRClientUpdate:
    """Tests for FHIRClient update operations."""

    @pytest.fixture
    def client(self, mock_settings):
        """Create FHIR client instance."""
        return FHIRClient()

    def test_update_resource_success(self, client, mock_settings):
        """Test successful resource update."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "resourceType": "Device",
            "id": "device-123",
            "status": "inactive",
        }

        with patch("publishers.fhir.client.requests.put", return_value=mock_response):
            result = client.update_resource("Device", "device-123", {"status": "inactive"})

            assert result["status"] == "inactive"

    def test_update_resource_sets_id_and_type(self, client, mock_settings):
        """Test update sets id and resourceType in data."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "device-123"}

        with patch("publishers.fhir.client.requests.put", return_value=mock_response) as mock_put:
            client.update_resource("Device", "device-123", {"status": "inactive"})

            call_args = mock_put.call_args
            assert call_args.kwargs["json"]["resourceType"] == "Device"
            assert call_args.kwargs["json"]["id"] == "device-123"

    def test_update_resource_error(self, client, mock_settings):
        """Test update handles request errors."""
        mock_error = requests.exceptions.RequestException("Update failed")
        mock_error.response = MagicMock()
        mock_error.response.text = "Conflict"

        with patch("publishers.fhir.client.requests.put") as mock_put:
            mock_put.side_effect = mock_error

            with pytest.raises(requests.exceptions.RequestException):
                client.update_resource("Device", "device-123", {})


class TestFHIRClientDelete:
    """Tests for FHIRClient delete operations."""

    @pytest.fixture
    def client(self, mock_settings):
        """Create FHIR client instance."""
        return FHIRClient()

    def test_delete_resource_success(self, client, mock_settings):
        """Test successful resource deletion."""
        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("publishers.fhir.client.requests.delete", return_value=mock_response):
            # Should not raise
            client.delete_resource("Device", "device-123")

    def test_delete_resource_error(self, client, mock_settings):
        """Test delete handles request errors."""
        with patch("publishers.fhir.client.requests.delete") as mock_delete:
            mock_delete.side_effect = requests.exceptions.RequestException("Delete failed")

            with pytest.raises(requests.exceptions.RequestException):
                client.delete_resource("Device", "device-123")


class TestFHIRClientFindByIdentifier:
    """Tests for FHIRClient find by identifier operations."""

    @pytest.fixture
    def client(self, mock_settings):
        """Create FHIR client instance."""
        return FHIRClient()

    def test_find_resource_found(self, client, mock_settings):
        """Test finding resource by identifier when found."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "total": 1,
            "entry": [{"resource": {"id": "device-123", "status": "active"}}],
        }

        with patch("publishers.fhir.client.requests.get", return_value=mock_response):
            result = client.find_resource_by_identifier("Device", "https://api.withings.com/device-id", "w123")

            assert result is not None
            assert result["id"] == "device-123"

    def test_find_resource_not_found(self, client, mock_settings):
        """Test finding resource by identifier when not found."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"total": 0, "entry": []}

        with patch("publishers.fhir.client.requests.get", return_value=mock_response):
            result = client.find_resource_by_identifier("Device", "https://api.withings.com/device-id", "nonexistent")

            assert result is None

    def test_find_resource_empty_entries(self, client, mock_settings):
        """Test finding resource when bundle has count but no entries."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"total": 1, "entry": []}

        with patch("publishers.fhir.client.requests.get", return_value=mock_response):
            result = client.find_resource_by_identifier("Device", "https://api.withings.com/device-id", "w123")

            assert result is None


class TestFHIRClientUpsert:
    """Tests for FHIRClient upsert operations."""

    @pytest.fixture
    def client(self, mock_settings):
        """Create FHIR client instance."""
        return FHIRClient()

    def test_upsert_creates_when_not_exists(self, client, mock_settings):
        """Test upsert creates new resource when not found."""
        # Search returns no results
        search_response = MagicMock()
        search_response.json.return_value = {"total": 0, "entry": []}

        # Create returns new resource
        create_response = MagicMock()
        create_response.json.return_value = {
            "id": "new-device-123",
            "status": "active",
        }

        with patch("publishers.fhir.client.requests.get", return_value=search_response):
            with patch("publishers.fhir.client.requests.post", return_value=create_response):
                result = client.upsert_resource(
                    "Device",
                    {"status": "active"},
                    "https://api.withings.com/device-id",
                    "w123",
                )

                assert result["id"] == "new-device-123"

    def test_upsert_updates_when_exists(self, client, mock_settings):
        """Test upsert updates resource when found."""
        # Search returns existing resource
        search_response = MagicMock()
        search_response.json.return_value = {
            "total": 1,
            "entry": [{"resource": {"id": "existing-123", "meta": {"versionId": "1"}}}],
        }

        # Update returns updated resource
        update_response = MagicMock()
        update_response.json.return_value = {
            "id": "existing-123",
            "status": "inactive",
        }

        with patch("publishers.fhir.client.requests.get", return_value=search_response):
            with patch("publishers.fhir.client.requests.put", return_value=update_response):
                result = client.upsert_resource(
                    "Device",
                    {"status": "inactive"},
                    "https://api.withings.com/device-id",
                    "w123",
                )

                assert result["id"] == "existing-123"
                assert result["status"] == "inactive"


class TestFHIRClientDeviceAssociations:
    """Tests for FHIRClient device association queries."""

    @pytest.fixture
    def client(self, mock_settings):
        """Create FHIR client instance."""
        return FHIRClient()

    def test_find_active_device_associations_success(self, client, mock_settings):
        """Test finding active device associations."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "total": 2,
            "entry": [
                {"resource": {"id": "assoc-1", "status": {"coding": [{"code": "active"}]}}},
                {"resource": {"id": "assoc-2", "status": {"coding": [{"code": "active"}]}}},
            ],
        }

        with patch("publishers.fhir.client.requests.get", return_value=mock_response):
            result = client.find_active_device_associations("Patient/123", "https://api.withings.com/device-id")

            assert len(result) == 2
            assert result[0]["id"] == "assoc-1"

    def test_find_active_device_associations_empty(self, client, mock_settings):
        """Test finding device associations when none exist."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"total": 0, "entry": []}

        with patch("publishers.fhir.client.requests.get", return_value=mock_response):
            result = client.find_active_device_associations("Patient/123", "https://api.withings.com/device-id")

            assert len(result) == 0
