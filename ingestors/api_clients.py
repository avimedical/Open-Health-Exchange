"""
Modern health data API clients - Provider-agnostic, unified, type-safe
Handles all health data fetching through unified operations with proper caching and error handling
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import requests
from django.utils import dateparse
from django.utils import timezone as django_timezone
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

from metrics.collectors import metrics

from .circuit_breaker import (
    fitbit_circuit_breaker,
    get_fitbit_circuit_breaker,
    get_withings_circuit_breaker,
    withings_circuit_breaker,
)
from .health_data_constants import DateRange, HealthDataType, MeasurementSource, Provider

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
        start_str = self.date_range.start.strftime("%Y%m%d")
        end_str = self.date_range.end.strftime("%Y%m%d")
        return f"health_data:{self.provider.value}:{self.data_type.value}:{self.user_id}:{start_str}-{end_str}"


class APIError(Exception):
    """Base exception for API errors"""


class TokenExpiredError(APIError):
    """Token has expired and needs refresh"""


class RateLimitError(APIError):
    """Rate limit exceeded"""


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
            total=self.config["MAX_RETRIES"],
            backoff_factor=self.config["BACKOFF_FACTOR"],
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Rate limiting tracking per provider
        self._request_times: dict[str, list[float]] = defaultdict(list)
        # Server-reported Fitbit rate limit state (from response headers)
        self._fitbit_rate_limit_info: dict[str, Any] = {}

    def get_health_data(
        self, provider: Provider, data_type: HealthDataType, user_id: str, date_range: DateRange
    ) -> list[dict[str, Any]]:
        """
        Get health data for a single query
        Wrapper around unified batch method
        """
        query = DataQuery(provider=provider, data_type=data_type, user_id=user_id, date_range=date_range)
        results = self.fetch_health_data([query])
        return results.get(query.cache_key, [])

    def bulk_fetch_health_data(
        self, provider: Provider, user_id: str, data_types: list[HealthDataType], date_range: DateRange
    ) -> dict[HealthDataType, list[dict[str, Any]]]:
        """
        Bulk fetch multiple data types for a user
        Wrapper around unified batch method
        """
        if not data_types:
            return {}

        queries = [
            DataQuery(provider=provider, data_type=data_type, user_id=user_id, date_range=date_range)
            for data_type in data_types
        ]

        results = self.fetch_health_data(queries)

        # Map results back to data types
        return {query.data_type: results.get(query.cache_key, []) for query in queries}

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
                # Check rate limit for this provider+user combination
                self._check_rate_limit(provider, query.user_id)

                # Get provider-specific data
                data = self._fetch_single_query_data(query)
                results[query.cache_key] = data

                # Record success metrics
                metrics.record_sync_operation(
                    provider=provider.value,
                    operation_type=f"{query.data_type.value}_fetch",
                    status="success",
                    duration=0,  # We could measure this if needed
                )
                metrics.record_data_points(provider.value, query.data_type.value, len(data))

            except Exception as e:
                self.logger.error(f"Failed to fetch {query.data_type.value} from {provider.value}: {e}")
                results[query.cache_key] = []

                # Record error metrics
                metrics.record_sync_operation(
                    provider=provider.value, operation_type=f"{query.data_type.value}_fetch", status="error", duration=0
                )
                metrics.record_provider_api_error(provider.value, "api_error")

        return results

    def _fetch_single_query_data(self, query: DataQuery) -> list[dict[str, Any]]:
        """Fetch data for a single query using provider-specific logic"""
        # Get user tokens
        social_auth = self._get_user_tokens(query.user_id, query.provider)
        access_token = social_auth.extra_data.get("access_token")

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
                # Refresh from DB to ensure we have the latest token data
                social_auth.refresh_from_db()
                # Reset circuit breaker after successful token refresh to allow retry
                match query.provider:
                    case Provider.WITHINGS:
                        get_withings_circuit_breaker().force_close()
                    case Provider.FITBIT:
                        get_fitbit_circuit_breaker().force_close()
                # Retry with new token
                match query.provider:
                    case Provider.WITHINGS:
                        return cast(list[dict[str, Any]], self._fetch_withings_data(query, social_auth))
                    case Provider.FITBIT:
                        return cast(list[dict[str, Any]], self._fetch_fitbit_data(query, social_auth))
                    case _:
                        raise APIError(f"Unsupported provider: {query.provider}")
            except (TokenExpiredError, APIError) as e:
                # TokenExpiredError = transient refresh failure, APIError = permanent failure (no refresh_token)
                raise APIError(f"Authentication failed for {query.provider.value}: {e}")

    @withings_circuit_breaker
    def _fetch_withings_data(self, query: DataQuery, social_auth: UserSocialAuth) -> list[dict[str, Any]]:
        """Fetch data from Withings API using unified logic"""
        access_token = social_auth.extra_data.get("access_token")
        endpoints = self.config["ENDPOINTS"]["withings"]

        # Get endpoint and parameters based on data type
        endpoint_info = self._get_withings_endpoint_info(query.data_type)
        endpoint = endpoint_info["endpoint"]
        params = endpoint_info["params"].copy()

        # Add date range parameters based on endpoint's expected format
        date_format = endpoint_info.get("date_format", "unix")
        if date_format == "ymd":
            # Getactivity, Getsummary use YYYY-MM-DD strings
            params["startdateymd"] = query.date_range.start.strftime("%Y-%m-%d")
            params["enddateymd"] = query.date_range.end.strftime("%Y-%m-%d")
        else:
            # Getmeas, Heart v2, Sleep v2 Get use unix timestamps
            params["startdate"] = int(query.date_range.start.timestamp())
            params["enddate"] = int(query.date_range.end.timestamp())

        url = f"{endpoints['base_url']}{endpoint}"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/x-www-form-urlencoded"}

        # Check if we need to make multiple calls for different meastypes
        # (Withings deprecated multi-meastype requests like "meastype=9,10")
        meastype_list = params.pop("meastype_list", None)
        if meastype_list:
            # Make separate paginated API calls for each meastype and merge results by grpid
            # Blood pressure has same grpid for systolic/diastolic, so we need to merge measures
            measuregrps_by_id: dict[int, dict[str, Any]] = {}

            for meastype in meastype_list:
                call_params = params.copy()
                call_params["meastype"] = meastype

                self.logger.debug(f"Fetching Withings {query.data_type.value} with meastype={meastype}")
                data = self._withings_paginated_request(url, call_params, headers)

                # Merge measuregrps by grpid (same reading can have multiple measures)
                measuregrps = data.get("body", {}).get("measuregrps", [])
                for grp in measuregrps:
                    grpid = grp.get("grpid")
                    if grpid in measuregrps_by_id:
                        # Merge measures from this meastype into existing group
                        measuregrps_by_id[grpid]["measures"].extend(grp.get("measures", []))
                    else:
                        # New group
                        measuregrps_by_id[grpid] = grp

            # Create merged response with all unique measuregrps
            merged_data: dict[str, Any] = {"status": 0, "body": {"measuregrps": list(measuregrps_by_id.values())}}
            return self._process_withings_response(merged_data, query.data_type)

        # Single meastype or no meastype - make paginated API call
        data = self._withings_paginated_request(url, params, headers)

        # Process response data based on data type
        return self._process_withings_response(data, query.data_type)

    @fitbit_circuit_breaker
    def _fetch_fitbit_data(self, query: DataQuery, social_auth: UserSocialAuth) -> list[dict[str, Any]]:
        """Fetch data from Fitbit API using unified logic"""
        if not FITBIT_AVAILABLE:
            raise ImportError("Fitbit library not available")

        access_token = social_auth.extra_data.get("access_token")
        refresh_token = social_auth.extra_data.get("refresh_token")

        # Create Fitbit client
        client = fitbit.Fitbit(
            client_id=settings.SOCIAL_AUTH_FITBIT_KEY,
            client_secret=settings.SOCIAL_AUTH_FITBIT_SECRET,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        # Install response hook to capture Fitbit rate limit headers
        def _capture_rate_limit_headers(response, *args, **kwargs):
            remaining = response.headers.get("Fitbit-Rate-Limit-Remaining")
            reset = response.headers.get("Fitbit-Rate-Limit-Reset")
            if remaining is not None:
                self._fitbit_rate_limit_info[query.user_id] = {
                    "remaining": int(remaining),
                    "reset_seconds": int(reset) if reset else None,
                    "updated_at": time.time(),
                }
                if int(remaining) < 10:
                    self.logger.warning(
                        f"Fitbit rate limit low for user {query.user_id}: "
                        f"{remaining} requests remaining, resets in {reset}s"
                    )
            return response

        client.client.session.hooks["response"].append(_capture_rate_limit_headers)

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

    # Withings numeric error status codes that indicate authentication failure
    _WITHINGS_AUTH_FAILED_STATUSES = frozenset({100, 101, 102, 200, 401})
    _WITHINGS_UNAUTHORIZED_STATUSES = frozenset({214, 277})

    def _check_withings_error(self, data: dict[str, Any]) -> None:
        """Check Withings response for errors and raise appropriate exceptions.

        Handles both numeric status codes (per official API docs) and
        string-based error messages as fallback.
        """
        status = data.get("status", 0)
        if status == 0:
            return

        error_msg = data.get("error", f"Withings API error (status {status})")

        # Check numeric status code families (official Withings API docs)
        if status in self._WITHINGS_AUTH_FAILED_STATUSES:
            raise TokenExpiredError(f"Authentication failed (status {status}): {error_msg}")
        if status in self._WITHINGS_UNAUTHORIZED_STATUSES:
            raise APIError(f"Unauthorized (status {status}): {error_msg}")

        # Fallback: check string-based error messages
        error_lower = str(error_msg).lower()
        if "invalid_token" in error_lower or "unauthorized" in error_lower or "invalid session" in error_lower:
            raise TokenExpiredError(f"Token expired: {error_msg}")

        raise APIError(f"Withings API error (status {status}): {error_msg}")

    def _withings_paginated_request(
        self,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        max_pages: int = 10,
    ) -> dict[str, Any]:
        """Make Withings API request with pagination support.

        Withings endpoints return 'more' and 'offset' fields when results
        are paginated. This method handles automatic page fetching.
        """
        all_data: dict[str, Any] | None = None
        offset: int | None = None

        for page in range(max_pages):
            call_params = params.copy()
            if offset is not None:
                call_params["offset"] = offset

            response = self.session.post(url, data=call_params, headers=headers)
            response.raise_for_status()
            data = response.json()

            self._check_withings_error(data)

            if all_data is None:
                all_data = data
            else:
                self._merge_paginated_body(all_data, data)

            # Check for more pages
            body = data.get("body", {})
            more = body.get("more")
            if more in (0, False, None):
                break
            offset = body.get("offset")
            if offset is None:
                break

            self.logger.debug(f"Withings pagination: page {page + 1}, offset={offset}")
        else:
            # Loop completed without break: max_pages exhausted but more data available
            self.logger.warning(
                f"Withings pagination limit reached: fetched {max_pages} pages but more data may be available "
                f"(url={url}, action={params.get('action', 'unknown')})"
            )

        return all_data or {"status": 0, "body": {}}

    @staticmethod
    def _merge_paginated_body(target: dict[str, Any], source: dict[str, Any]) -> None:
        """Merge paginated Withings response body into accumulated target.

        Handles the different body structures across endpoints:
        - measuregrps (getmeas)
        - activities (getactivity)
        - series (heart, sleep)
        """
        target_body = target.get("body", {})
        source_body = source.get("body", {})

        for key in ("measuregrps", "activities", "series"):
            if key in source_body:
                if key not in target_body:
                    target_body[key] = []
                target_body[key].extend(source_body[key])

    def _get_withings_endpoint_info(self, data_type: HealthDataType) -> dict[str, Any]:
        """
        Get Withings endpoint and parameters for data type using centralized configuration

        This method now uses the provider_mappings module for all configuration,
        ensuring consistency across subscription, webhook processing, and data fetching.
        """
        from .provider_mappings import Provider as ProviderEnum
        from .provider_mappings import get_data_type_config

        # Get configuration from centralized mapping
        config = get_data_type_config(ProviderEnum.WITHINGS, data_type.value)

        if not config:
            raise APIError(f"Unsupported Withings data type: {data_type.value}")

        # Build endpoint info from configuration
        params: dict[str, Any] = {}

        # Add action if specified
        if config.api_action:
            params["action"] = config.api_action

        # Add category=1 for getmeas to filter real device measures only (not user objectives)
        if config.api_action == "getmeas":
            params["category"] = 1

        # Add meastype if specified (for /measure endpoint)
        # Note: Withings deprecated multi-meastype requests (e.g., "meastype=9,10")
        # For blood pressure and temperature, we need to make separate calls
        if config.meastype is not None:
            if isinstance(config.meastype, list):
                # Store list of meastypes to handle separately
                # Will make multiple API calls and merge results
                params["meastype_list"] = config.meastype
            else:
                # Single meastype
                params["meastype"] = config.meastype

        # Add data_fields if specified (for sleep getsummary, activity, etc.)
        if config.data_fields:
            params["data_fields"] = config.data_fields

        endpoint_info = {
            "endpoint": config.api_endpoint,
            "params": params,
            "date_format": config.date_format,
        }

        self.logger.debug(
            f"Resolved Withings {data_type.value} to endpoint={config.api_endpoint}, params={endpoint_info['params']}"
        )

        return endpoint_info

    def _process_withings_response(self, data: dict[str, Any], data_type: HealthDataType) -> list[dict[str, Any]]:
        """Process Withings API response into standardized format"""
        match data_type:
            case (
                HealthDataType.HEART_RATE
                | HealthDataType.WEIGHT
                | HealthDataType.BLOOD_PRESSURE
                | HealthDataType.TEMPERATURE
                | HealthDataType.SPO2
                | HealthDataType.FAT_MASS
                | HealthDataType.PULSE_WAVE_VELOCITY
                | HealthDataType.GLUCOSE
            ):
                return self._process_withings_measurements(data, data_type)
            case HealthDataType.STEPS:
                return self._process_withings_activity(data)
            case HealthDataType.SLEEP:
                return self._process_withings_sleep(data)
            case HealthDataType.ECG:
                return self._process_withings_ecg(data)
            case HealthDataType.RR_INTERVALS:
                return self._process_withings_rr_intervals(data)
            case _:
                self.logger.warning(f"No processor for Withings data type: {data_type}")
                return []

    def _process_withings_measurements(self, data: dict[str, Any], data_type: HealthDataType) -> list[dict[str, Any]]:
        """Process Withings measurement data.

        Uses provider_mappings as the single source of truth for meastype matching,
        eliminating the need for a manual match block or settings.measure_types lookup.
        """
        from .provider_mappings import Provider as ProviderEnum
        from .provider_mappings import get_data_type_config

        config = get_data_type_config(ProviderEnum.WITHINGS, data_type.value)
        if not config or config.meastype is None:
            self.logger.warning(f"No meastype configured for {data_type.value} — cannot match measurements")
            return []

        # Build set of expected meastypes from the single source of truth
        expected_meastypes = set(config.meastype if isinstance(config.meastype, list) else [config.meastype])

        # Blood pressure requires special handling: pair systolic and diastolic
        # into a single record with a dict value, as the transformer expects
        if data_type == HealthDataType.BLOOD_PRESSURE:
            return self._process_withings_blood_pressure(data, expected_meastypes)

        results = []
        measuregrps = data.get("body", {}).get("measuregrps", [])

        for group in measuregrps:
            measures = group.get("measures", [])
            for measure in measures:
                measure_type = measure.get("type")
                if measure_type not in expected_meastypes:
                    continue

                # Calculate actual value (Withings uses scaling)
                value = measure.get("value", 0)
                unit = measure.get("unit", 0)
                if unit != 0:
                    value = value * (10**unit)

                # Get measurement source from category
                category = group.get("category", 1)
                measurement_source = MeasurementSource.DEVICE if category == 1 else MeasurementSource.USER

                results.append(
                    {
                        "timestamp": datetime.fromtimestamp(group.get("date", 0), tz=UTC),
                        "value": float(value),
                        "device_id": group.get("deviceid"),
                        "measurement_id": group.get("grpid"),
                        "measurement_source": measurement_source,
                        "category": category,
                    }
                )

        return results

    def _process_withings_blood_pressure(
        self, data: dict[str, Any], expected_meastypes: set[int]
    ) -> list[dict[str, Any]]:
        """Process Withings blood pressure data, pairing systolic and diastolic into single records.

        Withings meastype 10 = Systolic, meastype 9 = Diastolic.
        The transformer expects {"systolic": X, "diastolic": Y} as the value.
        """
        SYSTOLIC_MEASTYPE = 10
        DIASTOLIC_MEASTYPE = 9

        results = []
        measuregrps = data.get("body", {}).get("measuregrps", [])

        for group in measuregrps:
            measures = group.get("measures", [])
            systolic = None
            diastolic = None

            for measure in measures:
                measure_type = measure.get("type")
                if measure_type not in expected_meastypes:
                    continue

                # Calculate actual value (Withings uses scaling)
                value = measure.get("value", 0)
                unit = measure.get("unit", 0)
                if unit != 0:
                    value = value * (10**unit)

                if measure_type == SYSTOLIC_MEASTYPE:
                    systolic = float(value)
                elif measure_type == DIASTOLIC_MEASTYPE:
                    diastolic = float(value)

            if systolic is not None and diastolic is not None:
                category = group.get("category", 1)
                measurement_source = MeasurementSource.DEVICE if category == 1 else MeasurementSource.USER

                results.append(
                    {
                        "timestamp": datetime.fromtimestamp(group.get("date", 0), tz=UTC),
                        "value": {"systolic": systolic, "diastolic": diastolic},
                        "device_id": group.get("deviceid"),
                        "measurement_id": group.get("grpid"),
                        "measurement_source": measurement_source,
                        "category": category,
                    }
                )
            else:
                grpid = group.get("grpid")
                self.logger.warning(
                    f"Incomplete blood pressure reading (grpid={grpid}): "
                    f"systolic={'present' if systolic is not None else 'missing'}, "
                    f"diastolic={'present' if diastolic is not None else 'missing'}"
                )

        return results

    def _process_withings_activity(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Process Withings activity data"""
        results = []
        activities = data.get("body", {}).get("activities", [])

        for activity in activities:
            date_str = activity.get("date")
            parsed_date = None
            if date_str:
                parsed_date = dateparse.parse_date(date_str)
                if parsed_date:
                    parsed_date = datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)
            results.append(
                {
                    "date": parsed_date,
                    "original_date": date_str,
                    "steps": activity.get("steps", 0),
                    "distance": activity.get("distance", 0),
                    "calories": activity.get("calories", 0),
                    "elevation": activity.get("elevation", 0),
                    "device_id": activity.get("deviceid"),
                    "measurement_source": MeasurementSource.DEVICE,
                }
            )

        return results

    def _process_withings_sleep(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Process Withings sleep data from getsummary action.

        The getsummary response has summary fields nested under a "data" key within
        each series item, with aggregated durations and quality metrics.
        """
        results = []
        sleep_series = data.get("body", {}).get("series", [])

        for sleep_session in sleep_series:
            session_data = sleep_session.get("data", {})
            results.append(
                {
                    "timestamp": datetime.fromtimestamp(sleep_session.get("startdate", 0), tz=UTC),
                    "end_timestamp": datetime.fromtimestamp(sleep_session.get("enddate", 0), tz=UTC),
                    "duration": session_data.get("total_sleep_time", 0),
                    "deep_sleep_duration": session_data.get("deepsleepduration", 0),
                    "light_sleep_duration": session_data.get("lightsleepduration", 0),
                    "rem_sleep_duration": session_data.get("remsleepduration", 0),
                    "wake_up_count": session_data.get("wakeupcount", 0),
                    "sleep_score": session_data.get("sleep_score"),
                    "sleep_efficiency": session_data.get("sleep_efficiency"),
                    "hr_average": session_data.get("hr_average"),
                    "hr_min": session_data.get("hr_min"),
                    "hr_max": session_data.get("hr_max"),
                    "rr_average": session_data.get("rr_average"),
                    "rr_min": session_data.get("rr_min"),
                    "rr_max": session_data.get("rr_max"),
                    "device_id": sleep_session.get("deviceid"),
                    "measurement_source": MeasurementSource.DEVICE,
                }
            )

        return results

    def _process_withings_rr_intervals(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Process Withings RR interval data from /v2/sleep?action=get.

        The get response returns high-frequency data per sleep segment:
        {
            "body": {
                "series": [
                    {
                        "startdate": 1594159200,
                        "enddate": 1594162800,
                        "state": 0,
                        "hr": {"1594159200": 65, ...},
                        "rr": {"1594159200": 920, ...},
                        "snoring": {"1594159200": 0, ...}
                    }
                ]
            }
        }

        Each entry in "rr" is timestamp → RR interval in milliseconds.
        """
        results = []
        sleep_series = data.get("body", {}).get("series", [])

        for segment in sleep_series:
            rr_data = segment.get("rr", {})
            hr_data = segment.get("hr", {})
            device_id = segment.get("deviceid")

            if not rr_data:
                continue

            for ts_str, rr_value in rr_data.items():
                try:
                    timestamp = datetime.fromtimestamp(int(ts_str), tz=UTC)
                except (ValueError, OSError):
                    self.logger.warning(f"Invalid RR interval timestamp: {ts_str}")
                    continue

                result = {
                    "timestamp": timestamp,
                    "value": float(rr_value),
                    "device_id": device_id,
                    "measurement_source": MeasurementSource.DEVICE,
                }

                # Include corresponding heart rate if available
                if ts_str in hr_data:
                    result["hr"] = hr_data[ts_str]

                results.append(result)

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
        ecg_series = data.get("body", {}).get("series", [])

        # AFib classification mapping
        afib_classification = {0: "Normal sinus rhythm", 1: "Atrial fibrillation detected", 2: "Inconclusive"}

        for ecg_record in ecg_series:
            ecg_data = ecg_record.get("ecg", {})

            # Build standardized ECG record
            record = {
                "timestamp": datetime.fromtimestamp(ecg_record.get("timestamp", 0), tz=UTC),
                "heart_rate": ecg_record.get("heart_rate"),
                "device_id": ecg_record.get("deviceid"),
                "device_model": ecg_record.get("model"),
                "signal_id": ecg_data.get("signalid"),
                "afib_result": ecg_data.get("afib"),
                "afib_classification": afib_classification.get(ecg_data.get("afib", 2), "Unknown"),
                "modified": datetime.fromtimestamp(ecg_record.get("modified", 0), tz=UTC),
                "measurement_source": MeasurementSource.DEVICE,
                "data_type": HealthDataType.ECG,
            }

            # Add QT intervals if available
            if "qrs" in ecg_data:
                record["qrs_interval"] = ecg_data["qrs"]
            if "pr" in ecg_data:
                record["pr_interval"] = ecg_data["pr"]
            if "qt" in ecg_data:
                record["qt_interval"] = ecg_data["qt"]
            if "qtc" in ecg_data:
                record["qtc_interval"] = ecg_data["qtc"]

            results.append(record)

            self.logger.info(
                f"Processed ECG record: signal_id={record['signal_id']}, "
                f"heart_rate={record['heart_rate']}, afib={record['afib_classification']}"
            )

        return results

    def _fetch_fitbit_heart_rate(
        self, client: FitbitClient, query: DataQuery, user_devices: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch Fitbit heart rate data using date-range endpoint (max 1 year)"""
        results = []
        primary_device_id = self._get_primary_fitbit_device(user_devices)

        heart_rate_response = client.time_series(
            resource="activities/heart",
            base_date=query.date_range.start.date(),
            end_date=query.date_range.end.date(),
        )

        if heart_rate_response and "activities-heart" in heart_rate_response:
            for daily_data in heart_rate_response["activities-heart"]:
                if "value" not in daily_data or "restingHeartRate" not in daily_data["value"]:
                    continue

                parsed_date = dateparse.parse_date(daily_data["dateTime"])
                if not parsed_date:
                    continue

                timestamp = datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)
                value = daily_data["value"]

                # Extract heart rate zones if present (Fat Burn, Cardio, Peak, Out of Range)
                heart_rate_zones = None
                if "heartRateZones" in value:
                    heart_rate_zones = [
                        {
                            "name": zone.get("name"),
                            "min": zone.get("min"),
                            "max": zone.get("max"),
                            "minutes": zone.get("minutes", 0),
                            "calories_out": zone.get("caloriesOut", 0),
                        }
                        for zone in value["heartRateZones"]
                    ]

                results.append(
                    {
                        "timestamp": timestamp,
                        "value": float(value["restingHeartRate"]),
                        "heart_rate_type": "resting",
                        "heart_rate_zones": heart_rate_zones,
                        "device_id": primary_device_id,
                        "measurement_source": MeasurementSource.DEVICE,
                    }
                )

        return results

    def _fetch_fitbit_activity(
        self, client: FitbitClient, query: DataQuery, user_devices: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch Fitbit activity (steps) data"""
        primary_device_id = self._get_primary_fitbit_device(user_devices)

        steps_response = client.time_series(
            resource="activities/steps", base_date=query.date_range.start.date(), end_date=query.date_range.end.date()
        )

        results = []
        if steps_response and "activities-steps" in steps_response:
            for daily_data in steps_response["activities-steps"]:
                parsed_date = dateparse.parse_date(daily_data["dateTime"])
                if parsed_date:
                    date_timestamp = datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)
                    results.append(
                        {
                            "date": date_timestamp,
                            "steps": int(daily_data["value"]),
                            "device_id": primary_device_id,
                            "measurement_source": MeasurementSource.DEVICE,
                        }
                    )

        return results

    def _fetch_fitbit_weight(
        self, client: FitbitClient, query: DataQuery, user_devices: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch Fitbit weight data using date-range endpoint (max 31 days)"""
        results = []
        scale_device_id = (
            user_devices.get("scale") or user_devices.get("aria") or self._get_primary_fitbit_device(user_devices)
        )
        source_mapping = self.config["ENDPOINTS"]["fitbit"]["source_mapping"]

        weight_logs = client.get_bodyweight(
            base_date=query.date_range.start.date(),
            end_date=query.date_range.end.date(),
        )

        if weight_logs and "weight" in weight_logs:
            for weight_entry in weight_logs["weight"]:
                entry_date = weight_entry.get("date", query.date_range.start.strftime("%Y-%m-%d"))
                entry_time = weight_entry.get("time", "00:00:00")

                try:
                    timestamp_dt = dateparse.parse_datetime(f"{entry_date} {entry_time}")
                    if timestamp_dt:
                        timestamp = (
                            timestamp_dt.replace(tzinfo=UTC)
                            if timestamp_dt.tzinfo is None
                            else timestamp_dt.astimezone(UTC)
                        )
                    else:
                        parsed_date = dateparse.parse_date(entry_date)
                        fallback = parsed_date or query.date_range.start.date()
                        timestamp = datetime.combine(fallback, datetime.min.time(), tzinfo=UTC)
                except ValueError:
                    parsed_date = dateparse.parse_date(entry_date)
                    fallback = parsed_date or query.date_range.start.date()
                    timestamp = datetime.combine(fallback, datetime.min.time(), tzinfo=UTC)

                fitbit_source = weight_entry.get("source", "")
                measurement_source = (
                    MeasurementSource.DEVICE
                    if source_mapping.get(fitbit_source) == "device"
                    else MeasurementSource.USER
                )

                results.append(
                    {
                        "timestamp": timestamp,
                        "value": float(weight_entry["weight"]),
                        "device_id": scale_device_id,
                        "log_id": weight_entry.get("logId"),
                        "measurement_source": measurement_source,
                        "source": fitbit_source,
                        "bmi": weight_entry.get("bmi"),
                    }
                )

        return results

    def _fetch_fitbit_sleep(
        self, client: FitbitClient, query: DataQuery, user_devices: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch Fitbit sleep data using v1.2 date-range endpoint (max 100 days) with sleep stages"""
        results = []
        primary_device_id = self._get_primary_fitbit_device(user_devices)
        logtype_mapping = self.config["ENDPOINTS"]["fitbit"]["logtype_mapping"]
        base_url = self.config["ENDPOINTS"]["fitbit"]["base_url"]

        start_date = query.date_range.start.strftime("%Y-%m-%d")
        end_date = query.date_range.end.strftime("%Y-%m-%d")
        url = f"{base_url}/1.2/user/-/sleep/date/{start_date}/{end_date}.json"
        sleep_logs = client.make_request(url)

        if sleep_logs and "sleep" in sleep_logs:
            for sleep_entry in sleep_logs["sleep"]:
                start_time_str = sleep_entry.get("startTime", "")
                end_time_str = sleep_entry.get("endTime", "")

                try:
                    sleep_start = dateparse.parse_datetime(start_time_str)
                    sleep_end = dateparse.parse_datetime(end_time_str)
                    if sleep_start:
                        sleep_start = (
                            sleep_start.astimezone(UTC) if sleep_start.tzinfo else sleep_start.replace(tzinfo=UTC)
                        )
                    if sleep_end:
                        sleep_end = sleep_end.astimezone(UTC) if sleep_end.tzinfo else sleep_end.replace(tzinfo=UTC)
                    if not sleep_start or not sleep_end:
                        raise ValueError("Could not parse sleep times")
                except (ValueError, TypeError):
                    date_of_sleep = dateparse.parse_date(sleep_entry.get("dateOfSleep", ""))
                    fallback_date = date_of_sleep or query.date_range.start.date()
                    sleep_start = datetime.combine(fallback_date, datetime.min.time(), tzinfo=UTC)
                    sleep_end = sleep_start + timedelta(hours=8)

                fitbit_logtype = sleep_entry.get("logType", "")
                measurement_source = (
                    MeasurementSource.DEVICE
                    if logtype_mapping.get(fitbit_logtype) == "device"
                    else MeasurementSource.USER
                )

                sleep_metrics: dict[str, Any] = {
                    "minutes_asleep": sleep_entry.get("minutesAsleep", 0),
                    "minutes_awake": sleep_entry.get("minutesAwake", 0),
                    "minutes_to_fall_asleep": sleep_entry.get("minutesToFallAsleep", 0),
                    "efficiency": sleep_entry.get("efficiency", 0),
                    "time_in_bed": sleep_entry.get("timeInBed", 0),
                    "sleep_type": sleep_entry.get("type", "classic"),
                }

                # v1.2 "stages" type includes deep/light/rem/wake breakdowns
                levels = sleep_entry.get("levels", {})
                summary = levels.get("summary", {})
                if sleep_entry.get("type") == "stages" and summary:
                    sleep_metrics["stages"] = {
                        "deep_minutes": summary.get("deep", {}).get("minutes", 0),
                        "deep_count": summary.get("deep", {}).get("count", 0),
                        "light_minutes": summary.get("light", {}).get("minutes", 0),
                        "light_count": summary.get("light", {}).get("count", 0),
                        "rem_minutes": summary.get("rem", {}).get("minutes", 0),
                        "rem_count": summary.get("rem", {}).get("count", 0),
                        "wake_minutes": summary.get("wake", {}).get("minutes", 0),
                        "wake_count": summary.get("wake", {}).get("count", 0),
                    }

                results.append(
                    {
                        "timestamp": sleep_start,
                        "end_time": sleep_end,
                        "value": sleep_entry.get("minutesAsleep", 0),
                        "unit": "minutes",
                        "device_id": primary_device_id,
                        "log_id": sleep_entry.get("logId"),
                        "measurement_source": measurement_source,
                        "log_type": fitbit_logtype,
                        "sleep_metrics": sleep_metrics,
                    }
                )

        return results

    def _parse_fitbit_ecg_readings(
        self, ecg_readings: list[dict[str, Any]], primary_device_id: str | None
    ) -> list[dict[str, Any]]:
        """Parse ECG readings from a Fitbit API response page"""
        results = []
        for ecg_entry in ecg_readings:
            start_time_str = ecg_entry.get("startTime", "")

            try:
                ecg_timestamp = dateparse.parse_datetime(start_time_str)
                if ecg_timestamp:
                    ecg_timestamp = (
                        ecg_timestamp.astimezone(UTC) if ecg_timestamp.tzinfo else ecg_timestamp.replace(tzinfo=UTC)
                    )
                else:
                    ecg_timestamp = django_timezone.now()
            except (ValueError, TypeError):
                ecg_timestamp = django_timezone.now()

            results.append(
                {
                    "timestamp": ecg_timestamp,
                    "value": ecg_entry.get("averageHeartRate", 0),
                    "unit": "bpm",
                    "device_id": primary_device_id,
                    "measurement_source": MeasurementSource.DEVICE,
                    "ecg_metrics": {
                        "result_classification": ecg_entry.get("resultClassification", ""),
                        "sampling_frequency_hz": ecg_entry.get("samplingFrequencyHz", 0),
                        "scaling_factor": ecg_entry.get("scalingFactor", 0),
                        "number_of_samples": ecg_entry.get("numberOfWaveformSamples", 0),
                        "lead_number": ecg_entry.get("leadNumber", 1),
                        "device_name": ecg_entry.get("deviceName", ""),
                        "firmware_version": ecg_entry.get("firmwareVersion", ""),
                        "feature_version": ecg_entry.get("featureVersion", ""),
                    },
                    "waveform_data": {
                        "samples": ecg_entry.get("waveformSamples", []),
                        "sampling_frequency_hz": ecg_entry.get("samplingFrequencyHz", 0),
                        "scaling_factor": ecg_entry.get("scalingFactor", 0),
                        "number_of_samples": ecg_entry.get("numberOfWaveformSamples", 0),
                        "lead_number": ecg_entry.get("leadNumber", 1),
                        "duration_seconds": (
                            ecg_entry.get("numberOfWaveformSamples", 0)
                            / max(ecg_entry.get("samplingFrequencyHz", 1), 1)
                        ),
                    },
                }
            )
        return results

    def _fetch_fitbit_ecg(
        self, client: FitbitClient, query: DataQuery, user_devices: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch Fitbit ECG data with pagination (max 10 per page)"""
        results = []
        primary_device_id = self._get_primary_fitbit_device(user_devices)
        base_url = self.config["ENDPOINTS"]["fitbit"]["base_url"]

        try:
            url = f"{base_url}/1/user/-/ecg/list.json"
            params: dict[str, Any] = {
                "afterDate": query.date_range.start.strftime("%Y-%m-%d"),
                "sort": "asc",
                "limit": 10,
                "offset": 0,
            }

            while url:
                ecg_response = client.make_request(url, params=params)

                if ecg_response and "ecgReadings" in ecg_response:
                    results.extend(self._parse_fitbit_ecg_readings(ecg_response["ecgReadings"], primary_device_id))

                # Follow pagination "next" link if present
                next_url = ecg_response.get("pagination", {}).get("next", "") if ecg_response else ""
                if next_url:
                    url = next_url
                    params = {}  # next URL includes all params
                else:
                    url = ""

        except Exception as e:
            self.logger.warning(f"Failed to fetch ECG data: {e}")

        return results

    def _fetch_fitbit_hrv(
        self, client: FitbitClient, query: DataQuery, user_devices: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch Fitbit HRV intraday data using date-range endpoint (max 30 days, 5-min granularity)"""
        results = []
        primary_device_id = self._get_primary_fitbit_device(user_devices)
        base_url = self.config["ENDPOINTS"]["fitbit"]["base_url"]

        start_date = query.date_range.start.strftime("%Y-%m-%d")
        end_date = query.date_range.end.strftime("%Y-%m-%d")
        url = f"{base_url}/1/user/-/hrv/date/{start_date}/{end_date}/all.json"
        hrv_response = client.make_request(url)

        if hrv_response and "hrv" in hrv_response:
            for hrv_entry in hrv_response["hrv"]:
                minute_str = hrv_entry.get("minute", "")

                try:
                    hrv_timestamp = dateparse.parse_datetime(minute_str)
                    if hrv_timestamp:
                        hrv_timestamp = (
                            hrv_timestamp.astimezone(UTC) if hrv_timestamp.tzinfo else hrv_timestamp.replace(tzinfo=UTC)
                        )
                    else:
                        hrv_timestamp = django_timezone.now()
                except (ValueError, TypeError):
                    hrv_timestamp = django_timezone.now()

                rmssd = hrv_entry.get("value", {}).get("rmssd", 0)

                if rmssd > 0:
                    results.append(
                        {
                            "timestamp": hrv_timestamp,
                            "value": rmssd,
                            "unit": "ms",
                            "device_id": primary_device_id,
                            "measurement_source": MeasurementSource.DEVICE,
                            "hrv_metrics": {
                                "rmssd": rmssd,
                                "coverage": hrv_entry.get("value", {}).get("coverage", 0),
                                "hf": hrv_entry.get("value", {}).get("hf", 0),
                                "lf": hrv_entry.get("value", {}).get("lf", 0),
                            },
                        }
                    )

        return results

    def _get_fitbit_user_devices(self, client: FitbitClient, user_id: str) -> dict[str, str]:
        """Fetch user's Fitbit devices.

        When multiple devices share the same type (e.g. two TRACKERs), keeps
        the one with the most recent lastSyncTime so health data is attributed
        to the active device.

        Returns a mapping of lowercase device type/version -> device ID.
        """
        try:
            devices_response = client.get_devices()
            device_mapping: dict[str, str] = {}
            # Track lastSyncTime per type key so we keep the most recently synced device
            sync_times: dict[str, str] = {}

            for device in devices_response:
                device_id = device.get("id", "")
                device_type = device.get("type", "").lower()
                last_sync = device.get("lastSyncTime", "")

                # Only overwrite if this device synced more recently
                existing_sync = sync_times.get(device_type, "")
                if not existing_sync or last_sync > existing_sync:
                    device_mapping[device_type] = device_id
                    sync_times[device_type] = last_sync

                # Also map by device version (e.g. "charge 6") for scale lookups
                device_version = device.get("deviceVersion", "")
                if device_version:
                    version_key = device_version.lower()
                    existing_sync = sync_times.get(version_key, "")
                    if not existing_sync or last_sync > existing_sync:
                        device_mapping[version_key] = device_id
                        sync_times[version_key] = last_sync

            self.logger.info(f"Fetched {len(devices_response)} devices for Fitbit user {user_id}")
            return device_mapping

        except Exception as e:
            self.logger.warning(f"Failed to fetch Fitbit devices for user {user_id}: {e}")
            return {}

    def _get_primary_fitbit_device(self, user_devices: dict[str, str]) -> str | None:
        """Get primary Fitbit device ID.

        Fitbit returns device types TRACKER and SCALE. We prefer tracker for
        health metrics (HR, steps, sleep, HRV).
        """
        # Fitbit API device types are TRACKER and SCALE (lowercased in our mapping)
        for device_type in ("tracker", "scale"):
            if device_id := user_devices.get(device_type):
                return device_id

        # Fallback: return first available device
        return next(iter(user_devices.values()), None)

    def _check_rate_limit(self, provider: Provider, user_id: str) -> None:
        """Check if we're within rate limits for a provider+user pair.

        Supports per-provider rate limit configuration (e.g., Fitbit: 150 req/hour/user)
        with fallback to global defaults.

        Withings uses an application-level rate limit (120 req/min shared across all users),
        while Fitbit uses a per-user rate limit (150 req/hour per user).
        """
        # For Fitbit: check server-reported rate limit info first
        if provider == Provider.FITBIT and user_id in self._fitbit_rate_limit_info:
            info = self._fitbit_rate_limit_info[user_id]
            # Only trust recent data (within last 5 minutes)
            if time.time() - info["updated_at"] < 300 and info["remaining"] <= 0 and info.get("reset_seconds"):
                self.logger.warning(
                    f"Fitbit server reports rate limit exhausted for user {user_id}, "
                    f"sleeping for {info['reset_seconds']}s"
                )
                time.sleep(info["reset_seconds"])
                return

        # Use per-provider rate limits if configured, else global defaults
        provider_limits = self.config.get("PROVIDER_RATE_LIMITS", {}).get(provider.value, {})
        rate_limit_window = provider_limits.get("RATE_LIMIT_WINDOW", self.config["RATE_LIMIT_WINDOW"])
        max_requests = provider_limits.get("MAX_REQUESTS_PER_WINDOW", self.config["MAX_REQUESTS_PER_WINDOW"])

        current_time = time.time()
        window_start = current_time - rate_limit_window

        # Withings: application-level limit (shared across all users).
        # Fitbit: per-user limit.
        rate_key = provider.value if provider == Provider.WITHINGS else f"{provider.value}:{user_id}"
        self._request_times[rate_key] = [t for t in self._request_times[rate_key] if t > window_start]

        if len(self._request_times[rate_key]) >= max_requests:
            sleep_time = self._request_times[rate_key][0] + rate_limit_window - current_time
            if sleep_time > 0:
                self.logger.warning(
                    f"Rate limit reached for {provider.value} user {user_id}, sleeping for {sleep_time:.2f}s"
                )
                time.sleep(sleep_time)
                current_time = time.time()
                window_start = current_time - rate_limit_window
                self._request_times[rate_key] = [t for t in self._request_times[rate_key] if t > window_start]

        self._request_times[rate_key].append(current_time)

    def _get_user_tokens(self, user_id: str, provider: Provider) -> UserSocialAuth:
        """Get user's OAuth tokens"""
        try:
            from django.contrib.auth import get_user_model

            User = get_user_model()

            user = User.objects.get(ehr_user_id=user_id)
            social_auth = UserSocialAuth.objects.get(user=user, provider=provider.value)
            return cast(UserSocialAuth, social_auth)
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

        except APIError:
            raise  # Permanent failure (missing/invalid refresh token) — already logged at raise site
        except Exception as e:
            self.logger.error(f"Failed to refresh {provider.value} token: {e}")
            raise TokenExpiredError(f"Token refresh failed: {e}")

    def _refresh_withings_token(self, social_auth: UserSocialAuth) -> bool:
        """Refresh Withings OAuth2 token"""
        refresh_token = social_auth.extra_data.get("refresh_token")
        if not refresh_token:
            self.logger.error(
                f"User {social_auth.user.ehr_user_id} has no refresh_token for Withings. "
                f"User must re-authenticate through OAuth flow. "
                f"Preventing infinite retry loop by raising unrecoverable error."
            )
            # Raise APIError (not TokenExpiredError) to prevent retry loop
            raise APIError(
                f"Refresh token missing for user {social_auth.user.ehr_user_id}. "
                f"User must reconnect their Withings account via OAuth."
            )

        base_url = self.config["ENDPOINTS"]["withings"]["base_url"]
        token_url = base_url.rstrip("/") + "/v2/oauth2"
        data = {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": settings.SOCIAL_AUTH_WITHINGS_KEY,
            "client_secret": settings.SOCIAL_AUTH_WITHINGS_SECRET,
            "refresh_token": refresh_token,
        }

        response = self.session.post(token_url, data=data)
        response.raise_for_status()
        token_data = response.json()

        if token_data.get("status") != 0:
            error = token_data.get("error", "Unknown error")
            # Check if it's an unrecoverable error (invalid refresh token)
            if "invalid" in error.lower() or "expired" in error.lower():
                self.logger.error(
                    f"Refresh token invalid/expired for user {social_auth.user.ehr_user_id}. "
                    f"User must re-authenticate. Error: {error}"
                )
                raise APIError(f"Refresh token invalid - user must reconnect: {error}")
            raise TokenExpiredError(f"Token refresh failed: {error}")

        body = token_data.get("body", {})
        social_auth.extra_data.update(
            {
                "access_token": body["access_token"],
                "refresh_token": body["refresh_token"],
                "expires_in": body.get("expires_in", 3600),
                "token_type": "Bearer",
            }
        )
        social_auth.save()

        self.logger.info(f"Successfully refreshed Withings token for user {social_auth.user.ehr_user_id}")
        return True

    def _refresh_fitbit_token(self, social_auth: UserSocialAuth) -> bool:
        """Refresh Fitbit OAuth2 token"""
        if not FITBIT_AVAILABLE:
            raise ImportError("Fitbit library not available")

        refresh_token = social_auth.extra_data.get("refresh_token")
        if not refresh_token:
            self.logger.error(
                f"User {social_auth.user.ehr_user_id} has no refresh_token for Fitbit. "
                f"User must re-authenticate through OAuth flow. "
                f"Preventing infinite retry loop by raising unrecoverable error."
            )
            # Raise APIError (not TokenExpiredError) to prevent retry loop
            raise APIError(
                f"Refresh token missing for user {social_auth.user.ehr_user_id}. "
                f"User must reconnect their Fitbit account via OAuth."
            )

        try:
            client = fitbit.Fitbit(
                client_id=settings.SOCIAL_AUTH_FITBIT_KEY,
                client_secret=settings.SOCIAL_AUTH_FITBIT_SECRET,
                refresh_token=refresh_token,
            )

            new_tokens = client.client.refresh_token()

            social_auth.extra_data.update(
                {
                    "access_token": new_tokens["access_token"],
                    "refresh_token": new_tokens.get("refresh_token", refresh_token),
                    "expires_in": new_tokens.get("expires_in"),
                    "token_type": new_tokens.get("token_type", "Bearer"),
                }
            )
            social_auth.save()

            self.logger.info(f"Successfully refreshed Fitbit token for user {social_auth.user.ehr_user_id}")
            return True
        except Exception as e:
            # Check if it's an unrecoverable error
            error_str = str(e).lower()
            if "invalid" in error_str or "revoked" in error_str or "expired" in error_str:
                self.logger.error(
                    f"Refresh token invalid/revoked for user {social_auth.user.ehr_user_id}. "
                    f"User must re-authenticate. Error: {e}"
                )
                raise APIError(f"Refresh token invalid - user must reconnect: {e}")
            # Other errors might be transient, re-raise as TokenExpiredError
            raise TokenExpiredError(f"Token refresh failed: {e}")

    def get_client_stats(self) -> dict[str, Any]:
        """Get client configuration and status"""
        return {
            "max_retries": self.config["MAX_RETRIES"],
            "timeout": self.config["TIMEOUT"],
            "rate_limit_window": self.config["RATE_LIMIT_WINDOW"],
            "max_requests_per_window": self.config["MAX_REQUESTS_PER_WINDOW"],
            "supported_providers": [Provider.WITHINGS.value, Provider.FITBIT.value],
            "fitbit_available": FITBIT_AVAILABLE,
        }


# Global service instance
_unified_client: UnifiedHealthDataClient | None = None


def get_unified_health_data_client() -> UnifiedHealthDataClient:
    """Lazy singleton for global client instance"""
    global _unified_client
    if _unified_client is None:
        _unified_client = UnifiedHealthDataClient()
    return _unified_client
