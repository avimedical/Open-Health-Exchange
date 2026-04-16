"""
Modern, generic device manager using Python 3.13+ features
"""

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from django.conf import settings
from social_django.models import UserSocialAuth

from .constants import PROVIDER_CONFIGS, BatteryLevel, DeviceData, DeviceType, Provider

logger = logging.getLogger(__name__)


@runtime_checkable
class APIClient(Protocol):
    """Protocol for API clients"""

    def fetch_devices(self) -> list[dict]: ...


@dataclass(slots=True, frozen=True)
class OAuthCredentials:
    """OAuth credentials for API access"""

    access_token: str
    refresh_token: str | None = None
    user_id: str | None = None
    expires_in: int | None = None


class DeviceManagerError(Exception):
    """Base exception for device manager errors"""


class AuthenticationError(DeviceManagerError):
    """Authentication related errors"""


class APIError(DeviceManagerError):
    """API communication errors"""


class DeviceManager:
    """Generic device manager for all providers"""

    def __init__(self, provider: Provider):
        self.provider = provider
        self.config = PROVIDER_CONFIGS[provider]
        self.logger = logging.getLogger(f"{__name__}.{provider}")

    def fetch_user_devices(self, user_id: str) -> list[DeviceData]:
        """Fetch devices for a user from the provider"""
        try:
            credentials = self._get_user_credentials(user_id)
            client = self._create_api_client(credentials)
            raw_devices = client.fetch_devices()
            return [self._transform_device_data(device) for device in raw_devices]

        except Exception as e:
            self.logger.error(f"Failed to fetch devices for user {user_id}: {e}")
            match e:
                case AuthenticationError() | APIError():
                    raise
                case _:
                    raise APIError(f"Unexpected error: {e}") from e

    def _get_user_credentials(self, user_id: str) -> OAuthCredentials:
        """Get OAuth credentials for a user"""
        try:
            auth = (
                UserSocialAuth.objects.filter(user__ehr_user_id=user_id, provider=self.provider.value)
                .order_by("-id")
                .first()
            )
            if not auth:
                raise AuthenticationError(f"No {self.provider} credentials for user {user_id}")
            return OAuthCredentials(
                access_token=auth.extra_data["access_token"],
                refresh_token=auth.extra_data.get("refresh_token"),
                user_id=auth.extra_data.get("userid"),
                expires_in=auth.extra_data.get("expires"),
            )
        except AuthenticationError:
            raise
        except KeyError as e:
            raise AuthenticationError(f"Missing credential field: {e}")

    def _create_api_client(self, credentials: OAuthCredentials) -> APIClient:
        """Create provider-specific API client"""
        match self.provider:
            case Provider.WITHINGS:
                return self._create_withings_client(credentials)
            case Provider.FITBIT:
                return self._create_fitbit_client(credentials)
            case _:
                raise DeviceManagerError(f"Unsupported provider: {self.provider}")

    def _create_withings_client(self, credentials: OAuthCredentials) -> APIClient:
        """Create Withings API client using direct HTTP calls"""
        return DirectWithingsClient(
            access_token=credentials.access_token,
            api_base_url=self.config.api_base_url,
        )

    def _create_fitbit_client(self, credentials: OAuthCredentials) -> APIClient:
        """Create Fitbit API client"""
        import fitbit

        client = fitbit.Fitbit(
            client_id=getattr(settings, self.config.client_id_setting),
            client_secret=getattr(settings, self.config.client_secret_setting),
            oauth2=True,
            access_token=credentials.access_token,
            refresh_token=credentials.refresh_token,
            refresh_cb=lambda token: None,
        )

        return FitbitApiAdapter(client)

    def _transform_device_data(self, raw_device: dict) -> DeviceData:
        """Transform raw device data to standardized format"""
        match self.provider:
            case Provider.WITHINGS:
                return self._transform_withings_device(raw_device)
            case Provider.FITBIT:
                return self._transform_fitbit_device(raw_device)
            case _:
                raise DeviceManagerError(f"Unsupported provider: {self.provider}")

    def _transform_withings_device(self, device: dict) -> DeviceData:
        """Transform Withings device data from API response dict"""
        device_type_str = device.get("type", "")
        device_type = self.config.device_types_map.get(device_type_str, DeviceType.UNKNOWN)

        return DeviceData(
            provider_device_id=str(device.get("deviceid", "")),
            provider=self.provider,
            device_type=device_type,
            manufacturer="Withings",
            model=device.get("model", "Unknown Model"),
            battery_level=BatteryLevel.from_text(device.get("battery")),
            raw_data={
                "deviceid": device.get("deviceid"),
                "timezone": device.get("timezone"),
                "battery_text": device.get("battery"),
                "type": device_type_str,
                "model_id": device.get("model_id"),
                "mac_address": device.get("mac_address"),
            },
        )

    def _transform_fitbit_device(self, device_data: dict) -> DeviceData:
        """Transform Fitbit device data"""
        device_type = self.config.device_types_map.get(device_data.get("type", ""), DeviceType.UNKNOWN)

        return DeviceData(
            provider_device_id=str(device_data.get("id", "")),
            provider=self.provider,
            device_type=device_type,
            manufacturer="Fitbit",
            model=device_data.get("deviceVersion", "Unknown Model"),
            battery_level=BatteryLevel.from_text(device_data.get("batteryLevel")),
            last_sync=device_data.get("lastSyncTime"),
            firmware_version=device_data.get("version"),
            raw_data={
                "id": device_data.get("id"),
                "type": device_data.get("type"),
                "batteryLevel": device_data.get("batteryLevel"),
                "mac": device_data.get("mac"),
            },
        )


class DirectWithingsClient:
    """Direct Withings API client using HTTP requests (replaces withings-api library)"""

    def __init__(self, access_token: str, api_base_url: str):
        self.access_token = access_token
        self.api_base_url = api_base_url

    def fetch_devices(self) -> list[dict]:
        """Fetch devices from Withings API using direct HTTP call"""
        import requests

        url = f"{self.api_base_url}/v2/user"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        data = {"action": "getdevice"}

        try:
            response = requests.post(url, headers=headers, data=data, timeout=30)
            response.raise_for_status()

            json_response = response.json()

            # Withings API returns status 0 for success
            status = json_response.get("status", -1)
            if status != 0:
                error_message = json_response.get("error", f"Unknown error (status: {status})")
                raise APIError(f"Withings API error: {error_message}")

            body = json_response.get("body", {})
            devices: list[dict] = body.get("devices", [])
            return devices

        except requests.exceptions.Timeout:
            raise APIError("Withings API request timed out")
        except requests.exceptions.RequestException as e:
            if hasattr(e, "response") and e.response is not None:
                if e.response.status_code == 401:
                    raise AuthenticationError("Withings access token expired or invalid")
            raise APIError(f"Withings API request failed: {e}") from e


class FitbitApiAdapter:
    """Adapter for Fitbit API to match APIClient protocol"""

    def __init__(self, client):
        self.client = client

    def fetch_devices(self) -> list[dict[str, Any]]:
        """Fetch devices from Fitbit API using the dedicated devices endpoint"""
        try:
            # Use the dedicated devices endpoint, not user profile
            devices: list[dict[str, Any]] = self.client.get_devices() or []
            return devices
        except Exception as e:
            if "expired" in str(e).lower() or "invalid" in str(e).lower():
                raise AuthenticationError("Access token expired or invalid")
            raise APIError(f"Fitbit API error: {e}") from e


class DeviceManagerFactory:
    """Factory for creating device managers"""

    @staticmethod
    def create(provider: Provider | str) -> DeviceManager:
        """Create a device manager for the specified provider"""
        if isinstance(provider, str):
            provider = Provider(provider)

        if provider not in PROVIDER_CONFIGS:
            raise DeviceManagerError(f"Unsupported provider: {provider}")

        return DeviceManager(provider)

    @staticmethod
    def get_supported_providers() -> list[Provider]:
        """Get list of supported providers"""
        return list(PROVIDER_CONFIGS.keys())
