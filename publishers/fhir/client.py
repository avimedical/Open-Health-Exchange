"""
FHIR Client for interacting with FHIR server
"""
import logging
import requests
from django.conf import settings
from typing import Dict, Optional, Any, List

logger = logging.getLogger(__name__)


class FHIRClient:
    """Client for interacting with FHIR server"""

    def __init__(self):
        self.base_url = settings.FHIR_BASE_URL
        self.auth_header = settings.FHIR_AUTH_TOKEN_HEADER
        self.auth_value = settings.FHIR_AUTH_TOKEN_VALUE

        if not self.base_url:
            raise ValueError("FHIR_BASE_URL not configured")

        if not self.auth_value:
            raise ValueError("FHIR_AUTH_TOKEN_VALUE not configured")

        # Ensure base_url ends with /
        if not self.base_url.endswith('/'):
            self.base_url += '/'

    def _get_headers(self) -> Dict[str, str]:
        """Get common headers for FHIR requests"""
        return {
            self.auth_header: self.auth_value,
            'Accept': 'application/fhir+json',
            'Content-Type': 'application/fhir+json',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }

    def search_resource(self, resource_type: str, params: Optional[Dict] = None) -> Dict:
        """
        Search for FHIR resources

        Args:
            resource_type: Type of FHIR resource (e.g., 'Device', 'Patient')
            params: Search parameters

        Returns:
            FHIR Bundle with search results
        """
        url = f"{self.base_url}{resource_type}"

        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                params=params or {},
                timeout=settings.FHIR_CLIENT_CONFIG['TIMEOUT']
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching {resource_type}: {e}")
            raise

    def get_resource(self, resource_type: str, resource_id: str) -> Dict:
        """
        Get a specific FHIR resource by ID

        Args:
            resource_type: Type of FHIR resource
            resource_id: Resource ID

        Returns:
            FHIR resource
        """
        url = f"{self.base_url}{resource_type}/{resource_id}"

        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=settings.FHIR_CLIENT_CONFIG['TIMEOUT']
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting {resource_type}/{resource_id}: {e}")
            raise

    def create_resource(self, resource_type: str, resource_data: Dict) -> Dict:
        """
        Create a new FHIR resource

        Args:
            resource_type: Type of FHIR resource
            resource_data: Resource data in FHIR format

        Returns:
            Created FHIR resource
        """
        url = f"{self.base_url}{resource_type}"

        # Ensure resourceType is set correctly
        resource_data['resourceType'] = resource_type

        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=resource_data,
                timeout=settings.FHIR_CLIENT_CONFIG['TIMEOUT']
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error creating {resource_type}: {e}")
            if e.response is not None and hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            raise

    def update_resource(self, resource_type: str, resource_id: str, resource_data: Dict) -> Dict:
        """
        Update an existing FHIR resource

        Args:
            resource_type: Type of FHIR resource
            resource_id: Resource ID
            resource_data: Updated resource data

        Returns:
            Updated FHIR resource
        """
        url = f"{self.base_url}{resource_type}/{resource_id}"

        # Ensure resourceType and id are set correctly
        resource_data['resourceType'] = resource_type
        resource_data['id'] = resource_id

        try:
            response = requests.put(
                url,
                headers=self._get_headers(),
                json=resource_data,
                timeout=settings.FHIR_CLIENT_CONFIG['TIMEOUT']
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error updating {resource_type}/{resource_id}: {e}")
            if e.response is not None and hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            raise

    def delete_resource(self, resource_type: str, resource_id: str) -> None:
        """
        Delete a FHIR resource

        Args:
            resource_type: Type of FHIR resource
            resource_id: Resource ID
        """
        url = f"{self.base_url}{resource_type}/{resource_id}"

        try:
            response = requests.delete(
                url,
                headers=self._get_headers(),
                timeout=settings.FHIR_CLIENT_CONFIG['TIMEOUT']
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error deleting {resource_type}/{resource_id}: {e}")
            raise

    def find_resource_by_identifier(self, resource_type: str, system: str, value: str) -> Optional[Dict]:
        """
        Find a FHIR resource by its identifier

        Args:
            resource_type: Type of FHIR resource
            system: Identifier system
            value: Identifier value

        Returns:
            FHIR resource if found, None otherwise
        """
        params = {
            'identifier': f"{system}|{value}"
        }

        bundle = self.search_resource(resource_type, params)

        if bundle.get('total', 0) > 0:
            entries = bundle.get('entry', [])
            if entries:
                return entries[0].get('resource')

        return None

    def upsert_resource(self, resource_type: str, resource_data: Dict, identifier_system: str, identifier_value: str) -> Dict:
        """
        Create or update a FHIR resource based on identifier

        Args:
            resource_type: Type of FHIR resource
            resource_data: Resource data in FHIR format
            identifier_system: System for the identifier
            identifier_value: Value for the identifier

        Returns:
            Created or updated FHIR resource
        """
        # Check if resource already exists
        existing_resource = self.find_resource_by_identifier(resource_type, identifier_system, identifier_value)

        if existing_resource:
            # Update existing resource
            resource_id = existing_resource['id']
            # Preserve the existing id and meta
            resource_data['id'] = resource_id
            if 'meta' in existing_resource:
                resource_data['meta'] = existing_resource['meta']

            logger.info(f"Updating existing {resource_type} {resource_id}")
            return self.update_resource(resource_type, resource_id, resource_data)
        else:
            # Create new resource
            logger.info(f"Creating new {resource_type} with identifier {identifier_system}|{identifier_value}")
            return self.create_resource(resource_type, resource_data)

    def find_active_device_associations(self, patient_reference: str, provider_system: str) -> List[Dict]:
        """
        Find active DeviceAssociations for a patient from a specific provider

        Args:
            patient_reference: Patient reference (e.g., "Patient/123")
            provider_system: Provider identifier system

        Returns:
            List of active DeviceAssociation resources
        """
        params = {
            'subject': patient_reference,
            'status': 'active',
            'identifier': f"{provider_system}|"  # Will match any device from this provider
        }

        bundle = self.search_resource('DeviceAssociation', params)
        associations = []

        if bundle.get('total', 0) > 0:
            for entry in bundle.get('entry', []):
                associations.append(entry.get('resource'))

        return associations