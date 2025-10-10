"""
DeviceAssociation Publisher for managing FHIR DeviceAssociation resources
"""

import logging
from typing import Any

from django.utils import dateparse, timezone

from ingestors.constants import DeviceData
from transformers.fhir_transformers import DeviceAssociationTransformer

from .client import FHIRClient

logger = logging.getLogger(__name__)


class DeviceAssociationPublisher:
    """Publishes and manages FHIR DeviceAssociation resources"""

    def __init__(self):
        self.fhir_client = FHIRClient()
        self.transformer = DeviceAssociationTransformer()

    def publish_association(
        self, device_data: DeviceData, patient_reference: str, device_reference: str
    ) -> dict[str, Any]:
        """
        Publish a device association to the FHIR server (create or update)

        Args:
            device_data: Standardized device information
            patient_reference: FHIR Patient reference
            device_reference: FHIR Device reference

        Returns:
            Published FHIR DeviceAssociation resource
        """
        try:
            # Check if association already exists
            existing_association = self.find_association_by_device(
                device_data.provider.value, device_data.provider_device_id, patient_reference
            )

            # Create or update association
            fhir_association = self.transformer.transform(device_data, patient_reference, device_reference)

            if existing_association:
                # Update existing association
                association_resource = self.fhir_client.update_resource(
                    "DeviceAssociation", existing_association["id"], fhir_association
                )
                logger.info(f"Updated device association {association_resource['id']}")
            else:
                # Create new association
                association_resource = self.fhir_client.create_resource("DeviceAssociation", fhir_association)
                logger.info(f"Created new device association {association_resource['id']}")

            # Cache the association mapping (disabled temporarily)
            # self._cache_association_mapping(device_info, association_resource['id'])

            return association_resource

        except Exception as e:
            logger.error(f"Error publishing device association for {device_data.provider_device_id}: {e}")
            raise

    def publish_associations_batch(
        self, devices: list[DeviceData], patient_reference: str, device_references: dict[str, str]
    ) -> tuple[list[dict], list[Exception]]:
        """
        Publish multiple device associations in batch

        Args:
            devices: List of standardized device information
            patient_reference: FHIR Patient reference
            device_references: Map of provider_device_id to FHIR Device reference

        Returns:
            Tuple of (successful_associations, errors)
        """
        successful_associations = []
        errors = []

        for device_info in devices:
            try:
                device_reference = device_references.get(device_info.provider_device_id)
                if not device_reference:
                    raise ValueError(f"No device reference found for {device_info.provider_device_id}")

                association_resource = self.publish_association(device_info, patient_reference, device_reference)
                successful_associations.append(association_resource)

            except Exception as e:
                errors.append(e)
                logger.error(f"Failed to publish association for device {device_info.provider_device_id}: {e}")

        logger.info(
            f"Batch association publish completed: {len(successful_associations)} successful, {len(errors)} errors"
        )
        return successful_associations, errors

    def deactivate_association(
        self, provider: str, provider_device_id: str, patient_reference: str, end_date: str | None = None
    ) -> dict[str, Any] | None:
        """
        Deactivate a device association

        Args:
            provider: Provider name
            provider_device_id: Provider device ID
            patient_reference: FHIR Patient reference
            end_date: End date (defaults to current time)

        Returns:
            Updated DeviceAssociation resource if found, None otherwise
        """
        try:
            # Find existing association
            existing_association = self.find_association_by_device(provider, provider_device_id, patient_reference)

            if not existing_association:
                logger.warning(f"No association found for device {provider}/{provider_device_id}")
                return None

            # Only deactivate if currently active
            if existing_association.get("status") != "active":
                logger.info(f"Association for device {provider}/{provider_device_id} is already inactive")
                return existing_association

            # Deactivate the association by updating status and end date
            deactivated_association = existing_association.copy()
            deactivated_association["status"] = {
                "coding": [
                    {
                        "system": "http://hl7.org/fhir/device-association-status",
                        "code": "inactive",
                        "display": "Inactive",
                    }
                ]
            }

            # Update period end date
            if "period" not in deactivated_association:
                deactivated_association["period"] = {}
            deactivated_association["period"]["end"] = end_date or (timezone.now().isoformat() + "Z")

            # Update on FHIR server
            association_resource = self.fhir_client.update_resource(
                "DeviceAssociation", existing_association["id"], deactivated_association
            )

            # Update cache
            self._remove_association_from_cache(provider, provider_device_id)

            logger.info(f"Deactivated device association {association_resource['id']}")
            return association_resource

        except Exception as e:
            logger.error(f"Error deactivating association for {provider}/{provider_device_id}: {e}")
            raise

    def deactivate_missing_associations(
        self, active_device_ids: list[str], provider: str, patient_reference: str
    ) -> list[dict[str, Any]]:
        """
        Deactivate associations for devices that are no longer present in provider API

        Args:
            active_device_ids: List of provider device IDs that are currently active
            provider: Provider name
            patient_reference: FHIR Patient reference

        Returns:
            List of deactivated DeviceAssociation resources
        """
        try:
            # Get all active associations for this provider
            active_associations = self.find_active_associations_by_provider(provider, patient_reference)
            deactivated_associations = []

            for association in active_associations:
                # Extract provider device ID from association identifiers
                provider_device_id = self._extract_provider_device_id(association, provider)

                if provider_device_id and provider_device_id not in active_device_ids:
                    # Association is for a missing device - deactivate it
                    deactivated_association = self.deactivate_association(
                        provider, provider_device_id, patient_reference
                    )

                    if deactivated_association:
                        deactivated_associations.append(deactivated_association)

            logger.info(f"Deactivated {len(deactivated_associations)} missing associations for provider {provider}")
            return deactivated_associations

        except Exception as e:
            logger.error(f"Error deactivating missing associations for provider {provider}: {e}")
            raise

    def find_association_by_device(
        self, provider: str, provider_device_id: str, patient_reference: str
    ) -> dict[str, Any] | None:
        """
        Find a device association by provider device ID

        Args:
            provider: Provider name
            provider_device_id: Provider device ID
            patient_reference: FHIR Patient reference

        Returns:
            DeviceAssociation resource if found, None otherwise
        """
        try:
            # Check cache first
            cached_association_id = self._get_cached_association_id(provider, provider_device_id)
            if cached_association_id:
                try:
                    association = self.fhir_client.get_resource("DeviceAssociation", cached_association_id)
                    # Verify it's for the right patient
                    if association.get("subject", {}).get("reference") == patient_reference:
                        return association
                except Exception:
                    # Cache miss or association deleted - fall through to search
                    self._remove_association_from_cache(provider, provider_device_id)

            # Search on FHIR server
            provider_system = f"https://api.{provider.lower()}.com/device-association"

            params = {"subject": patient_reference, "identifier": f"{provider_system}|{provider_device_id}"}

            bundle = self.fhir_client.search_resource("DeviceAssociation", params)

            if bundle.get("total", 0) > 0:
                entries = bundle.get("entry", [])
                if entries:
                    association = entries[0].get("resource")
                    # Cache the result
                    self._cache_association_mapping(
                        type("DeviceData", (), {"provider": provider, "provider_device_id": provider_device_id})(),
                        association["id"],
                    )
                    return association

            return None

        except Exception as e:
            logger.error(f"Error finding association for device {provider}/{provider_device_id}: {e}")
            raise

    def find_active_associations_by_provider(self, provider: str, patient_reference: str) -> list[dict[str, Any]]:
        """
        Find all active associations for a patient from a specific provider

        Args:
            provider: Provider name
            patient_reference: FHIR Patient reference

        Returns:
            List of active DeviceAssociation resources
        """
        try:
            provider_system = f"https://api.{provider.lower()}.com/device-association"

            params = {
                "subject": patient_reference,
                "status": "active",
                "identifier": f"{provider_system}|",  # Match any association from this provider
            }

            bundle = self.fhir_client.search_resource("DeviceAssociation", params)
            associations = []

            if bundle.get("total", 0) > 0:
                for entry in bundle.get("entry", []):
                    associations.append(entry.get("resource"))

            logger.info(f"Found {len(associations)} active associations for provider {provider}")
            return associations

        except Exception as e:
            logger.error(f"Error finding active associations for provider {provider}: {e}")
            raise

    def get_association_statistics(self, patient_reference: str) -> dict[str, Any]:
        """
        Get device association statistics for a patient

        Args:
            patient_reference: FHIR Patient reference

        Returns:
            Statistics about patient's device associations
        """
        try:
            # Search for all associations for this patient
            params = {"subject": patient_reference}
            bundle = self.fhir_client.search_resource("DeviceAssociation", params)

            associations = []
            if bundle.get("total", 0) > 0:
                for entry in bundle.get("entry", []):
                    associations.append(entry.get("resource"))

            # Analyze associations
            stats: dict[str, Any] = {
                "total_associations": len(associations),
                "active_associations": 0,
                "inactive_associations": 0,
                "associations_by_provider": {},
                "recent_associations": 0,  # Active in last 30 days
            }

            now = timezone.now()
            thirty_days_ago = (
                timezone.now().replace(day=now.day - 30)
                if now.day > 30
                else timezone.now().replace(month=now.month - 1)
            )

            for association in associations:
                # Count by status
                if association.get("status") == "active":
                    stats["active_associations"] += 1
                else:
                    stats["inactive_associations"] += 1

                # Count by provider
                provider = self._get_association_provider(association)
                if provider:
                    stats["associations_by_provider"][provider] = stats["associations_by_provider"].get(provider, 0) + 1

                # Check recent activity
                period = association.get("period", {})
                if "start" in period:
                    try:
                        start_date = dateparse.parse_datetime(period["start"])
                        if start_date:
                            start_date = (
                                start_date.astimezone(timezone.utc)
                                if start_date.tzinfo
                                else start_date.replace(tzinfo=timezone.utc)
                            )
                            if start_date >= thirty_days_ago:
                                stats["recent_associations"] += 1
                    except (ValueError, TypeError):
                        pass

            return stats

        except Exception as e:
            logger.error(f"Error getting association statistics for {patient_reference}: {e}")
            raise

    def _extract_provider_device_id(self, association: dict[str, Any], provider: str) -> str | None:
        """Extract provider device ID from DeviceAssociation identifiers"""
        provider_system = f"https://api.{provider.lower()}.com/device-association"

        for identifier in association.get("identifier", []):
            if identifier.get("system") == provider_system and identifier.get("use") == "secondary":
                return identifier.get("value")

        return None

    def _get_association_provider(self, association: dict[str, Any]) -> str | None:
        """Extract provider name from association identifiers"""
        for identifier in association.get("identifier", []):
            system = identifier.get("system", "")
            if "withings.com" in system:
                return "withings"
            elif "fitbit.com" in system:
                return "fitbit"
        return None

    def _cache_association_mapping(self, device_info, fhir_association_id: str):
        """Cache association mapping for quick lookups"""
        # cache.set(cache_key, fhir_association_id, timeout=settings.CACHE_TIMEOUTS['ASSOCIATION_CACHE'])  # 24 hours - disabled temporarily

    def _get_cached_association_id(self, provider: str, provider_device_id: str) -> str | None:
        """Get cached FHIR association ID"""
        return None  # cache.get(cache_key) - disabled temporarily

    def _remove_association_from_cache(self, provider: str, provider_device_id: str):
        """Remove association from cache"""
        # cache.delete(cache_key) - disabled temporarily
