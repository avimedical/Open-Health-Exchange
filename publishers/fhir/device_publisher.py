"""
Device Publisher for managing FHIR Device resources
"""
import logging
from typing import Dict, List, Optional, Any, Tuple

from .client import FHIRClient
from transformers.fhir_transformers import DeviceTransformer
from ingestors.constants import DeviceData

logger = logging.getLogger(__name__)


class DevicePublisher:
    """Publishes and manages FHIR Device resources"""

    def __init__(self):
        self.fhir_client = FHIRClient()
        self.transformer = DeviceTransformer()

    def publish_device(self, device_data: DeviceData, patient_reference: str | None = None) -> Dict[str, Any]:
        """
        Publish a device to the FHIR server (create or update)

        Args:
            device_data: Standardized device information
            patient_reference: Not used (devices don't reference patients directly)

        Returns:
            Published FHIR Device resource
        """
        try:
            # Transform to FHIR Device (no patient reference)
            fhir_device = self.transformer.transform(device_data)

            # Create device directly
            device_resource = self.fhir_client.create_resource('Device', fhir_device)

            logger.info(f"Successfully published device {device_resource['id']} for provider {device_data.provider.value}")
            return device_resource

        except Exception as e:
            logger.error(f"Error publishing device {device_data.provider_device_id}: {e}")
            raise

    def publish_devices_batch(self,
                            devices: List[DeviceData],
                            patient_reference: str) -> Tuple[List[Dict], List[Exception]]:
        """
        Publish multiple devices in batch

        Args:
            devices: List of standardized device information
            patient_reference: FHIR Patient reference

        Returns:
            Tuple of (successful_devices, errors)
        """
        successful_devices = []
        errors = []

        for device_data in devices:
            try:
                device_resource = self.publish_device(device_data, patient_reference)
                successful_devices.append(device_resource)
            except Exception as e:
                errors.append(e)
                logger.error(f"Failed to publish device {device_data.provider_device_id}: {e}")

        logger.info(f"Batch publish completed: {len(successful_devices)} successful, {len(errors)} errors")
        return successful_devices, errors

    def find_devices_by_provider(self, provider: str, patient_reference: str) -> List[Dict[str, Any]]:
        """
        Find all devices from a specific provider (without patient filtering for now)

        Args:
            provider: Provider name (withings, fitbit, etc.)
            patient_reference: FHIR Patient reference (not used in search but kept for compatibility)

        Returns:
            List of FHIR Device resources
        """
        try:
            provider_system = f"https://api.{provider.lower()}.com/device-id"

            # Search for devices from this provider only by identifier system
            # Note: Device resources don't have patient field, so we can't filter by patient
            params = {
                'identifier': f"{provider_system}|"  # Match any device from this provider
            }

            bundle = self.fhir_client.search_resource('Device', params)
            devices = []

            if bundle.get('total', 0) > 0:
                for entry in bundle.get('entry', []):
                    devices.append(entry.get('resource'))

            logger.info(f"Found {len(devices)} devices for provider {provider}")
            return devices

        except Exception as e:
            logger.error(f"Error finding devices for provider {provider}: {e}")
            raise

    def deactivate_missing_devices(self,
                                 active_device_ids: List[str],
                                 provider: str,
                                 patient_reference: str) -> List[Dict[str, Any]]:
        """
        Deactivate devices that are no longer present in provider API

        Args:
            active_device_ids: List of provider device IDs that are currently active
            provider: Provider name
            patient_reference: FHIR Patient reference

        Returns:
            List of deactivated Device resources
        """
        try:
            # Get all existing devices for this provider
            existing_devices = self.find_devices_by_provider(provider, patient_reference)
            deactivated_devices = []

            for device in existing_devices:
                # Extract provider device ID from identifiers
                provider_device_id = self._extract_provider_device_id(device, provider)

                if provider_device_id and provider_device_id not in active_device_ids:
                    # Device is missing from provider API - deactivate it
                    device['status'] = 'inactive'
                    device['statusReason'] = [
                        {
                            'coding': [{
                                'system': 'http://terminology.hl7.org/CodeSystem/device-status-reason',
                                'code': 'offline',
                                'display': 'Offline'
                            }]
                        }
                    ]

                    # Update the device on FHIR server
                    updated_device = self.fhir_client.update_resource(
                        'Device',
                        device['id'],
                        device
                    )
                    deactivated_devices.append(updated_device)

                    # Update cache
                    self._remove_device_from_cache(provider, provider_device_id)

                    logger.info(f"Deactivated device {device['id']} (provider ID: {provider_device_id})")

            logger.info(f"Deactivated {len(deactivated_devices)} missing devices for provider {provider}")
            return deactivated_devices

        except Exception as e:
            logger.error(f"Error deactivating missing devices for provider {provider}: {e}")
            raise

    def get_device_by_provider_id(self, provider: str, provider_device_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a device by provider and provider device ID

        Args:
            provider: Provider name
            provider_device_id: Provider-specific device ID

        Returns:
            FHIR Device resource if found, None otherwise
        """
        try:
            # Check cache first
            cached_device_id = self._get_cached_device_id(provider, provider_device_id)
            if cached_device_id:
                try:
                    return self.fhir_client.get_resource('Device', cached_device_id)
                except Exception:
                    # Cache miss or device deleted - fall through to search
                    self._remove_device_from_cache(provider, provider_device_id)

            # Search on FHIR server
            provider_system = f"https://api.{provider.lower()}.com/device-id"

            device = self.fhir_client.find_resource_by_identifier(
                'Device',
                provider_system,
                provider_device_id
            )

            # Cache the result if found
            if device:
                self._cache_device_mapping(
                    type('DeviceData', (), {
                        'provider': provider,
                        'provider_device_id': provider_device_id
                    })(),
                    device['id']
                )

            return device

        except Exception as e:
            logger.error(f"Error getting device by provider ID {provider}/{provider_device_id}: {e}")
            raise

    def _extract_provider_device_id(self, device: Dict[str, Any], provider: str) -> Optional[str]:
        """Extract provider device ID from FHIR Device identifiers"""
        provider_system = f"https://api.{provider.lower()}.com/device-id"

        for identifier in device.get('identifier', []):
            if identifier.get('system') == provider_system:
                return identifier.get('value')

        return None

    def _cache_device_mapping(self, device_info, fhir_device_id: str):
        """Cache device mapping for quick lookups"""
        cache_key = f"device:{device_info.provider}:{device_info.provider_device_id}"
        # cache.set(cache_key, fhir_device_id, timeout=settings.CACHE_TIMEOUTS['DEVICE_CACHE'])  # 24 hours - disabled temporarily

    def _get_cached_device_id(self, provider: str, provider_device_id: str) -> Optional[str]:
        """Get cached FHIR device ID"""
        cache_key = f"device:{provider}:{provider_device_id}"
        return None  # cache.get(cache_key) - disabled temporarily

    def _remove_device_from_cache(self, provider: str, provider_device_id: str):
        """Remove device from cache"""
        cache_key = f"device:{provider}:{provider_device_id}"
        # cache.delete(cache_key) - disabled temporarily

    def get_device_statistics(self, patient_reference: str) -> Dict[str, Any]:
        """
        Get device statistics for a patient

        Args:
            patient_reference: FHIR Patient reference

        Returns:
            Statistics about patient's devices
        """
        try:
            # Search for all devices for this patient
            params = {'patient': patient_reference}
            bundle = self.fhir_client.search_resource('Device', params)

            devices = []
            if bundle.get('total', 0) > 0:
                for entry in bundle.get('entry', []):
                    devices.append(entry.get('resource'))

            # Analyze devices
            stats: Dict[str, Any] = {
                'total_devices': len(devices),
                'active_devices': 0,
                'inactive_devices': 0,
                'devices_by_provider': {},
                'devices_by_type': {}
            }

            for device in devices:
                # Count by status
                if device.get('status') == 'active':
                    stats['active_devices'] += 1
                else:
                    stats['inactive_devices'] += 1

                # Count by provider
                provider = self._get_device_provider(device)
                if provider:
                    stats['devices_by_provider'][provider] = stats['devices_by_provider'].get(provider, 0) + 1

                # Count by type
                device_type = self._get_device_type(device)
                if device_type:
                    stats['devices_by_type'][device_type] = stats['devices_by_type'].get(device_type, 0) + 1

            return stats

        except Exception as e:
            logger.error(f"Error getting device statistics for {patient_reference}: {e}")
            raise

    def _get_device_provider(self, device: Dict[str, Any]) -> Optional[str]:
        """Extract provider name from device identifiers"""
        for identifier in device.get('identifier', []):
            system = identifier.get('system', '')
            if 'withings.com' in system:
                return 'withings'
            elif 'fitbit.com' in system:
                return 'fitbit'
        return None

    def _get_device_type(self, device: Dict[str, Any]) -> Optional[str]:
        """Extract device type from FHIR device"""
        device_types = device.get('type', [])
        if device_types and len(device_types) > 0:
            return device_types[0].get('text', 'unknown')
        return None