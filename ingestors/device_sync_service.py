"""
Modern device synchronization service
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from django.utils import timezone

from publishers.fhir.association_publisher import DeviceAssociationPublisher
from publishers.fhir.client import FHIRClient
from transformers.fhir_transformers import DeviceAssociationTransformer, DeviceTransformer

from .constants import DeviceData, Provider
from .device_manager import DeviceManagerFactory

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SyncResult:
    """Result of device synchronization"""

    user_id: str
    provider: Provider
    processed_devices: int = 0
    processed_associations: int = 0
    deactivated_associations: int = 0
    errors: list[str] = field(default_factory=list)
    success: bool = False
    sync_timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class DeviceSyncService:
    """Modern device synchronization service"""

    def __init__(self, fhir_client: FHIRClient | None = None):
        self.fhir_client = fhir_client or FHIRClient()
        self.device_transformer = DeviceTransformer()
        self.association_transformer = DeviceAssociationTransformer()
        self.logger = logging.getLogger(f"{__name__}.DeviceSyncService")

    def sync_user_devices(
        self, user_id: str, provider: Provider | str, patient_reference: str | None = None
    ) -> SyncResult:
        """
        Synchronize devices for a user from a specific provider

        Args:
            user_id: EHR user ID
            provider: Provider name
            patient_reference: FHIR Patient reference (defaults to Patient/{user_id})

        Returns:
            SyncResult with details of the synchronization
        """
        if isinstance(provider, str):
            provider = Provider(provider)

        if patient_reference is None:
            patient_reference = f"Patient/{user_id}"

        result = SyncResult(user_id=user_id, provider=provider)

        try:
            # 1. Fetch devices from provider
            devices = self._fetch_devices(user_id, provider)
            self.logger.info(f"Fetched {len(devices)} devices from {provider}")

            # Collect active device IDs from the provider response (not from publish results)
            # so that publish failures don't cause incorrect deactivation
            active_device_ids = [device.provider_device_id for device in devices]

            # 2. Process each device
            processed_devices = []
            processed_associations = []

            for device in devices:
                try:
                    # Create FHIR Device
                    device_resource = self._publish_device(device)
                    processed_devices.append(device_resource)

                    # Create FHIR DeviceAssociation
                    device_ref = f"Device/{device_resource['id']}"
                    association_resource = self._publish_association(device, patient_reference, device_ref)
                    processed_associations.append(association_resource)

                    self.logger.info(f"Successfully processed device {device.provider_device_id}")

                except Exception as e:
                    error_msg = f"Error processing device {device.provider_device_id}: {e}"
                    self.logger.error(error_msg)
                    result.errors.append(error_msg)

            # 3. Deactivate associations no longer present in provider
            # Note: Only deactivate DeviceAssociations (patient-scoped), not Device resources.
            # Device resources are not patient-scoped in FHIR, so deactivating them here
            # could affect other users sharing the same provider.
            try:
                association_publisher = DeviceAssociationPublisher(self.fhir_client)

                deactivated_assocs = association_publisher.deactivate_missing_associations(
                    active_device_ids, provider.value, patient_reference
                )

                result.deactivated_associations = len(deactivated_assocs)

                if deactivated_assocs:
                    self.logger.info(f"Deactivated {len(deactivated_assocs)} associations for user {user_id}")
            except Exception as e:
                self.logger.warning(f"Error during association deactivation for user {user_id}: {e}")

            # 4. Update result
            result.processed_devices = len(processed_devices)
            result.processed_associations = len(processed_associations)
            result.success = len(result.errors) == 0

            self.logger.info(
                f"Device sync completed for user {user_id}: "
                f"{result.processed_devices} devices, "
                f"{result.processed_associations} associations, "
                f"{result.deactivated_associations} deactivated associations, "
                f"{len(result.errors)} errors"
            )

            return result

        except Exception as e:
            error_msg = f"Unexpected error in device sync for user {user_id}: {e}"
            self.logger.error(error_msg)
            result.errors.append(error_msg)
            return result

    def _fetch_devices(self, user_id: str, provider: Provider) -> list[DeviceData]:
        """Fetch devices from provider API"""
        try:
            device_manager = DeviceManagerFactory.create(provider)
            return device_manager.fetch_user_devices(user_id)
        except Exception as e:
            self.logger.error(f"Failed to fetch devices from {provider}: {e}")
            raise

    def _publish_device(self, device: DeviceData) -> dict:
        """Publish device to FHIR server"""
        try:
            fhir_device = self.device_transformer.transform(device)
            return self.fhir_client.create_resource("Device", fhir_device)
        except Exception as e:
            self.logger.error(f"Failed to publish device {device.provider_device_id}: {e}")
            raise

    def _publish_association(self, device: DeviceData, patient_ref: str, device_ref: str) -> dict:
        """Publish device association to FHIR server"""
        try:
            fhir_association = self.association_transformer.transform(device, patient_ref, device_ref)
            return self.fhir_client.create_resource("DeviceAssociation", fhir_association)
        except Exception as e:
            self.logger.error(f"Failed to publish association for device {device.provider_device_id}: {e}")
            raise

    def get_sync_statistics(self, user_id: str) -> dict[str, Any]:
        """Get synchronization statistics for a user"""
        try:
            # This could be expanded to query FHIR server for actual stats
            patient_ref = f"Patient/{user_id}"

            # Search for devices
            device_bundle = self.fhir_client.search_resource("Device", {})
            total_devices = device_bundle.get("total", 0)

            # Search for associations
            association_bundle = self.fhir_client.search_resource("DeviceAssociation", {"subject": patient_ref})
            user_associations = association_bundle.get("total", 0)

            return {
                "user_id": user_id,
                "total_devices_in_system": total_devices,
                "user_device_associations": user_associations,
                "last_check": timezone.now().isoformat(),
            }
        except Exception as e:
            self.logger.error(f"Failed to get sync statistics for user {user_id}: {e}")
            return {"user_id": user_id, "error": str(e), "last_check": timezone.now().isoformat()}


class MockDeviceSyncService(DeviceSyncService):
    """Mock device sync service for testing"""

    def __init__(self):
        # Initialize with mock FHIR client that doesn't require real configuration
        from publishers.fhir.client import FHIRClient

        mock_client = FHIRClient(
            base_url="http://mock-fhir-server.example.com/fhir/",
            auth_token="mock-token",
            auth_header="Authorization",
        )
        super().__init__(fhir_client=mock_client)
        self.published_devices = []
        self.published_associations = []

    def _publish_device(self, device: DeviceData) -> dict:
        """Mock device publishing"""
        fhir_device = self.device_transformer.transform(device)
        fhir_device["id"] = f"mock-device-{len(self.published_devices)}"
        self.published_devices.append(fhir_device)
        return fhir_device

    def _publish_association(self, device: DeviceData, patient_ref: str, device_ref: str) -> dict:
        """Mock association publishing"""
        fhir_association = self.association_transformer.transform(device, patient_ref, device_ref)
        fhir_association["id"] = f"mock-association-{len(self.published_associations)}"
        self.published_associations.append(fhir_association)
        return fhir_association
