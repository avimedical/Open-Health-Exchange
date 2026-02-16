"""
Tests for DeviceAssociation Publisher - FHIR DeviceAssociation resource management.
"""

from unittest.mock import MagicMock, patch

import pytest

from ingestors.constants import DeviceData, Provider
from publishers.fhir.association_publisher import DeviceAssociationPublisher


class TestDeviceAssociationPublisher:
    """Tests for DeviceAssociationPublisher class."""

    @pytest.fixture
    def publisher(self):
        """Create DeviceAssociationPublisher with mocked dependencies."""
        with (
            patch("publishers.fhir.association_publisher.FHIRClient") as mock_client,
            patch("publishers.fhir.association_publisher.DeviceAssociationTransformer") as mock_transformer,
        ):
            pub = DeviceAssociationPublisher()
            pub.fhir_client = mock_client.return_value
            pub.transformer = mock_transformer.return_value
            yield pub

    @pytest.fixture
    def sample_device_data(self):
        """Create sample DeviceData."""
        return DeviceData(
            provider=Provider.WITHINGS,
            provider_device_id="device-123",
            device_type="Blood Pressure Monitor",
            model="BPM Connect",
            manufacturer="Withings",
        )

    def test_publish_association_creates_new(self, publisher, sample_device_data):
        """Test publishing a new association."""
        publisher.fhir_client.search_resource.return_value = {"total": 0, "entry": []}
        publisher.transformer.transform.return_value = {"resourceType": "DeviceAssociation"}
        publisher.fhir_client.create_resource.return_value = {"id": "assoc-123"}

        result = publisher.publish_association(sample_device_data, "Patient/test-user", "Device/device-123")

        assert result["id"] == "assoc-123"
        publisher.fhir_client.create_resource.assert_called_once()

    def test_publish_association_updates_existing(self, publisher, sample_device_data):
        """Test publishing updates existing association."""
        publisher.fhir_client.search_resource.return_value = {
            "total": 1,
            "entry": [{"resource": {"id": "existing-assoc-123"}}],
        }
        publisher.transformer.transform.return_value = {"resourceType": "DeviceAssociation"}
        publisher.fhir_client.update_resource.return_value = {"id": "existing-assoc-123"}

        result = publisher.publish_association(sample_device_data, "Patient/test-user", "Device/device-123")

        assert result["id"] == "existing-assoc-123"
        publisher.fhir_client.update_resource.assert_called_once()

    def test_publish_association_error_raises(self, publisher, sample_device_data):
        """Test publish association raises on error."""
        publisher.fhir_client.search_resource.side_effect = Exception("FHIR error")

        with pytest.raises(Exception, match="FHIR error"):
            publisher.publish_association(sample_device_data, "Patient/test-user", "Device/device-123")


class TestDeviceAssociationPublisherBatch:
    """Tests for batch association operations."""

    @pytest.fixture
    def publisher(self):
        """Create DeviceAssociationPublisher with mocked dependencies."""
        with (
            patch("publishers.fhir.association_publisher.FHIRClient") as mock_client,
            patch("publishers.fhir.association_publisher.DeviceAssociationTransformer") as mock_transformer,
        ):
            pub = DeviceAssociationPublisher()
            pub.fhir_client = mock_client.return_value
            pub.transformer = mock_transformer.return_value
            yield pub

    @pytest.fixture
    def multiple_devices(self):
        """Create multiple DeviceData."""
        return [
            DeviceData(
                provider=Provider.WITHINGS,
                provider_device_id="device-1",
                device_type="Scale",
                model="Body+",
                manufacturer="Withings",
            ),
            DeviceData(
                provider=Provider.WITHINGS,
                provider_device_id="device-2",
                device_type="Blood Pressure Monitor",
                model="BPM Connect",
                manufacturer="Withings",
            ),
        ]

    def test_publish_associations_batch_success(self, publisher, multiple_devices):
        """Test batch publishing associations."""
        publisher.fhir_client.search_resource.return_value = {"total": 0, "entry": []}
        publisher.transformer.transform.return_value = {"resourceType": "DeviceAssociation"}
        publisher.fhir_client.create_resource.side_effect = [
            {"id": "assoc-1"},
            {"id": "assoc-2"},
        ]

        device_refs = {"device-1": "Device/device-1", "device-2": "Device/device-2"}
        successful, errors = publisher.publish_associations_batch(multiple_devices, "Patient/test-user", device_refs)

        assert len(successful) == 2
        assert len(errors) == 0

    def test_publish_associations_batch_missing_reference(self, publisher, multiple_devices):
        """Test batch with missing device reference."""
        publisher.fhir_client.search_resource.return_value = {"total": 0, "entry": []}
        publisher.transformer.transform.return_value = {"resourceType": "DeviceAssociation"}
        publisher.fhir_client.create_resource.return_value = {"id": "assoc-1"}

        # Only provide reference for device-1
        device_refs = {"device-1": "Device/device-1"}
        successful, errors = publisher.publish_associations_batch(multiple_devices, "Patient/test-user", device_refs)

        assert len(successful) == 1
        assert len(errors) == 1
        assert "No device reference found" in str(errors[0])


class TestDeviceAssociationDeactivation:
    """Tests for association deactivation."""

    @pytest.fixture
    def publisher(self):
        """Create DeviceAssociationPublisher with mocked dependencies."""
        with (
            patch("publishers.fhir.association_publisher.FHIRClient") as mock_client,
            patch("publishers.fhir.association_publisher.DeviceAssociationTransformer"),
        ):
            pub = DeviceAssociationPublisher()
            pub.fhir_client = mock_client.return_value
            yield pub

    def test_deactivate_association_success(self, publisher):
        """Test deactivating an association."""
        existing = {"id": "assoc-123", "status": "active", "subject": {"reference": "Patient/test"}}
        publisher.fhir_client.search_resource.return_value = {
            "total": 1,
            "entry": [{"resource": existing}],
        }
        publisher.fhir_client.update_resource.return_value = {
            **existing,
            "status": {"coding": [{"code": "inactive"}]},
        }

        result = publisher.deactivate_association("withings", "device-123", "Patient/test")

        assert result is not None
        publisher.fhir_client.update_resource.assert_called_once()

    def test_deactivate_association_not_found(self, publisher):
        """Test deactivating when association not found."""
        publisher.fhir_client.search_resource.return_value = {"total": 0, "entry": []}

        result = publisher.deactivate_association("withings", "device-123", "Patient/test")

        assert result is None

    def test_deactivate_association_already_inactive(self, publisher):
        """Test deactivating already inactive association."""
        existing = {
            "id": "assoc-123",
            "status": "inactive",
            "subject": {"reference": "Patient/test"},
        }
        publisher.fhir_client.search_resource.return_value = {
            "total": 1,
            "entry": [{"resource": existing}],
        }

        result = publisher.deactivate_association("withings", "device-123", "Patient/test")

        assert result == existing
        publisher.fhir_client.update_resource.assert_not_called()

    def test_deactivate_missing_associations(self, publisher):
        """Test deactivating associations for missing devices."""
        active_associations = [
            {
                "id": "assoc-1",
                "status": "active",
                "subject": {"reference": "Patient/test"},
                "identifier": [
                    {"system": "https://api.withings.com/device-association", "use": "secondary", "value": "device-1"}
                ],
            },
            {
                "id": "assoc-2",
                "status": "active",
                "subject": {"reference": "Patient/test"},
                "identifier": [
                    {"system": "https://api.withings.com/device-association", "use": "secondary", "value": "device-2"}
                ],
            },
        ]

        # First call returns active associations, subsequent calls for individual lookups
        publisher.fhir_client.search_resource.side_effect = [
            {"total": 2, "entry": [{"resource": a} for a in active_associations]},
            {"total": 1, "entry": [{"resource": active_associations[1]}]},  # For device-2 lookup
        ]
        publisher.fhir_client.update_resource.return_value = {
            **active_associations[1],
            "status": {"coding": [{"code": "inactive"}]},
        }

        # Only device-1 is still active
        deactivated = publisher.deactivate_missing_associations(["device-1"], "withings", "Patient/test")

        assert len(deactivated) == 1


class TestAssociationSearch:
    """Tests for association search operations."""

    @pytest.fixture
    def publisher(self):
        """Create DeviceAssociationPublisher with mocked dependencies."""
        with (
            patch("publishers.fhir.association_publisher.FHIRClient") as mock_client,
            patch("publishers.fhir.association_publisher.DeviceAssociationTransformer"),
        ):
            pub = DeviceAssociationPublisher()
            pub.fhir_client = mock_client.return_value
            yield pub

    def test_find_association_by_device_found(self, publisher):
        """Test finding association by device."""
        association = {"id": "assoc-123", "subject": {"reference": "Patient/test"}}
        publisher.fhir_client.search_resource.return_value = {
            "total": 1,
            "entry": [{"resource": association}],
        }

        result = publisher.find_association_by_device("withings", "device-123", "Patient/test")

        assert result == association

    def test_find_association_by_device_not_found(self, publisher):
        """Test finding association when not found."""
        publisher.fhir_client.search_resource.return_value = {"total": 0, "entry": []}

        result = publisher.find_association_by_device("withings", "device-123", "Patient/test")

        assert result is None

    def test_find_active_associations_by_provider(self, publisher):
        """Test finding active associations by provider."""
        associations = [
            {"id": "assoc-1", "status": "active"},
            {"id": "assoc-2", "status": "active"},
        ]
        publisher.fhir_client.search_resource.return_value = {
            "total": 2,
            "entry": [{"resource": a} for a in associations],
        }

        result = publisher.find_active_associations_by_provider("withings", "Patient/test")

        assert len(result) == 2


class TestAssociationStatistics:
    """Tests for association statistics."""

    @pytest.fixture
    def publisher(self):
        """Create DeviceAssociationPublisher with mocked dependencies."""
        with (
            patch("publishers.fhir.association_publisher.FHIRClient") as mock_client,
            patch("publishers.fhir.association_publisher.DeviceAssociationTransformer"),
        ):
            pub = DeviceAssociationPublisher()
            pub.fhir_client = mock_client.return_value
            yield pub

    def test_get_association_statistics(self, publisher):
        """Test getting association statistics."""
        associations = [
            {
                "id": "assoc-1",
                "status": "active",
                "identifier": [{"system": "https://api.withings.com/device-association"}],
            },
            {
                "id": "assoc-2",
                "status": "inactive",
                "identifier": [{"system": "https://api.fitbit.com/device-association"}],
            },
        ]
        publisher.fhir_client.search_resource.return_value = {
            "total": 2,
            "entry": [{"resource": a} for a in associations],
        }

        stats = publisher.get_association_statistics("Patient/test")

        assert stats["total_associations"] == 2
        assert stats["active_associations"] == 1
        assert stats["inactive_associations"] == 1
        assert stats["associations_by_provider"]["withings"] == 1
        assert stats["associations_by_provider"]["fitbit"] == 1

    def test_get_association_statistics_empty(self, publisher):
        """Test statistics when no associations exist."""
        publisher.fhir_client.search_resource.return_value = {"total": 0, "entry": []}

        stats = publisher.get_association_statistics("Patient/test")

        assert stats["total_associations"] == 0


class TestAssociationHelpers:
    """Tests for helper methods."""

    @pytest.fixture
    def publisher(self):
        """Create DeviceAssociationPublisher with mocked dependencies."""
        with (
            patch("publishers.fhir.association_publisher.FHIRClient"),
            patch("publishers.fhir.association_publisher.DeviceAssociationTransformer"),
        ):
            yield DeviceAssociationPublisher()

    def test_extract_provider_device_id_found(self, publisher):
        """Test extracting provider device ID."""
        association = {
            "identifier": [
                {"system": "https://api.withings.com/device-association", "use": "secondary", "value": "device-123"},
            ]
        }

        result = publisher._extract_provider_device_id(association, "withings")

        assert result == "device-123"

    def test_extract_provider_device_id_not_found(self, publisher):
        """Test extracting provider device ID when not present."""
        association = {"identifier": []}

        result = publisher._extract_provider_device_id(association, "withings")

        assert result is None

    def test_get_association_provider_withings(self, publisher):
        """Test extracting provider from Withings association."""
        association = {"identifier": [{"system": "https://api.withings.com/device-association"}]}

        result = publisher._get_association_provider(association)

        assert result == "withings"

    def test_get_association_provider_fitbit(self, publisher):
        """Test extracting provider from Fitbit association."""
        association = {"identifier": [{"system": "https://api.fitbit.com/device-association"}]}

        result = publisher._get_association_provider(association)

        assert result == "fitbit"

    def test_get_association_provider_unknown(self, publisher):
        """Test extracting provider from unknown association."""
        association = {"identifier": [{"system": "https://api.unknown.com/device-association"}]}

        result = publisher._get_association_provider(association)

        assert result is None

    def test_cache_association_mapping(self, publisher):
        """Test caching association mapping (currently disabled)."""
        # Should not raise even though caching is disabled
        device_info = MagicMock()
        publisher._cache_association_mapping(device_info, "assoc-123")

    def test_get_cached_association_id(self, publisher):
        """Test getting cached association ID (currently returns None)."""
        result = publisher._get_cached_association_id("withings", "device-123")

        assert result is None

    def test_remove_association_from_cache(self, publisher):
        """Test removing association from cache (currently no-op)."""
        # Should not raise
        publisher._remove_association_from_cache("withings", "device-123")
