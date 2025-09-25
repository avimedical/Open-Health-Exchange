"""
Production API clients for health data providers
Handles real API integration with proper error handling, token management, and rate limiting
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Optional, List, Dict, cast
from dataclasses import dataclass
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Native implementation - no third-party Withings library needed
WITHINGS_AVAILABLE = True  # We implement it ourselves

try:
    import fitbit
    FITBIT_AVAILABLE = True
except ImportError:
    FITBIT_AVAILABLE = False

from django.conf import settings
from social_django.models import UserSocialAuth

from .health_data_constants import HealthDataType, HealthDataRecord, Provider, DateRange, MeasurementSource
from .circuit_breaker import withings_circuit_breaker, fitbit_circuit_breaker
from metrics.collectors import metrics


logger = logging.getLogger(__name__)


@dataclass
class APIClientConfig:
    """Configuration for API clients"""
    max_retries: int = 3
    backoff_factor: float = 1.0
    timeout: int = 30
    rate_limit_window: int = 60  # seconds
    max_requests_per_window: int = 300


class APIError(Exception):
    """Base exception for API errors"""
    pass


class TokenExpiredError(APIError):
    """Token has expired and needs refresh"""
    pass


class RateLimitError(APIError):
    """Rate limit exceeded"""
    pass


class APIClientBase:
    """Base class for API clients with common functionality"""

    def __init__(self, provider: Provider, config: Optional[APIClientConfig] = None):
        self.provider = provider
        self.config = config or APIClientConfig()
        self.logger = logging.getLogger(f"{__name__}.{provider.value.title()}APIClient")

        # Setup session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Rate limiting tracking
        self._request_times: List[float] = []

    def _check_rate_limit(self) -> None:
        """Check if we're within rate limits"""
        current_time = time.time()
        window_start = current_time - self.config.rate_limit_window

        # Remove old requests outside the window
        self._request_times = [t for t in self._request_times if t > window_start]

        if len(self._request_times) >= self.config.max_requests_per_window:
            sleep_time = self._request_times[0] + self.config.rate_limit_window - current_time
            if sleep_time > 0:
                self.logger.warning(f"Rate limit reached, sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
                # Clean up old requests after sleeping
                current_time = time.time()
                window_start = current_time - self.config.rate_limit_window
                self._request_times = [t for t in self._request_times if t > window_start]

        self._request_times.append(current_time)

    def _refresh_token(self, user_social_auth: UserSocialAuth) -> bool:
        """Refresh OAuth2 token - to be implemented by subclasses"""
        raise NotImplementedError("Subclasses must implement token refresh")

    def _get_user_tokens(self, user_id: str) -> UserSocialAuth:
        """Get user's OAuth tokens"""
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()

            user = User.objects.get(ehr_user_id=user_id)
            social_auth = UserSocialAuth.objects.get(
                user=user,
                provider=self.provider.value
            )
            return social_auth
        except Exception as e:
            raise APIError(f"Failed to get user tokens for {user_id}: {e}")


class WithingsAPIClient(APIClientBase):
    """Native Withings API client using direct HTTP requests"""

    BASE_URL = "https://wbsapi.withings.net"

    # Withings measurement types
    MEASURE_TYPES = {
        'weight': 1,
        'height': 4,
        'fat_free_mass': 5,
        'fat_ratio': 6,
        'fat_mass_weight': 8,
        'diastolic_bp': 9,
        'systolic_bp': 10,
        'heart_rate': 11,
        'temperature': 12,
        'spo2': 54,
        'body_temperature': 71,
        'skin_temperature': 73
    }

    def __init__(self, config: Optional[APIClientConfig] = None):
        super().__init__(Provider.WITHINGS, config)

    def _refresh_token(self, user_social_auth: UserSocialAuth) -> bool:
        """Refresh Withings OAuth2 token using native HTTP requests"""
        try:
            refresh_token = user_social_auth.extra_data.get('refresh_token')
            if not refresh_token:
                raise TokenExpiredError("No refresh token available")

            # Prepare token refresh request
            token_url = "https://wbsapi.withings.net/v2/oauth2"
            data = {
                'action': 'requesttoken',
                'grant_type': 'refresh_token',
                'client_id': settings.SOCIAL_AUTH_WITHINGS_KEY,
                'client_secret': settings.SOCIAL_AUTH_WITHINGS_SECRET,
                'refresh_token': refresh_token
            }

            response = self.session.post(token_url, data=data)
            response.raise_for_status()

            token_data = response.json()

            if token_data.get('status') != 0:
                raise TokenExpiredError(f"Token refresh failed: {token_data.get('error', 'Unknown error')}")

            body = token_data.get('body', {})

            # Update stored tokens
            user_social_auth.extra_data.update({
                'access_token': body['access_token'],
                'refresh_token': body['refresh_token'],
                'expires_in': body.get('expires_in', 3600),
                'token_type': 'Bearer'
            })
            user_social_auth.save()

            self.logger.info(f"Successfully refreshed Withings token for user {user_social_auth.user.ehr_user_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to refresh Withings token: {e}")
            raise TokenExpiredError(f"Token refresh failed: {e}")

    def _make_authenticated_request(self, endpoint: str, params: dict, access_token: str) -> dict:
        """Make authenticated request to Withings API"""
        url = f"{self.BASE_URL}{endpoint}"

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        response = self.session.post(url, data=params, headers=headers)
        response.raise_for_status()

        data = response.json()

        if data.get('status') != 0:
            error_msg = data.get('error', 'Unknown API error')
            if 'invalid_token' in error_msg.lower() or 'unauthorized' in error_msg.lower():
                raise TokenExpiredError(f"Token expired: {error_msg}")
            raise APIError(f"Withings API error: {error_msg}")

        return data

    def _get_measurement_source(self, category: int) -> MeasurementSource:
        """Convert Withings category to measurement source"""
        if category == 1:
            return MeasurementSource.DEVICE  # Real measurement
        elif category == 2:
            return MeasurementSource.USER    # User objective
        return MeasurementSource.UNKNOWN

    @withings_circuit_breaker
    def get_heart_rate_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch heart rate data from Withings API"""
        self._check_rate_limit()
        start_time = time.time()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")

            # Convert dates to Unix timestamps
            start_timestamp = int(start_date.timestamp())
            end_timestamp = int(end_date.timestamp())

            # Prepare request parameters
            params = {
                'action': 'getmeas',
                'meastype': self.MEASURE_TYPES['heart_rate'],
                'startdate': start_timestamp,
                'enddate': end_timestamp
            }

            # Make authenticated request
            data = self._make_authenticated_request('/v2/measure', params, access_token)

            heart_rate_data = []
            measuregrps = data.get('body', {}).get('measuregrps', [])

            for group in measuregrps:
                # Each group can have multiple measures
                measures = group.get('measures', [])
                for measure in measures:
                    if measure.get('type') == self.MEASURE_TYPES['heart_rate']:
                        # Calculate actual value (Withings uses scaling)
                        value = measure.get('value', 0)
                        unit = measure.get('unit', 0)
                        if unit != 0:
                            value = value * (10 ** unit)

                        # Get measurement source from category
                        category = group.get('category', 1)
                        measurement_source = self._get_measurement_source(category)

                        heart_rate_data.append({
                            'timestamp': datetime.fromtimestamp(group.get('date', 0)),
                            'value': float(value),
                            'device_id': group.get('deviceid'),
                            'measurement_id': group.get('grpid'),
                            'measurement_source': measurement_source,
                            'category': category
                        })

            self.logger.info(f"Fetched {len(heart_rate_data)} heart rate measurements from Withings")

            # Record metrics
            duration = time.time() - start_time
            metrics.record_sync_operation(
                provider="withings",
                operation_type="heart_rate_fetch",
                status="success",
                duration=duration
            )
            metrics.record_data_points("withings", "heart_rate", len(heart_rate_data))

            return heart_rate_data

        except TokenExpiredError as e:
            # Try token refresh
            try:
                self._refresh_token(social_auth)
                # Retry with new token
                return cast(List[Dict[str, Any]], self.get_heart_rate_data(user_id, start_date, end_date))
            except TokenExpiredError:
                duration = time.time() - start_time
                metrics.record_sync_operation(
                    provider="withings",
                    operation_type="heart_rate_fetch",
                    status="error",
                    duration=duration
                )
                raise APIError(f"Withings authentication failed and token refresh unsuccessful: {e}")
        except Exception as e:
            # Record error metrics
            duration = time.time() - start_time
            metrics.record_sync_operation(
                provider="withings",
                operation_type="heart_rate_fetch",
                status="error",
                duration=duration
            )
            metrics.record_provider_api_error("withings", "api_error")

            self.logger.error(f"Failed to fetch heart rate data from Withings: {e}")
            raise APIError(f"Withings API error: {e}")

    @withings_circuit_breaker
    def get_activity_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch activity data (steps, distance, calories) from Withings API"""
        self._check_rate_limit()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")

            # Prepare request parameters (activity uses date format YYYY-MM-DD)
            params = {
                'action': 'getactivity',
                'startdateymd': start_date.strftime('%Y-%m-%d'),
                'enddateymd': end_date.strftime('%Y-%m-%d')
            }

            # Make authenticated request
            data = self._make_authenticated_request('/v2/measure', params, access_token)

            activity_data = []
            activities = data.get('body', {}).get('activities', [])

            for activity in activities:
                # Activity data includes steps, distance, calories, etc.
                activity_data.append({
                    'date': datetime.strptime(activity.get('date'), '%Y-%m-%d') if activity.get('date') else datetime.combine(start_date.date(), datetime.min.time()),
                    'steps': activity.get('steps', 0),
                    'distance': activity.get('distance', 0),  # meters
                    'calories': activity.get('calories', 0),
                    'elevation': activity.get('elevation', 0),
                    'device_id': activity.get('deviceid')
                })

            self.logger.info(f"Fetched {len(activity_data)} activity records from Withings")
            return activity_data

        except TokenExpiredError as e:
            try:
                self._refresh_token(social_auth)
                return cast(List[Dict[str, Any]], self.get_activity_data(user_id, start_date, end_date))
            except TokenExpiredError:
                raise APIError(f"Withings authentication failed and token refresh unsuccessful: {e}")
        except Exception as e:
            self.logger.error(f"Failed to fetch activity data from Withings: {e}")
            raise APIError(f"Withings API error: {e}")

    @withings_circuit_breaker
    def get_weight_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch weight measurements from Withings API"""
        self._check_rate_limit()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")

            # Convert dates to Unix timestamps
            start_timestamp = int(start_date.timestamp())
            end_timestamp = int(end_date.timestamp())

            # Prepare request parameters
            params = {
                'action': 'getmeas',
                'meastype': self.MEASURE_TYPES['weight'],
                'startdate': start_timestamp,
                'enddate': end_timestamp
            }

            # Make authenticated request
            data = self._make_authenticated_request('/v2/measure', params, access_token)

            weight_data = []
            measuregrps = data.get('body', {}).get('measuregrps', [])

            for group in measuregrps:
                # Each group can have multiple measures
                measures = group.get('measures', [])
                for measure in measures:
                    if measure.get('type') == self.MEASURE_TYPES['weight']:
                        # Calculate actual value (Withings uses scaling)
                        value = measure.get('value', 0)
                        unit = measure.get('unit', 0)
                        if unit != 0:
                            value = value * (10 ** unit)

                        # Get measurement source from category
                        category = group.get('category', 1)
                        measurement_source = self._get_measurement_source(category)

                        weight_data.append({
                            'timestamp': datetime.fromtimestamp(group.get('date', 0)),
                            'value': float(value),
                            'device_id': group.get('deviceid'),
                            'measurement_id': group.get('grpid'),
                            'measurement_source': measurement_source,
                            'category': category
                        })

            self.logger.info(f"Fetched {len(weight_data)} weight measurements from Withings")
            return weight_data

        except TokenExpiredError as e:
            try:
                self._refresh_token(social_auth)
                return cast(List[Dict[str, Any]], self.get_weight_data(user_id, start_date, end_date))
            except TokenExpiredError:
                raise APIError(f"Withings authentication failed and token refresh unsuccessful: {e}")
        except Exception as e:
            self.logger.error(f"Failed to fetch weight data from Withings: {e}")
            raise APIError(f"Withings API error: {e}")

    @withings_circuit_breaker
    def get_sleep_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch sleep data from Withings API"""
        self._check_rate_limit()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")

            # Convert dates to Unix timestamps
            start_timestamp = int(start_date.timestamp())
            end_timestamp = int(end_date.timestamp())

            # Prepare request parameters
            params = {
                'action': 'get',
                'startdate': start_timestamp,
                'enddate': end_timestamp
            }

            # Make authenticated request to sleep endpoint
            data = self._make_authenticated_request('/v2/sleep', params, access_token)

            sleep_data = []
            sleep_series = data.get('body', {}).get('series', [])

            for sleep_session in sleep_series:
                # Sleep data includes duration, deep sleep, light sleep, REM, etc.
                sleep_data.append({
                    'timestamp': datetime.fromtimestamp(sleep_session.get('startdate', 0)),
                    'end_timestamp': datetime.fromtimestamp(sleep_session.get('enddate', 0)),
                    'duration': sleep_session.get('data', {}).get('totalsleepduration', 0),  # seconds
                    'deep_sleep_duration': sleep_session.get('data', {}).get('deepsleepduration', 0),
                    'light_sleep_duration': sleep_session.get('data', {}).get('lightsleepduration', 0),
                    'rem_sleep_duration': sleep_session.get('data', {}).get('remsleepduration', 0),
                    'wake_up_count': sleep_session.get('data', {}).get('wakeupcount', 0),
                    'device_id': sleep_session.get('deviceid'),
                    'measurement_source': MeasurementSource.DEVICE  # Sleep is always device-measured
                })

            self.logger.info(f"Fetched {len(sleep_data)} sleep sessions from Withings")
            return sleep_data

        except TokenExpiredError as e:
            try:
                self._refresh_token(social_auth)
                return cast(List[Dict[str, Any]], self.get_sleep_data(user_id, start_date, end_date))
            except TokenExpiredError:
                raise APIError(f"Withings authentication failed and token refresh unsuccessful: {e}")
        except Exception as e:
            self.logger.error(f"Failed to fetch sleep data from Withings: {e}")
            raise APIError(f"Withings API error: {e}")

    @withings_circuit_breaker
    def get_blood_pressure_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch blood pressure data from Withings API"""
        self._check_rate_limit()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")

            # Convert dates to Unix timestamps
            start_timestamp = int(start_date.timestamp())
            end_timestamp = int(end_date.timestamp())

            # Fetch both systolic and diastolic BP in one request
            params = {
                'action': 'getmeas',
                'meastype': f"{self.MEASURE_TYPES['systolic_bp']},{self.MEASURE_TYPES['diastolic_bp']}",
                'startdate': start_timestamp,
                'enddate': end_timestamp
            }

            # Make authenticated request
            data = self._make_authenticated_request('/v2/measure', params, access_token)

            bp_data = []
            measuregrps = data.get('body', {}).get('measuregrps', [])

            # Group measurements by timestamp to pair systolic/diastolic
            bp_readings = {}

            for group in measuregrps:
                timestamp = group.get('date', 0)
                category = group.get('category', 1)
                measurement_source = self._get_measurement_source(category)

                if timestamp not in bp_readings:
                    bp_readings[timestamp] = {
                        'timestamp': datetime.fromtimestamp(timestamp),
                        'systolic': None,
                        'diastolic': None,
                        'device_id': group.get('deviceid'),
                        'measurement_id': group.get('grpid'),
                        'measurement_source': measurement_source,
                        'category': category
                    }

                measures = group.get('measures', [])
                for measure in measures:
                    measure_type = measure.get('type')
                    value = measure.get('value', 0)
                    unit = measure.get('unit', 0)
                    if unit != 0:
                        value = value * (10 ** unit)

                    if measure_type == self.MEASURE_TYPES['systolic_bp']:
                        bp_readings[timestamp]['systolic'] = float(value)
                    elif measure_type == self.MEASURE_TYPES['diastolic_bp']:
                        bp_readings[timestamp]['diastolic'] = float(value)

            # Only include readings with both systolic and diastolic values
            for reading in bp_readings.values():
                if reading['systolic'] is not None and reading['diastolic'] is not None:
                    bp_data.append(reading)

            self.logger.info(f"Fetched {len(bp_data)} blood pressure readings from Withings")
            return bp_data

        except TokenExpiredError as e:
            try:
                self._refresh_token(social_auth)
                return cast(List[Dict[str, Any]], self.get_blood_pressure_data(user_id, start_date, end_date))
            except TokenExpiredError:
                raise APIError(f"Withings authentication failed and token refresh unsuccessful: {e}")
        except Exception as e:
            self.logger.error(f"Failed to fetch blood pressure data from Withings: {e}")
            raise APIError(f"Withings API error: {e}")


class FitbitAPIClient(APIClientBase):
    """Production Fitbit API client"""

    def __init__(self, config: Optional[APIClientConfig] = None):
        super().__init__(Provider.FITBIT, config)

        if not FITBIT_AVAILABLE:
            raise ImportError("fitbit library not available")

    def _refresh_token(self, user_social_auth: UserSocialAuth) -> bool:
        """Refresh Fitbit OAuth2 token"""
        try:
            refresh_token = user_social_auth.extra_data.get('refresh_token')
            if not refresh_token:
                raise TokenExpiredError("No refresh token available")

            # Create Fitbit client for token refresh
            client = fitbit.Fitbit(
                client_id=settings.SOCIAL_AUTH_FITBIT_KEY,
                client_secret=settings.SOCIAL_AUTH_FITBIT_SECRET,
                refresh_token=refresh_token
            )

            # Refresh token
            new_tokens = client.client.refresh_token()

            # Update stored tokens
            user_social_auth.extra_data.update({
                'access_token': new_tokens['access_token'],
                'refresh_token': new_tokens.get('refresh_token', refresh_token),
                'expires_in': new_tokens.get('expires_in'),
                'token_type': new_tokens.get('token_type', 'Bearer')
            })
            user_social_auth.save()

            self.logger.info(f"Successfully refreshed Fitbit token for user {user_social_auth.user.ehr_user_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to refresh Fitbit token: {e}")
            raise TokenExpiredError(f"Token refresh failed: {e}")

    def _create_api_instance(self, access_token: str, refresh_token: str) -> fitbit.Fitbit:
        """Create Fitbit API instance"""
        try:
            client = fitbit.Fitbit(
                client_id=settings.SOCIAL_AUTH_FITBIT_KEY,
                client_secret=settings.SOCIAL_AUTH_FITBIT_SECRET,
                access_token=access_token,
                refresh_token=refresh_token
            )
            return client
        except Exception as e:
            raise APIError(f"Failed to create Fitbit API instance: {e}")

    def _get_measurement_source_from_fitbit_source(self, source: str) -> MeasurementSource:
        """Convert Fitbit source field to measurement source"""
        fitbit_source_mapping = {
            "Aria": MeasurementSource.DEVICE,      # Aria or Aria 2 scale
            "AriaAir": MeasurementSource.DEVICE,   # Aria Air scale
            "Withings": MeasurementSource.DEVICE,  # Withings scale (cross-platform)
            "API": MeasurementSource.USER          # Manual entry or 3rd party integration
        }
        return fitbit_source_mapping.get(source, MeasurementSource.UNKNOWN)

    def _get_user_devices(self, user_id: str) -> Dict[str, str]:
        """Fetch and cache user's Fitbit devices"""
        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")
            refresh_token = social_auth.extra_data.get('refresh_token')

            client = self._create_api_instance(access_token, refresh_token)

            # Get devices from Fitbit API
            devices_response = client.get_devices()

            # Map device types to device IDs
            device_mapping = {}
            for device in devices_response:
                device_id = device.get('id', '')
                device_type = device.get('type', '').lower()
                device_mapping[device_type] = device_id

                # Also map by device version for more specific matching
                device_version = device.get('deviceVersion', '')
                if device_version:
                    device_mapping[device_version.lower()] = device_id

            self.logger.info(f"Fetched {len(device_mapping)} devices for Fitbit user {user_id}")
            return device_mapping

        except Exception as e:
            self.logger.warning(f"Failed to fetch Fitbit devices for user {user_id}: {e}")
            return {}

    def _get_measurement_source_from_fitbit_logtype(self, log_type: str) -> MeasurementSource:
        """Convert Fitbit logType field to measurement source"""
        fitbit_logtype_mapping = {
            "auto_detected": MeasurementSource.DEVICE,  # Automatically detected by device
            "manual": MeasurementSource.USER            # Manually logged or edited by user
        }
        return fitbit_logtype_mapping.get(log_type, MeasurementSource.UNKNOWN)

    @fitbit_circuit_breaker
    def get_heart_rate_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch heart rate data from Fitbit API"""
        self._check_rate_limit()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")
            refresh_token = social_auth.extra_data.get('refresh_token')

            client = self._create_api_instance(access_token, refresh_token)

            # Get user's devices for device ID mapping
            user_devices = self._get_user_devices(user_id)
            primary_device_id = user_devices.get('tracker') or user_devices.get('watch') or (list(user_devices.values())[0] if user_devices else None)

            heart_rate_data = []

            # Fitbit requires daily requests for heart rate data
            current_date = start_date.date()
            end_date_only = end_date.date()

            while current_date <= end_date_only:
                try:
                    # Get heart rate time series data
                    heart_rate_response = client.time_series(
                        resource='activities/heart',
                        base_date=current_date,
                        period='1d'
                    )

                    if heart_rate_response and 'activities-heart' in heart_rate_response:
                        for daily_data in heart_rate_response['activities-heart']:
                            if 'value' in daily_data and 'restingHeartRate' in daily_data['value']:
                                heart_rate_data.append({
                                    'timestamp': datetime.combine(
                                        datetime.strptime(daily_data['dateTime'], '%Y-%m-%d').date(),
                                        datetime.min.time()
                                    ),
                                    'value': float(daily_data['value']['restingHeartRate']),
                                    'heart_rate_type': 'resting',
                                    'device_id': primary_device_id,
                                    'measurement_source': MeasurementSource.DEVICE  # Time series data is device-measured
                                })

                    # Small delay to respect rate limits
                    time.sleep(0.1)

                except Exception as e:
                    self.logger.warning(f"Failed to fetch heart rate for {current_date}: {e}")

                current_date += timedelta(days=1)

            self.logger.info(f"Fetched {len(heart_rate_data)} heart rate measurements from Fitbit")
            return heart_rate_data

        except Exception as e:
            if "401" in str(e) or "unauthorized" in str(e).lower():
                try:
                    self._refresh_token(social_auth)
                    return cast(List[Dict[str, Any]], self.get_heart_rate_data(user_id, start_date, end_date))
                except TokenExpiredError:
                    raise APIError(f"Fitbit authentication failed: {e}")

            self.logger.error(f"Failed to fetch heart rate data from Fitbit: {e}")
            raise APIError(f"Fitbit API error: {e}")

    @fitbit_circuit_breaker
    def get_activity_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch activity data (steps, distance, calories) from Fitbit API"""
        self._check_rate_limit()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")
            refresh_token = social_auth.extra_data.get('refresh_token')

            client = self._create_api_instance(access_token, refresh_token)

            # Get user's devices for device ID mapping
            user_devices = self._get_user_devices(user_id)
            primary_device_id = user_devices.get('tracker') or user_devices.get('watch') or (list(user_devices.values())[0] if user_devices else None)

            # Get steps time series
            steps_response = client.time_series(
                resource='activities/steps',
                base_date=start_date.date(),
                end_date=end_date.date()
            )

            activity_data = []

            if steps_response and 'activities-steps' in steps_response:
                for daily_data in steps_response['activities-steps']:
                    activity_data.append({
                        'date': datetime.combine(
                            datetime.strptime(daily_data['dateTime'], '%Y-%m-%d').date(),
                            datetime.min.time()
                        ),
                        'steps': int(daily_data['value']),
                        'device_id': primary_device_id,
                        'measurement_source': MeasurementSource.DEVICE  # Steps are typically device-measured
                    })

            self.logger.info(f"Fetched {len(activity_data)} activity records from Fitbit")
            return activity_data

        except Exception as e:
            if "401" in str(e) or "unauthorized" in str(e).lower():
                try:
                    self._refresh_token(social_auth)
                    return self.get_activity_data(user_id, start_date, end_date)
                except TokenExpiredError:
                    raise APIError(f"Fitbit authentication failed: {e}")

            self.logger.error(f"Failed to fetch activity data from Fitbit: {e}")
            raise APIError(f"Fitbit API error: {e}")

    @fitbit_circuit_breaker
    def get_weight_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch weight data from Fitbit API with source information"""
        self._check_rate_limit()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")
            refresh_token = social_auth.extra_data.get('refresh_token')

            client = self._create_api_instance(access_token, refresh_token)

            # Get user's devices for device ID mapping
            user_devices = self._get_user_devices(user_id)
            # Weight is typically from a scale (Aria, Aria 2, etc.)
            scale_device_id = user_devices.get('scale') or user_devices.get('aria') or (list(user_devices.values())[0] if user_devices else None)

            weight_data = []

            # Fetch weight logs day by day to get source information
            current_date = start_date.date()
            end_date_only = end_date.date()

            while current_date <= end_date_only:
                try:
                    # Get weight logs for specific date using the weight log API
                    # This provides source information unlike time_series
                    weight_logs = client.get_bodyweight(base_date=current_date)

                    if weight_logs and 'weight' in weight_logs:
                        for weight_entry in weight_logs['weight']:
                            # Parse timestamp from date and time fields
                            entry_date = weight_entry.get('date', current_date.strftime('%Y-%m-%d'))
                            entry_time = weight_entry.get('time', '00:00:00')
                            timestamp_str = f"{entry_date} {entry_time}"

                            try:
                                timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                            except ValueError:
                                # Fallback to date only if time parsing fails
                                timestamp = datetime.combine(current_date, datetime.min.time())

                            # Get measurement source from Fitbit source field
                            fitbit_source = weight_entry.get('source', '')
                            measurement_source = self._get_measurement_source_from_fitbit_source(fitbit_source)

                            weight_data.append({
                                'timestamp': timestamp,
                                'value': float(weight_entry['weight']),
                                'device_id': scale_device_id,
                                'log_id': weight_entry.get('logId'),
                                'measurement_source': measurement_source,
                                'source': fitbit_source,
                                'bmi': weight_entry.get('bmi')
                            })

                    # Small delay to respect rate limits
                    time.sleep(0.1)

                except Exception as e:
                    self.logger.warning(f"Failed to fetch weight for {current_date}: {e}")

                current_date += timedelta(days=1)

            self.logger.info(f"Fetched {len(weight_data)} weight measurements from Fitbit")
            return weight_data

        except Exception as e:
            if "401" in str(e) or "unauthorized" in str(e).lower():
                try:
                    self._refresh_token(social_auth)
                    return self.get_weight_data(user_id, start_date, end_date)
                except TokenExpiredError:
                    raise APIError(f"Fitbit authentication failed: {e}")

            self.logger.error(f"Failed to fetch weight data from Fitbit: {e}")
            raise APIError(f"Fitbit API error: {e}")

    @fitbit_circuit_breaker
    def get_sleep_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch sleep data from Fitbit API with source information"""
        self._check_rate_limit()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")
            refresh_token = social_auth.extra_data.get('refresh_token')

            client = self._create_api_instance(access_token, refresh_token)

            # Get user's devices for device ID mapping
            user_devices = self._get_user_devices(user_id)
            primary_device_id = user_devices.get('tracker') or user_devices.get('watch') or (list(user_devices.values())[0] if user_devices else None)

            sleep_data = []

            # Fetch sleep logs day by day to get source information
            current_date = start_date.date()
            end_date_only = end_date.date()

            while current_date <= end_date_only:
                try:
                    # Get sleep logs for specific date using the sleep log API
                    # This provides logType information (auto_detected vs manual)
                    sleep_logs = client.sleep(date=current_date)

                    if sleep_logs and 'sleep' in sleep_logs:
                        for sleep_entry in sleep_logs['sleep']:
                            # Parse sleep start and end times
                            start_time_str = sleep_entry.get('startTime', '')
                            end_time_str = sleep_entry.get('endTime', '')

                            try:
                                # Parse ISO format timestamps
                                sleep_start = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                                sleep_end = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                            except (ValueError, TypeError):
                                # Fallback to current date if parsing fails
                                sleep_start = datetime.combine(current_date, datetime.min.time())
                                sleep_end = sleep_start + timedelta(hours=8)  # Default 8 hours

                            # Get measurement source from Fitbit logType field
                            fitbit_logtype = sleep_entry.get('logType', '')
                            measurement_source = self._get_measurement_source_from_fitbit_logtype(fitbit_logtype)

                            # Extract key sleep metrics
                            minutes_asleep = sleep_entry.get('minutesAsleep', 0)
                            minutes_awake = sleep_entry.get('minutesAwake', 0)
                            minutes_to_fall_asleep = sleep_entry.get('minutesToFallAsleep', 0)
                            efficiency = sleep_entry.get('efficiency', 0)

                            sleep_data.append({
                                'timestamp': sleep_start,
                                'end_time': sleep_end,
                                'value': minutes_asleep,  # Main value: minutes asleep
                                'unit': 'minutes',
                                'device_id': primary_device_id,
                                'log_id': sleep_entry.get('logId'),
                                'measurement_source': measurement_source,
                                'log_type': fitbit_logtype,
                                'sleep_metrics': {
                                    'minutes_asleep': minutes_asleep,
                                    'minutes_awake': minutes_awake,
                                    'minutes_to_fall_asleep': minutes_to_fall_asleep,
                                    'efficiency': efficiency,
                                    'time_in_bed': sleep_entry.get('timeInBed', 0)
                                }
                            })

                    # Small delay to respect rate limits
                    time.sleep(0.1)

                except Exception as e:
                    self.logger.warning(f"Failed to fetch sleep data for {current_date}: {e}")

                current_date += timedelta(days=1)

            self.logger.info(f"Fetched {len(sleep_data)} sleep records from Fitbit")
            return sleep_data

        except Exception as e:
            if "401" in str(e) or "unauthorized" in str(e).lower():
                try:
                    self._refresh_token(social_auth)
                    return self.get_sleep_data(user_id, start_date, end_date)
                except TokenExpiredError:
                    raise APIError(f"Fitbit authentication failed: {e}")

            self.logger.error(f"Failed to fetch sleep data from Fitbit: {e}")
            raise APIError(f"Fitbit API error: {e}")

    @fitbit_circuit_breaker
    def get_ecg_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch ECG data from Fitbit API"""
        self._check_rate_limit()
        start_time = time.time()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")
            refresh_token = social_auth.extra_data.get('refresh_token')

            client = self._create_api_instance(access_token, refresh_token)

            # Get user's devices for device ID mapping
            user_devices = self._get_user_devices(user_id)
            primary_device_id = user_devices.get('tracker') or user_devices.get('watch') or (list(user_devices.values())[0] if user_devices else None)

            ecg_data = []

            # Fetch ECG logs using pagination
            # Note: ECG API limits to 10 results per request due to large waveform data
            try:
                # Use the fitbit library's direct API call method
                # Format: GET /1/user/-/ecg/list.json?afterDate=YYYY-MM-DD&limit=10&sort=desc
                ecg_response = client.make_request(
                    f'/1/user/-/ecg/list.json',
                    params={
                        'afterDate': start_date.strftime('%Y-%m-%d'),
                        'beforeDate': end_date.strftime('%Y-%m-%d'),
                        'limit': 10,
                        'sort': 'desc'
                    }
                )

                if ecg_response and 'ecgReadings' in ecg_response:
                    for ecg_entry in ecg_response['ecgReadings']:
                        # Parse ISO format timestamp
                        start_time_str = ecg_entry.get('startTime', '')

                        try:
                            # Parse ISO format: "2022-09-28T17:12:30.222"
                            ecg_timestamp = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            # Fallback if parsing fails
                            ecg_timestamp = datetime.now()

                        # All ECG data is device-generated (no manual entry capability)
                        measurement_source = MeasurementSource.DEVICE

                        # Extract key ECG metrics
                        average_heart_rate = ecg_entry.get('averageHeartRate', 0)
                        result_classification = ecg_entry.get('resultClassification', '')
                        waveform_samples = ecg_entry.get('waveformSamples', [])
                        sampling_frequency = ecg_entry.get('samplingFrequencyHz', 0)

                        ecg_data.append({
                            'timestamp': ecg_timestamp,
                            'value': average_heart_rate,  # Main value: average heart rate during ECG
                            'unit': 'bpm',
                            'device_id': primary_device_id,
                            'measurement_source': measurement_source,
                            'ecg_metrics': {
                                'result_classification': result_classification,
                                'sampling_frequency_hz': sampling_frequency,
                                'scaling_factor': ecg_entry.get('scalingFactor', 0),
                                'number_of_samples': ecg_entry.get('numberOfWaveformSamples', 0),
                                'lead_number': ecg_entry.get('leadNumber', 1),
                                'device_name': ecg_entry.get('deviceName', ''),
                                'firmware_version': ecg_entry.get('firmwareVersion', ''),
                                'feature_version': ecg_entry.get('featureVersion', '')
                            },
                            # Store complete waveform data for FHIR SampledData
                            'waveform_data': {
                                'samples': waveform_samples,  # Complete waveform samples
                                'sampling_frequency_hz': sampling_frequency,
                                'scaling_factor': ecg_entry.get('scalingFactor', 0),
                                'number_of_samples': ecg_entry.get('numberOfWaveformSamples', 0),
                                'lead_number': ecg_entry.get('leadNumber', 1),
                                'duration_seconds': (ecg_entry.get('numberOfWaveformSamples', 0) / max(sampling_frequency, 1)) if sampling_frequency else 0
                            }
                        })

            except Exception as e:
                self.logger.warning(f"Failed to fetch ECG data: {e}")

            self.logger.info(f"Fetched {len(ecg_data)} ECG readings from Fitbit")

            # Record metrics
            duration = time.time() - start_time
            metrics.record_sync_operation(
                provider="fitbit",
                operation_type="ecg_fetch",
                status="success",
                duration=duration
            )
            metrics.record_data_points("fitbit", "ecg", len(ecg_data))

            return ecg_data

        except Exception as e:
            if "401" in str(e) or "unauthorized" in str(e).lower():
                try:
                    self._refresh_token(social_auth)
                    return self.get_ecg_data(user_id, start_date, end_date)
                except TokenExpiredError:
                    raise APIError(f"Fitbit authentication failed: {e}")

            # Record error metrics
            duration = time.time() - start_time
            metrics.record_sync_operation(
                provider="fitbit",
                operation_type="ecg_fetch",
                status="error",
                duration=duration
            )
            metrics.record_provider_api_error("fitbit", "api_error")

            self.logger.error(f"Failed to fetch ECG data from Fitbit: {e}")
            raise APIError(f"Fitbit API error: {e}")

    @fitbit_circuit_breaker
    def get_hrv_data(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch HRV (Heart Rate Variability) intraday data from Fitbit API"""
        self._check_rate_limit()

        try:
            social_auth = self._get_user_tokens(user_id)
            access_token = social_auth.extra_data.get('access_token')
            if not access_token:
                raise TokenExpiredError("No access token available")
            refresh_token = social_auth.extra_data.get('refresh_token')

            client = self._create_api_instance(access_token, refresh_token)

            # Get user's devices for device ID mapping
            user_devices = self._get_user_devices(user_id)
            primary_device_id = user_devices.get('tracker') or user_devices.get('watch') or (list(user_devices.values())[0] if user_devices else None)

            hrv_data = []

            # Fetch HRV data day by day (intraday data is per-date)
            current_date = start_date.date()
            end_date_only = end_date.date()

            while current_date <= end_date_only:
                try:
                    # Get HRV intraday data for specific date
                    # Format: GET /1/user/-/hrv/date/YYYY-MM-DD/all.json
                    hrv_response = client.make_request(
                        f'/1/user/-/hrv/date/{current_date.strftime("%Y-%m-%d")}/all.json'
                    )

                    if hrv_response and 'hrv' in hrv_response:
                        for hrv_entry in hrv_response['hrv']:
                            # Parse timestamp: "2021-10-25T09:10:00.000"
                            minute_str = hrv_entry.get('minute', '')

                            try:
                                # Parse ISO format timestamp
                                hrv_timestamp = datetime.fromisoformat(minute_str.replace('Z', '+00:00'))
                            except (ValueError, TypeError):
                                # Fallback if parsing fails
                                hrv_timestamp = datetime.combine(current_date, datetime.min.time())

                            # All HRV data is automatically processed from device sleep data
                            measurement_source = MeasurementSource.DEVICE

                            # Extract HRV metrics (RMSSD is the primary HRV measure)
                            rmssd = hrv_entry.get('value', {}).get('rmssd', 0)
                            coverage = hrv_entry.get('value', {}).get('coverage', 0)
                            hf = hrv_entry.get('value', {}).get('hf', 0)  # High frequency
                            lf = hrv_entry.get('value', {}).get('lf', 0)  # Low frequency

                            # Only include records with valid RMSSD values
                            if rmssd > 0:
                                hrv_data.append({
                                    'timestamp': hrv_timestamp,
                                    'value': rmssd,  # Main value: RMSSD (Root Mean Square of Successive Differences)
                                    'unit': 'ms',
                                    'device_id': primary_device_id,
                                    'measurement_source': measurement_source,
                                    'hrv_metrics': {
                                        'rmssd': rmssd,
                                        'coverage': coverage,
                                        'hf': hf,  # High frequency power
                                        'lf': lf   # Low frequency power
                                    }
                                })

                    # Small delay to respect rate limits
                    time.sleep(0.1)

                except Exception as e:
                    self.logger.warning(f"Failed to fetch HRV data for {current_date}: {e}")

                current_date += timedelta(days=1)

            self.logger.info(f"Fetched {len(hrv_data)} HRV measurements from Fitbit")
            return hrv_data

        except Exception as e:
            if "401" in str(e) or "unauthorized" in str(e).lower():
                try:
                    self._refresh_token(social_auth)
                    return self.get_hrv_data(user_id, start_date, end_date)
                except TokenExpiredError:
                    raise APIError(f"Fitbit authentication failed: {e}")

            self.logger.error(f"Failed to fetch HRV data from Fitbit: {e}")
            raise APIError(f"Fitbit API error: {e}")


class APIClientFactory:
    """Factory for creating API clients"""

    _clients = {
        Provider.WITHINGS: WithingsAPIClient,
        Provider.FITBIT: FitbitAPIClient
    }

    @classmethod
    def create(cls, provider: Provider, config: Optional[APIClientConfig] = None) -> APIClientBase:
        """Create an API client for the given provider"""
        if provider not in cls._clients:
            raise ValueError(f"Unsupported API provider: {provider}")

        try:
            return cls._clients[provider](config)
        except ImportError as e:
            raise APIError(f"API client for {provider.value} not available: {e}")

    @classmethod
    def get_supported_providers(cls) -> List[Provider]:
        """Get list of supported providers"""
        return list(cls._clients.keys())