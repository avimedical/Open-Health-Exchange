"""
Modern health data API clients - Provider-agnostic, unified, type-safe
Handles all health data fetching through unified operations with proper caching and error handling
"""
from __future__ import annotations
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TYPE_CHECKING, cast

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import fitbit
    FITBIT_AVAILABLE = True
except ImportError:
    FITBIT_AVAILABLE = False
    fitbit = None

if TYPE_CHECKING:
    from fitbit import Fitbit as FitbitClient  # pragma: no cover
else:
    FitbitClient = Any  # runtime placeholder for type checking

from django.conf import settings
from social_django.models import UserSocialAuth

from .circuit_breaker import withings_circuit_breaker, fitbit_circuit_breaker
from .health_data_constants import HealthDataType, MeasurementSource, Provider, DateRange
from metrics.collectors import metrics

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class DataQuery:
    """Immutable health data query for batch operations"""
    provider: Provider
    data_type: HealthDataType
    user_id: str
    date_range: DateRange

    @property
    def cache_key(self) -> str:
        """Generate cache key for this query"""
        start_str = self.date_range.start.strftime('%Y%m%d')
        end_str = self.date_range.end.strftime('%Y%m%d')
        return f"health_data:{self.provider.value}:{self.data_type.value}:{self.user_id}:{start_str}-{end_str}"


class APIError(Exception):
    """Base exception for API errors"""
    pass


class TokenExpiredError(APIError):
    """Token has expired and needs refresh"""
    pass


class RateLimitError(APIError):
    """Rate limit exceeded"""
    pass


class UnifiedHealthDataClient:
    """
    Modern health data client using unified batch operations

    All operations go through a single core method for consistency
    Provider-agnostic design using settings configuration
    Unified error handling, token management, and metrics recording
    """

    def __init__(self) -> None:
        self.config = settings.API_CLIENT_CONFIG
        self.logger = logging.getLogger(__name__)

        # Setup session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=self.config['MAX_RETRIES'],
            backoff_factor=self.config['BACKOFF_FACTOR'],
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Rate limiting tracking per provider
        self._request_times: dict[str, list[float]] = defaultdict(list)

    def get_health_data(self, provider: Provider, data_type: HealthDataType, user_id: str, date_range: DateRange) -> list[dict[str, Any]]:
        """
        Get health data for a single query
        Wrapper around unified batch method
        """
        query = DataQuery(provider=provider, data_type=data_type, user_id=user_id, date_range=date_range)
        results = self.fetch_health_data([query])
        return results.get(query.cache_key, [])

    def bulk_fetch_health_data(self, provider: Provider, user_id: str, data_types: list[HealthDataType], date_range: DateRange) -> dict[HealthDataType, list[dict[str, Any]]]:
        """
        Bulk fetch multiple data types for a user
        Wrapper around unified batch method
        """
        if not data_types:
            return {}

        queries = [DataQuery(provider=provider, data_type=data_type, user_id=user_id, date_range=date_range)
                  for data_type in data_types]

        results = self.fetch_health_data(queries)

        # Map results back to data types
        return {
            query.data_type: results.get(query.cache_key, [])
            for query in queries
        }

    def fetch_health_data(self, queries: list[DataQuery]) -> dict[str, list[dict[str, Any]]]:
        """
        Unified method handling all health data fetching operations
        Single source of truth for API operations, caching, and error handling
        """
        if not queries:
            return {}

        try:
            # Group queries by provider for efficient batch processing
            by_provider: dict[Provider, list[DataQuery]] = defaultdict(list)
            for query in queries:
                by_provider[query.provider].append(query)

            results = {}

            # Process each provider's queries
            for provider, provider_queries in by_provider.items():
                provider_results = self._fetch_provider_data(provider, provider_queries)
                results.update(provider_results)

            return results

        except Exception as e:
            self.logger.error(f"Health data batch operation failed: {e}")
            # Return empty results for failed operations
            return {query.cache_key: [] for query in queries}

    def _fetch_provider_data(self, provider: Provider, queries: list[DataQuery]) -> dict[str, list[dict[str, Any]]]:
        """Fetch data for all queries from a specific provider"""
        results = {}

        for query in queries:
            try:
                # Check rate limit for this provider
                self._check_rate_limit(provider)

                # Get provider-specific data
                data = self._fetch_single_query_data(query)
                results[query.cache_key] = data

                # Record success metrics
                metrics.record_sync_operation(
                    provider=provider.value,
                    operation_type=f"{query.data_type.value}_fetch",
                    status="success",
                    duration=0  # We could measure this if needed
                )
                metrics.record_data_points(provider.value, query.data_type.value, len(data))

            except Exception as e:
                self.logger.error(f"Failed to fetch {query.data_type.value} from {provider.value}: {e}")
                results[query.cache_key] = []

                # Record error metrics
                metrics.record_sync_operation(
                    provider=provider.value,
                    operation_type=f"{query.data_type.value}_fetch",
                    status="error",
                    duration=0
                )
                metrics.record_provider_api_error(provider.value, "api_error")

        return results

    def _fetch_single_query_data(self, query: DataQuery) -> list[dict[str, Any]]:
        """Fetch data for a single query using provider-specific logic"""
        # Get user tokens
        social_auth = self._get_user_tokens(query.user_id, query.provider)
        access_token = social_auth.extra_data.get('access_token')

        if not access_token:
            raise TokenExpiredError("No access token available")

        try:
            # Provider-specific data fetching using Python 3.13+ match statement
            match query.provider:
                case Provider.WITHINGS:
                    return cast(list[dict[str, Any]], self._fetch_withings_data(query, social_auth))
                case Provider.FITBIT:
                    return cast(list[dict[str, Any]], self._fetch_fitbit_data(query, social_auth))
                case _:
                    raise APIError(f"Unsupported provider: {query.provider}")

        except TokenExpiredError:
            # Try token refresh once
            try:
                self._refresh_token(social_auth, query.provider)
                # Retry with new token
                match query.provider:
                    case Provider.WITHINGS:
                        return cast(list[dict[str, Any]], self._fetch_withings_data(query, social_auth))
                    case Provider.FITBIT:
                        return cast(list[dict[str, Any]], self._fetch_fitbit_data(query, social_auth))
                    case _:
                        raise APIError(f"Unsupported provider: {query.provider}")
            except TokenExpiredError as e:
                raise APIError(f"Authentication failed for {query.provider.value}: {e}")

    @withings_circuit_breaker
    def _fetch_withings_data(self, query: DataQuery, social_auth: UserSocialAuth) -> list[dict[str, Any]]:
        """Fetch data from Withings API using unified logic"""
        access_token = social_auth.extra_data.get('access_token')
        endpoints = self.config['ENDPOINTS']['withings']

        # Get endpoint and parameters based on data type
        endpoint_info = self._get_withings_endpoint_info(query.data_type)
        endpoint = endpoint_info['endpoint']
        params = endpoint_info['params']

        # Add date range to parameters
        params.update({
            'startdate': int(query.date_range.start.timestamp()),
            'enddate': int(query.date_range.end.timestamp())
        })

        # Make authenticated request
        url = f"{endpoints['base_url']}{endpoint}"
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

        # Process response data based on data type
        return self._process_withings_response(data, query.data_type)

    @fitbit_circuit_breaker
    def _fetch_fitbit_data(self, query: DataQuery, social_auth: UserSocialAuth) -> list[dict[str, Any]]:
        """Fetch data from Fitbit API using unified logic"""
        if not FITBIT_AVAILABLE:
            raise ImportError("Fitbit library not available")

        access_token = social_auth.extra_data.get('access_token')
        refresh_token = social_auth.extra_data.get('refresh_token')

        # Create Fitbit client
        client = fitbit.Fitbit(
            client_id=settings.SOCIAL_AUTH_FITBIT_KEY,
            client_secret=settings.SOCIAL_AUTH_FITBIT_SECRET,
            access_token=access_token,
            refresh_token=refresh_token
        )

        # Get user devices for device ID mapping
        user_devices = self._get_fitbit_user_devices(client, query.user_id)

        # Fetch data based on type using match statement
        match query.data_type:
            case HealthDataType.HEART_RATE:
                return self._fetch_fitbit_heart_rate(client, query, user_devices)
            case HealthDataType.STEPS:
                return self._fetch_fitbit_activity(client, query, user_devices)
            case HealthDataType.WEIGHT:
                return self._fetch_fitbit_weight(client, query, user_devices)
            case HealthDataType.SLEEP:
                return self._fetch_fitbit_sleep(client, query, user_devices)
            case HealthDataType.ECG:
                return self._fetch_fitbit_ecg(client, query, user_devices)
            case HealthDataType.RR_INTERVALS | HealthDataType.HRV:
                return self._fetch_fitbit_hrv(client, query, user_devices)
            case _:
                raise APIError(f"Unsupported Fitbit data type: {query.data_type}")

    def _get_withings_endpoint_info(self, data_type: HealthDataType) -> dict[str, Any]:
        """
        Get Withings endpoint and parameters for data type using centralized configuration

        This method now uses the provider_mappings module for all configuration,
        ensuring consistency across subscription, webhook processing, and data fetching.
        """
        from .provider_mappings import get_data_type_config, Provider as ProviderEnum

        # Get configuration from centralized mapping
        config = get_data_type_config(ProviderEnum.WITHINGS, data_type.value)

        if not config:
            raise APIError(f"Unsupported Withings data type: {data_type.value}")

        # Build endpoint info from configuration
        endpoint_info = {
            'endpoint': config.api_endpoint,
            'params': {}
        }

        # Add action if specified
        if config.api_action:
            endpoint_info['params']['action'] = config.api_action

        # Add meastype if specified (for /v2/measure endpoint)
        if config.meastype is not None:
            if isinstance(config.meastype, list):
                # Multiple meastypes (e.g., blood pressure: systolic + diastolic)
                endpoint_info['params']['meastype'] = ','.join(str(mt) for mt in config.meastype)
            else:
                # Single meastype
                endpoint_info['params']['meastype'] = config.meastype

        self.logger.debug(
            f"Resolved Withings {data_type.value} to endpoint={config.api_endpoint}, "
            f"params={endpoint_info['params']}"
        )

        return endpoint_info

    def _process_withings_response(self, data: dict[str, Any], data_type: HealthDataType) -> list[dict[str, Any]]:
        """Process Withings API response into standardized format"""
        match data_type:
            case HealthDataType.HEART_RATE | HealthDataType.WEIGHT | HealthDataType.BLOOD_PRESSURE:
                return self._process_withings_measurements(data, data_type)
            case HealthDataType.STEPS:
                return self._process_withings_activity(data)
            case HealthDataType.SLEEP:
                return self._process_withings_sleep(data)
            case HealthDataType.ECG:
                return self._process_withings_ecg(data)
            case _:
                return []

    def _process_withings_measurements(self, data: dict[str, Any], data_type: HealthDataType) -> list[dict[str, Any]]:
        """Process Withings measurement data"""
        results = []
        measuregrps = data.get('body', {}).get('measuregrps', [])
        measure_types = self.config['ENDPOINTS']['withings']['measure_types']

        for group in measuregrps:
            measures = group.get('measures', [])
            for measure in measures:
                # Calculate actual value (Withings uses scaling)
                value = measure.get('value', 0)
                unit = measure.get('unit', 0)
                if unit != 0:
                    value = value * (10 ** unit)

                # Get measurement source from category
                category = group.get('category', 1)
                measurement_source = MeasurementSource.DEVICE if category == 1 else MeasurementSource.USER

                # Check if this measure matches our requested type
                measure_type = measure.get('type')
                matches_requested_type = False

                match data_type:
                    case HealthDataType.HEART_RATE:
                        matches_requested_type = measure_type == measure_types['heart_rate']
                    case HealthDataType.WEIGHT:
                        matches_requested_type = measure_type == measure_types['weight']
                    case HealthDataType.BLOOD_PRESSURE:
                        matches_requested_type = measure_type in [measure_types['systolic_bp'], measure_types['diastolic_bp']]

                if matches_requested_type:
                    results.append({
                        'timestamp': datetime.fromtimestamp(group.get('date', 0)),
                        'value': float(value),
                        'device_id': group.get('deviceid'),
                        'measurement_id': group.get('grpid'),
                        'measurement_source': measurement_source,
                        'category': category
                    })

        return results

    def _process_withings_activity(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Process Withings activity data"""
        results = []
        activities = data.get('body', {}).get('activities', [])

        for activity in activities:
            results.append({
                'date': datetime.strptime(activity.get('date'), '%Y-%m-%d') if activity.get('date') else None,
                'steps': activity.get('steps', 0),
                'distance': activity.get('distance', 0),
                'calories': activity.get('calories', 0),
                'elevation': activity.get('elevation', 0),
                'device_id': activity.get('deviceid'),
                'measurement_source': MeasurementSource.DEVICE
            })

        return results

    def _process_withings_sleep(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Process Withings sleep data"""
        results = []
        sleep_series = data.get('body', {}).get('series', [])

        for sleep_session in sleep_series:
            results.append({
                'timestamp': datetime.fromtimestamp(sleep_session.get('startdate', 0)),
                'end_timestamp': datetime.fromtimestamp(sleep_session.get('enddate', 0)),
                'duration': sleep_session.get('data', {}).get('totalsleepduration', 0),
                'deep_sleep_duration': sleep_session.get('data', {}).get('deepsleepduration', 0),
                'light_sleep_duration': sleep_session.get('data', {}).get('lightsleepduration', 0),
                'rem_sleep_duration': sleep_session.get('data', {}).get('remsleepduration', 0),
                'wake_up_count': sleep_session.get('data', {}).get('wakeupcount', 0),
                'device_id': sleep_session.get('deviceid'),
                'measurement_source': MeasurementSource.DEVICE
            })

        return results

    def _process_withings_ecg(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Process Withings ECG data from Heart v2 API

        Response format:
        {
            "status": 0,
            "body": {
                "series": [
                    {
                        "deviceid": "...",
                        "model": 94,
                        "ecg": {
                            "signalid": 557124430,
                            "afib": 0  # 0=normal, 1=AFib detected, 2=inconclusive
                        },
                        "heart_rate": 71,
                        "timestamp": 1752509738,
                        "modified": 1752509778
                    }
                ]
            }
        }
        """
        results = []
        ecg_series = data.get('body', {}).get('series', [])

        # AFib classification mapping
        afib_classification = {
            0: "Normal sinus rhythm",
            1: "Atrial fibrillation detected",
            2: "Inconclusive"
        }

        for ecg_record in ecg_series:
            ecg_data = ecg_record.get('ecg', {})

            # Build standardized ECG record
            record = {
                'timestamp': datetime.fromtimestamp(ecg_record.get('timestamp', 0)),
                'heart_rate': ecg_record.get('heart_rate'),
                'device_id': ecg_record.get('deviceid'),
                'device_model': ecg_record.get('model'),
                'signal_id': ecg_data.get('signalid'),
                'afib_result': ecg_data.get('afib'),
                'afib_classification': afib_classification.get(ecg_data.get('afib', 2), 'Unknown'),
                'modified': datetime.fromtimestamp(ecg_record.get('modified', 0)),
                'measurement_source': MeasurementSource.DEVICE,
                'data_type': HealthDataType.ECG
            }

            # Add QT intervals if available
            if 'qrs' in ecg_data:
                record['qrs_interval'] = ecg_data['qrs']
            if 'pr' in ecg_data:
                record['pr_interval'] = ecg_data['pr']
            if 'qt' in ecg_data:
                record['qt_interval'] = ecg_data['qt']
            if 'qtc' in ecg_data:
                record['qtc_interval'] = ecg_data['qtc']

            results.append(record)

            self.logger.info(
                f"Processed ECG record: signal_id={record['signal_id']}, "
                f"heart_rate={record['heart_rate']}, afib={record['afib_classification']}"
            )

        return results

    def _fetch_fitbit_heart_rate(self, client: 'FitbitClient', query: DataQuery, user_devices: dict[str, str]) -> list[dict[str, Any]]:
        """Fetch Fitbit heart rate data"""
        results = []
        primary_device_id = self._get_primary_fitbit_device(user_devices)

        # Fitbit requires daily requests for heart rate data
        current_date = query.date_range.start.date()
        end_date_only = query.date_range.end.date()

        while current_date <= end_date_only:
            try:
                heart_rate_response = client.time_series(
                    resource='activities/heart',
                    base_date=current_date,
                    period='1d'
                )

                if heart_rate_response and 'activities-heart' in heart_rate_response:
                    for daily_data in heart_rate_response['activities-heart']:
                        if 'value' in daily_data and 'restingHeartRate' in daily_data['value']:
                            results.append({
                                'timestamp': datetime.combine(
                                    datetime.strptime(daily_data['dateTime'], '%Y-%m-%d').date(),
                                    datetime.min.time()
                                ),
                                'value': float(daily_data['value']['restingHeartRate']),
                                'heart_rate_type': 'resting',
                                'device_id': primary_device_id,
                                'measurement_source': MeasurementSource.DEVICE
                            })

                time.sleep(0.1)  # Rate limiting

            except Exception as e:
                self.logger.warning(f"Failed to fetch heart rate for {current_date}: {e}")

            current_date += timedelta(days=1)

        return results

    def _fetch_fitbit_activity(self, client: 'FitbitClient', query: DataQuery, user_devices: dict[str, str]) -> list[dict[str, Any]]:
        """Fetch Fitbit activity (steps) data"""
        primary_device_id = self._get_primary_fitbit_device(user_devices)

        steps_response = client.time_series(
            resource='activities/steps',
            base_date=query.date_range.start.date(),
            end_date=query.date_range.end.date()
        )

        results = []
        if steps_response and 'activities-steps' in steps_response:
            for daily_data in steps_response['activities-steps']:
                results.append({
                    'date': datetime.combine(
                        datetime.strptime(daily_data['dateTime'], '%Y-%m-%d').date(),
                        datetime.min.time()
                    ),
                    'steps': int(daily_data['value']),
                    'device_id': primary_device_id,
                    'measurement_source': MeasurementSource.DEVICE
                })

        return results

    def _fetch_fitbit_weight(self, client: 'FitbitClient', query: DataQuery, user_devices: dict[str, str]) -> list[dict[str, Any]]:
        """Fetch Fitbit weight data"""
        results = []
        scale_device_id = user_devices.get('scale') or user_devices.get('aria') or self._get_primary_fitbit_device(user_devices)
        source_mapping = self.config['ENDPOINTS']['fitbit']['source_mapping']

        current_date = query.date_range.start.date()
        end_date_only = query.date_range.end.date()

        while current_date <= end_date_only:
            try:
                weight_logs = client.get_bodyweight(base_date=current_date)

                if weight_logs and 'weight' in weight_logs:
                    for weight_entry in weight_logs['weight']:
                        entry_date = weight_entry.get('date', current_date.strftime('%Y-%m-%d'))
                        entry_time = weight_entry.get('time', '00:00:00')

                        try:
                            timestamp = datetime.strptime(f"{entry_date} {entry_time}", '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            timestamp = datetime.combine(current_date, datetime.min.time())

                        # Get measurement source
                        fitbit_source = weight_entry.get('source', '')
                        measurement_source = MeasurementSource.DEVICE if source_mapping.get(fitbit_source) == 'device' else MeasurementSource.USER

                        results.append({
                            'timestamp': timestamp,
                            'value': float(weight_entry['weight']),
                            'device_id': scale_device_id,
                            'log_id': weight_entry.get('logId'),
                            'measurement_source': measurement_source,
                            'source': fitbit_source,
                            'bmi': weight_entry.get('bmi')
                        })

                time.sleep(0.1)  # Rate limiting

            except Exception as e:
                self.logger.warning(f"Failed to fetch weight for {current_date}: {e}")

            current_date += timedelta(days=1)

        return results

    def _fetch_fitbit_sleep(self, client: 'FitbitClient', query: DataQuery, user_devices: dict[str, str]) -> list[dict[str, Any]]:
        """Fetch Fitbit sleep data"""
        results = []
        primary_device_id = self._get_primary_fitbit_device(user_devices)
        logtype_mapping = self.config['ENDPOINTS']['fitbit']['logtype_mapping']

        current_date = query.date_range.start.date()
        end_date_only = query.date_range.end.date()

        while current_date <= end_date_only:
            try:
                sleep_logs = client.sleep(date=current_date)

                if sleep_logs and 'sleep' in sleep_logs:
                    for sleep_entry in sleep_logs['sleep']:
                        start_time_str = sleep_entry.get('startTime', '')
                        end_time_str = sleep_entry.get('endTime', '')

                        try:
                            sleep_start = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                            sleep_end = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            sleep_start = datetime.combine(current_date, datetime.min.time())
                            sleep_end = sleep_start + timedelta(hours=8)

                        # Get measurement source
                        fitbit_logtype = sleep_entry.get('logType', '')
                        measurement_source = MeasurementSource.DEVICE if logtype_mapping.get(fitbit_logtype) == 'device' else MeasurementSource.USER

                        results.append({
                            'timestamp': sleep_start,
                            'end_time': sleep_end,
                            'value': sleep_entry.get('minutesAsleep', 0),
                            'unit': 'minutes',
                            'device_id': primary_device_id,
                            'log_id': sleep_entry.get('logId'),
                            'measurement_source': measurement_source,
                            'log_type': fitbit_logtype,
                            'sleep_metrics': {
                                'minutes_asleep': sleep_entry.get('minutesAsleep', 0),
                                'minutes_awake': sleep_entry.get('minutesAwake', 0),
                                'minutes_to_fall_asleep': sleep_entry.get('minutesToFallAsleep', 0),
                                'efficiency': sleep_entry.get('efficiency', 0),
                                'time_in_bed': sleep_entry.get('timeInBed', 0)
                            }
                        })

                time.sleep(0.1)  # Rate limiting

            except Exception as e:
                self.logger.warning(f"Failed to fetch sleep data for {current_date}: {e}")

            current_date += timedelta(days=1)

        return results

    def _fetch_fitbit_ecg(self, client: 'FitbitClient', query: DataQuery, user_devices: dict[str, str]) -> list[dict[str, Any]]:
        """Fetch Fitbit ECG data"""
        results = []
        primary_device_id = self._get_primary_fitbit_device(user_devices)

        try:
            ecg_response = client.make_request(
                f'/1/user/-/ecg/list.json',
                params={
                    'afterDate': query.date_range.start.strftime('%Y-%m-%d'),
                    'beforeDate': query.date_range.end.strftime('%Y-%m-%d'),
                    'limit': 10,
                    'sort': 'desc'
                }
            )

            if ecg_response and 'ecgReadings' in ecg_response:
                for ecg_entry in ecg_response['ecgReadings']:
                    start_time_str = ecg_entry.get('startTime', '')

                    try:
                        ecg_timestamp = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    except (ValueError, TypeError):
                        ecg_timestamp = datetime.now()

                    results.append({
                        'timestamp': ecg_timestamp,
                        'value': ecg_entry.get('averageHeartRate', 0),
                        'unit': 'bpm',
                        'device_id': primary_device_id,
                        'measurement_source': MeasurementSource.DEVICE,
                        'ecg_metrics': {
                            'result_classification': ecg_entry.get('resultClassification', ''),
                            'sampling_frequency_hz': ecg_entry.get('samplingFrequencyHz', 0),
                            'scaling_factor': ecg_entry.get('scalingFactor', 0),
                            'number_of_samples': ecg_entry.get('numberOfWaveformSamples', 0),
                            'lead_number': ecg_entry.get('leadNumber', 1),
                            'device_name': ecg_entry.get('deviceName', ''),
                            'firmware_version': ecg_entry.get('firmwareVersion', ''),
                            'feature_version': ecg_entry.get('featureVersion', '')
                        },
                        'waveform_data': {
                            'samples': ecg_entry.get('waveformSamples', []),
                            'sampling_frequency_hz': ecg_entry.get('samplingFrequencyHz', 0),
                            'scaling_factor': ecg_entry.get('scalingFactor', 0),
                            'number_of_samples': ecg_entry.get('numberOfWaveformSamples', 0),
                            'lead_number': ecg_entry.get('leadNumber', 1),
                            'duration_seconds': (ecg_entry.get('numberOfWaveformSamples', 0) /
                                               max(ecg_entry.get('samplingFrequencyHz', 1), 1))
                        }
                    })

        except Exception as e:
            self.logger.warning(f"Failed to fetch ECG data: {e}")

        return results

    def _fetch_fitbit_hrv(self, client: 'FitbitClient', query: DataQuery, user_devices: dict[str, str]) -> list[dict[str, Any]]:
        """Fetch Fitbit HRV data"""
        results = []
        primary_device_id = self._get_primary_fitbit_device(user_devices)

        current_date = query.date_range.start.date()
        end_date_only = query.date_range.end.date()

        while current_date <= end_date_only:
            try:
                hrv_response = client.make_request(
                    f'/1/user/-/hrv/date/{current_date.strftime("%Y-%m-%d")}/all.json'
                )

                if hrv_response and 'hrv' in hrv_response:
                    for hrv_entry in hrv_response['hrv']:
                        minute_str = hrv_entry.get('minute', '')

                        try:
                            hrv_timestamp = datetime.fromisoformat(minute_str.replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            hrv_timestamp = datetime.combine(current_date, datetime.min.time())

                        rmssd = hrv_entry.get('value', {}).get('rmssd', 0)

                        if rmssd > 0:  # Only include valid readings
                            results.append({
                                'timestamp': hrv_timestamp,
                                'value': rmssd,
                                'unit': 'ms',
                                'device_id': primary_device_id,
                                'measurement_source': MeasurementSource.DEVICE,
                                'hrv_metrics': {
                                    'rmssd': rmssd,
                                    'coverage': hrv_entry.get('value', {}).get('coverage', 0),
                                    'hf': hrv_entry.get('value', {}).get('hf', 0),
                                    'lf': hrv_entry.get('value', {}).get('lf', 0)
                                }
                            })

                time.sleep(0.1)  # Rate limiting

            except Exception as e:
                self.logger.warning(f"Failed to fetch HRV data for {current_date}: {e}")

            current_date += timedelta(days=1)

        return results

    def _get_fitbit_user_devices(self, client: 'FitbitClient', user_id: str) -> dict[str, str]:
        """Fetch and cache user's Fitbit devices"""
        try:
            devices_response = client.get_devices()
            device_mapping = {}

            for device in devices_response:
                device_id = device.get('id', '')
                device_type = device.get('type', '').lower()
                device_mapping[device_type] = device_id

                # Also map by device version
                device_version = device.get('deviceVersion', '')
                if device_version:
                    device_mapping[device_version.lower()] = device_id

            self.logger.info(f"Fetched {len(device_mapping)} devices for Fitbit user {user_id}")
            return device_mapping

        except Exception as e:
            self.logger.warning(f"Failed to fetch Fitbit devices for user {user_id}: {e}")
            return {}

    def _get_primary_fitbit_device(self, user_devices: dict[str, str]) -> str | None:
        """Get primary Fitbit device ID"""
        device_types = self.config['ENDPOINTS']['fitbit']['device_types']

        for device_type in device_types:
            if device_id := user_devices.get(device_type):
                return device_id

        # Return first available device if none found
        return list(user_devices.values())[0] if user_devices else None

    def _check_rate_limit(self, provider: Provider) -> None:
        """Check if we're within rate limits for a provider"""
        current_time = time.time()
        window_start = current_time - self.config['RATE_LIMIT_WINDOW']

        # Remove old requests outside the window
        provider_key = provider.value
        self._request_times[provider_key] = [
            t for t in self._request_times[provider_key] if t > window_start
        ]

        if len(self._request_times[provider_key]) >= self.config['MAX_REQUESTS_PER_WINDOW']:
            sleep_time = (self._request_times[provider_key][0] +
                         self.config['RATE_LIMIT_WINDOW'] - current_time)
            if sleep_time > 0:
                self.logger.warning(f"Rate limit reached for {provider.value}, sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
                # Clean up old requests after sleeping
                current_time = time.time()
                window_start = current_time - self.config['RATE_LIMIT_WINDOW']
                self._request_times[provider_key] = [
                    t for t in self._request_times[provider_key] if t > window_start
                ]

        self._request_times[provider_key].append(current_time)

    def _get_user_tokens(self, user_id: str, provider: Provider) -> UserSocialAuth:
        """Get user's OAuth tokens"""
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()

            user = User.objects.get(ehr_user_id=user_id)
            social_auth = UserSocialAuth.objects.get(
                user=user,
                provider=provider.value
            )
            return social_auth
        except Exception as e:
            raise APIError(f"Failed to get user tokens for {user_id}: {e}")

    def _refresh_token(self, social_auth: UserSocialAuth, provider: Provider) -> bool:
        """Refresh OAuth2 token for provider"""
        try:
            match provider:
                case Provider.WITHINGS:
                    return self._refresh_withings_token(social_auth)
                case Provider.FITBIT:
                    return self._refresh_fitbit_token(social_auth)
                case _:
                    raise APIError(f"Token refresh not supported for {provider}")

        except Exception as e:
            self.logger.error(f"Failed to refresh {provider.value} token: {e}")
            raise TokenExpiredError(f"Token refresh failed: {e}")

    def _refresh_withings_token(self, social_auth: UserSocialAuth) -> bool:
        """Refresh Withings OAuth2 token"""
        refresh_token = social_auth.extra_data.get('refresh_token')
        if not refresh_token:
            raise TokenExpiredError("No refresh token available")

        token_url = self.config['ENDPOINTS']['withings']['token_url']
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
        social_auth.extra_data.update({
            'access_token': body['access_token'],
            'refresh_token': body['refresh_token'],
            'expires_in': body.get('expires_in', 3600),
            'token_type': 'Bearer'
        })
        social_auth.save()

        self.logger.info(f"Successfully refreshed Withings token for user {social_auth.user.ehr_user_id}")
        return True

    def _refresh_fitbit_token(self, social_auth: UserSocialAuth) -> bool:
        """Refresh Fitbit OAuth2 token"""
        if not FITBIT_AVAILABLE:
            raise ImportError("Fitbit library not available")

        refresh_token = social_auth.extra_data.get('refresh_token')
        if not refresh_token:
            raise TokenExpiredError("No refresh token available")

        client = fitbit.Fitbit(
            client_id=settings.SOCIAL_AUTH_FITBIT_KEY,
            client_secret=settings.SOCIAL_AUTH_FITBIT_SECRET,
            refresh_token=refresh_token
        )

        new_tokens = client.client.refresh_token()

        social_auth.extra_data.update({
            'access_token': new_tokens['access_token'],
            'refresh_token': new_tokens.get('refresh_token', refresh_token),
            'expires_in': new_tokens.get('expires_in'),
            'token_type': new_tokens.get('token_type', 'Bearer')
        })
        social_auth.save()

        self.logger.info(f"Successfully refreshed Fitbit token for user {social_auth.user.ehr_user_id}")
        return True

    def get_client_stats(self) -> dict[str, Any]:
        """Get client configuration and status"""
        return {
            'max_retries': self.config['MAX_RETRIES'],
            'timeout': self.config['TIMEOUT'],
            'rate_limit_window': self.config['RATE_LIMIT_WINDOW'],
            'max_requests_per_window': self.config['MAX_REQUESTS_PER_WINDOW'],
            'supported_providers': [Provider.WITHINGS.value, Provider.FITBIT.value],
            'fitbit_available': FITBIT_AVAILABLE
        }


# Global service instance
_unified_client: UnifiedHealthDataClient | None = None


def get_unified_health_data_client() -> UnifiedHealthDataClient:
    """Lazy singleton for global client instance"""
    global _unified_client
    if _unified_client is None:
        _unified_client = UnifiedHealthDataClient()
    return _unified_client


