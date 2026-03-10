"""
Tests for unified health data API clients.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import responses

from ingestors.api_clients import (
    APIError,
    DataQuery,
    RateLimitError,
    TokenExpiredError,
    UnifiedHealthDataClient,
    get_unified_health_data_client,
)
from ingestors.health_data_constants import DateRange, HealthDataType, MeasurementSource, Provider


class TestDataQuery:
    """Tests for DataQuery dataclass."""

    def test_data_query_creation(self):
        """Test creating a DataQuery instance."""
        date_range = DateRange(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )
        query = DataQuery(
            provider=Provider.WITHINGS,
            data_type=HealthDataType.HEART_RATE,
            user_id="user-123",
            date_range=date_range,
        )

        assert query.provider == Provider.WITHINGS
        assert query.data_type == HealthDataType.HEART_RATE
        assert query.user_id == "user-123"

    def test_cache_key_generation(self):
        """Test cache key generation is deterministic."""
        date_range = DateRange(
            start=datetime(2024, 1, 15, tzinfo=UTC),
            end=datetime(2024, 1, 16, tzinfo=UTC),
        )
        query = DataQuery(
            provider=Provider.FITBIT,
            data_type=HealthDataType.STEPS,
            user_id="user-456",
            date_range=date_range,
        )

        cache_key = query.cache_key
        assert "fitbit" in cache_key
        assert "steps" in cache_key
        assert "user-456" in cache_key
        assert "20240115" in cache_key
        assert "20240116" in cache_key

    def test_cache_key_unique_for_different_queries(self):
        """Test different queries have different cache keys."""
        date_range = DateRange(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        query1 = DataQuery(
            provider=Provider.WITHINGS,
            data_type=HealthDataType.HEART_RATE,
            user_id="user-1",
            date_range=date_range,
        )
        query2 = DataQuery(
            provider=Provider.WITHINGS,
            data_type=HealthDataType.STEPS,
            user_id="user-1",
            date_range=date_range,
        )

        assert query1.cache_key != query2.cache_key


class TestUnifiedHealthDataClient:
    """Tests for UnifiedHealthDataClient class."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {
                        "base_url": "https://wbsapi.withings.net",
                        "measure_types": {
                            "weight": 1,
                            "heart_rate": 11,
                            "systolic_bp": 10,
                            "diastolic_bp": 9,
                        },
                    },
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {"API": "manual", "Aria 2": "device"},
                        "logtype_mapping": {"auto_detected": "device", "manual": "manual"},
                    },
                },
            }
            mock.SOCIAL_AUTH_WITHINGS_KEY = "withings_key"
            mock.SOCIAL_AUTH_WITHINGS_SECRET = "withings_secret"
            mock.SOCIAL_AUTH_FITBIT_KEY = "fitbit_key"
            mock.SOCIAL_AUTH_FITBIT_SECRET = "fitbit_secret"
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance with mocked settings."""
        # Reset global client
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    def test_client_initialization(self, client):
        """Test client initializes correctly."""
        assert client.session is not None
        assert client._request_times is not None

    def test_get_client_stats(self, client):
        """Test getting client statistics."""
        stats = client.get_client_stats()

        assert "max_retries" in stats
        assert "timeout" in stats
        assert "supported_providers" in stats
        assert Provider.WITHINGS.value in stats["supported_providers"]
        assert Provider.FITBIT.value in stats["supported_providers"]

    def test_fetch_health_data_empty_queries(self, client):
        """Test fetching with empty query list returns empty dict."""
        result = client.fetch_health_data([])
        assert result == {}

    def test_bulk_fetch_empty_data_types(self, client):
        """Test bulk fetch with empty data types returns empty dict."""
        date_range = DateRange(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )
        result = client.bulk_fetch_health_data(
            provider=Provider.WITHINGS,
            user_id="user-123",
            data_types=[],
            date_range=date_range,
        )
        assert result == {}


class TestWithingsDataFetching:
    """Tests for Withings-specific data fetching."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {
                        "base_url": "https://wbsapi.withings.net",
                        "measure_types": {
                            "weight": 1,
                            "heart_rate": 11,
                            "systolic_bp": 10,
                            "diastolic_bp": 9,
                        },
                    },
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.SOCIAL_AUTH_WITHINGS_KEY = "withings_key"
            mock.SOCIAL_AUTH_WITHINGS_SECRET = "withings_secret"
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        # Clear circuit breaker registry
        from ingestors.circuit_breaker import registry

        registry._breakers.clear()
        return UnifiedHealthDataClient()

    @responses.activate
    def test_fetch_withings_weight_data(self, client, mock_settings):
        """Test fetching Withings weight data."""
        # Mock the Withings API response
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/measure",
            json={
                "status": 0,
                "body": {
                    "measuregrps": [
                        {
                            "grpid": 123,
                            "date": 1704067200,
                            "category": 1,
                            "deviceid": "device-123",
                            "measures": [{"value": 75000, "unit": -3, "type": 1}],
                        }
                    ]
                },
            },
        )

        # Mock social auth
        mock_social_auth = MagicMock()
        mock_social_auth.extra_data = {"access_token": "test_token", "refresh_token": "refresh_token"}

        with patch.object(client, "_get_user_tokens", return_value=mock_social_auth):
            with patch("ingestors.provider_mappings.get_data_type_config") as mock_config:
                mock_config.return_value = MagicMock(
                    api_endpoint="/measure",
                    api_action="getmeas",
                    meastype=1,
                )

                date_range = DateRange(
                    start=datetime(2024, 1, 1, tzinfo=UTC),
                    end=datetime(2024, 1, 2, tzinfo=UTC),
                )
                result = client.get_health_data(
                    provider=Provider.WITHINGS,
                    data_type=HealthDataType.WEIGHT,
                    user_id="user-123",
                    date_range=date_range,
                )

                assert len(result) == 1
                assert result[0]["value"] == 75.0  # 75000 * 10^-3

    @responses.activate
    def test_fetch_withings_handles_api_error(self, client, mock_settings):
        """Test handling of Withings API errors."""
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/measure",
            json={"status": 401, "error": "Invalid token"},
        )

        mock_social_auth = MagicMock()
        mock_social_auth.extra_data = {"access_token": "test_token", "refresh_token": "refresh_token"}

        with patch.object(client, "_get_user_tokens", return_value=mock_social_auth):
            with patch("ingestors.provider_mappings.get_data_type_config") as mock_config:
                mock_config.return_value = MagicMock(
                    api_endpoint="/measure",
                    api_action="getmeas",
                    meastype=1,
                )

                date_range = DateRange(
                    start=datetime(2024, 1, 1, tzinfo=UTC),
                    end=datetime(2024, 1, 2, tzinfo=UTC),
                )

                # Should return empty results on error
                result = client.get_health_data(
                    provider=Provider.WITHINGS,
                    data_type=HealthDataType.WEIGHT,
                    user_id="user-123",
                    date_range=date_range,
                )

                assert result == []


class TestFitbitDataFetching:
    """Tests for Fitbit-specific data fetching."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {
                        "base_url": "https://wbsapi.withings.net",
                        "measure_types": {},
                    },
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {"API": "manual", "Aria 2": "device"},
                        "logtype_mapping": {"auto_detected": "device"},
                    },
                },
            }
            mock.SOCIAL_AUTH_FITBIT_KEY = "fitbit_key"
            mock.SOCIAL_AUTH_FITBIT_SECRET = "fitbit_secret"
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        from ingestors.circuit_breaker import registry

        registry._breakers.clear()
        return UnifiedHealthDataClient()

    def test_get_primary_fitbit_device(self, client):
        """Test getting primary Fitbit device prefers tracker."""
        user_devices = {
            "tracker": "tracker-123",
            "scale": "scale-789",
        }

        device_id = client._get_primary_fitbit_device(user_devices)
        assert device_id == "tracker-123"

    def test_get_primary_fitbit_device_scale_fallback(self, client):
        """Test falls back to scale when no tracker."""
        user_devices = {"scale": "scale-789"}

        device_id = client._get_primary_fitbit_device(user_devices)
        assert device_id == "scale-789"

    def test_get_primary_fitbit_device_fallback(self, client):
        """Test fallback when no tracker or scale."""
        user_devices = {"unknown_type": "device-123"}

        device_id = client._get_primary_fitbit_device(user_devices)
        assert device_id == "device-123"

    def test_get_primary_fitbit_device_empty(self, client):
        """Test with empty device mapping."""
        device_id = client._get_primary_fitbit_device({})
        assert device_id is None


class TestTokenManagement:
    """Tests for OAuth token management."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {"base_url": "https://wbsapi.withings.net", "measure_types": {}},
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.SOCIAL_AUTH_WITHINGS_KEY = "withings_key"
            mock.SOCIAL_AUTH_WITHINGS_SECRET = "withings_secret"
            mock.SOCIAL_AUTH_FITBIT_KEY = "fitbit_key"
            mock.SOCIAL_AUTH_FITBIT_SECRET = "fitbit_secret"
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    @responses.activate
    def test_refresh_withings_token_success(self, client, mock_settings):
        """Test successful Withings token refresh."""
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/v2/oauth2",
            json={
                "status": 0,
                "body": {
                    "access_token": "new_access_token",
                    "refresh_token": "new_refresh_token",
                    "expires_in": 3600,
                },
            },
        )

        mock_social_auth = MagicMock()
        mock_social_auth.extra_data = {
            "access_token": "old_access_token",
            "refresh_token": "old_refresh_token",
        }

        result = client._refresh_withings_token(mock_social_auth)

        assert result is True
        assert mock_social_auth.extra_data["access_token"] == "new_access_token"
        assert mock_social_auth.extra_data["refresh_token"] == "new_refresh_token"
        mock_social_auth.save.assert_called_once()

    @responses.activate
    def test_refresh_withings_token_failure(self, client, mock_settings):
        """Test Withings token refresh failure with invalid token raises APIError (unrecoverable)."""
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/v2/oauth2",
            json={"status": 401, "error": "Invalid refresh token"},
        )

        mock_social_auth = MagicMock()
        mock_social_auth.extra_data = {"refresh_token": "invalid_token"}

        with pytest.raises(APIError):
            client._refresh_withings_token(mock_social_auth)

    def test_refresh_withings_token_no_refresh_token(self, client):
        """Test error when no refresh token available raises APIError (unrecoverable)."""
        mock_social_auth = MagicMock()
        mock_social_auth.extra_data = {}

        with pytest.raises(APIError) as exc_info:
            client._refresh_withings_token(mock_social_auth)

        assert "Refresh token missing" in str(exc_info.value)


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings with low rate limit for testing."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 1,  # 1 second window for fast tests
                "MAX_REQUESTS_PER_WINDOW": 2,  # Low limit for testing
                "ENDPOINTS": {
                    "withings": {"base_url": "https://wbsapi.withings.net", "measure_types": {}},
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    def test_rate_limit_tracking(self, client):
        """Test that requests are tracked per provider+user pair."""
        client._check_rate_limit(Provider.FITBIT, "user-1")
        client._check_rate_limit(Provider.FITBIT, "user-1")

        assert len(client._request_times["fitbit:user-1"]) == 2

    def test_rate_limit_different_providers_independent(self, client):
        """Test rate limits are tracked independently per provider."""
        client._check_rate_limit(Provider.WITHINGS, "user-1")
        client._check_rate_limit(Provider.FITBIT, "user-1")

        # Withings uses application-level key (no user suffix)
        assert len(client._request_times["withings"]) == 1
        assert len(client._request_times["fitbit:user-1"]) == 1

    def test_rate_limit_different_users_independent(self, client):
        """Test rate limits are tracked independently per user."""
        client._check_rate_limit(Provider.FITBIT, "user-1")
        client._check_rate_limit(Provider.FITBIT, "user-2")

        assert len(client._request_times["fitbit:user-1"]) == 1
        assert len(client._request_times["fitbit:user-2"]) == 1


class TestPerProviderRateLimiting:
    """Tests for per-provider rate limit configuration."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with per-provider rate limits."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 1,  # 1 second global default
                "MAX_REQUESTS_PER_WINDOW": 10,  # global default
                "PROVIDER_RATE_LIMITS": {
                    "fitbit": {
                        "RATE_LIMIT_WINDOW": 2,  # 2 seconds for Fitbit
                        "MAX_REQUESTS_PER_WINDOW": 3,  # 3 requests for Fitbit
                    },
                },
                "ENDPOINTS": {
                    "withings": {"base_url": "https://wbsapi.withings.net"},
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    def test_fitbit_uses_provider_specific_limits(self, client):
        """Test that Fitbit uses its per-provider rate limit config."""
        # Fitbit limit is 3 requests — make 3 requests, should all succeed without sleeping
        for _ in range(3):
            client._check_rate_limit(Provider.FITBIT, "user-1")

        assert len(client._request_times["fitbit:user-1"]) == 3

    def test_withings_uses_global_defaults(self, client):
        """Test that Withings falls back to global defaults (no per-provider config)."""
        # Global default is 10 requests — make 5, should all succeed
        for _ in range(5):
            client._check_rate_limit(Provider.WITHINGS, "user-1")

        # Withings uses application-level key (no user suffix)
        assert len(client._request_times["withings"]) == 5

    def test_fitbit_limit_lower_than_global(self, client):
        """Test that Fitbit's per-provider limit (3) is enforced independently of global (10)."""
        # Fitbit: 3 requests allowed, 4th should trigger rate limiting
        # Withings: 10 requests allowed (global default)
        for _ in range(3):
            client._check_rate_limit(Provider.FITBIT, "user-1")
        for _ in range(5):
            client._check_rate_limit(Provider.WITHINGS, "user-1")

        assert len(client._request_times["fitbit:user-1"]) == 3
        # Withings uses application-level key
        assert len(client._request_times["withings"]) == 5


class TestWithingsResponseProcessing:
    """Tests for Withings API response processing."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {
                        "base_url": "https://wbsapi.withings.net",
                        "measure_types": {
                            "weight": 1,
                            "heart_rate": 11,
                            "systolic_bp": 10,
                            "diastolic_bp": 9,
                        },
                    },
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    def test_process_withings_measurements_weight(self, client):
        """Test processing Withings weight measurements."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 123,
                        "date": 1704067200,  # 2024-01-01 00:00:00 UTC
                        "category": 1,
                        "deviceid": "device-123",
                        "measures": [{"value": 75000, "unit": -3, "type": 1}],  # Weight
                    }
                ]
            }
        }

        result = client._process_withings_measurements(data, HealthDataType.WEIGHT)

        assert len(result) == 1
        assert result[0]["value"] == 75.0
        assert result[0]["device_id"] == "device-123"
        assert result[0]["measurement_source"] == MeasurementSource.DEVICE

    def test_process_withings_measurements_user_entry(self, client):
        """Test processing user-entered measurements (category 2)."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 456,
                        "date": 1704067200,
                        "category": 2,  # User entry
                        "measures": [{"value": 70000, "unit": -3, "type": 1}],
                    }
                ]
            }
        }

        result = client._process_withings_measurements(data, HealthDataType.WEIGHT)

        assert len(result) == 1
        assert result[0]["measurement_source"] == MeasurementSource.USER

    def test_process_withings_activity(self, client):
        """Test processing Withings activity data."""
        data = {
            "body": {
                "activities": [
                    {
                        "date": "2024-01-15",
                        "steps": 10000,
                        "distance": 8500,
                        "calories": 350,
                        "elevation": 50,
                        "deviceid": "device-123",
                    }
                ]
            }
        }

        result = client._process_withings_activity(data)

        assert len(result) == 1
        assert result[0]["steps"] == 10000
        assert result[0]["distance"] == 8500
        assert result[0]["device_id"] == "device-123"
        assert result[0]["original_date"] == "2024-01-15"

    def test_process_withings_sleep_getsummary(self, client):
        """Test processing Withings sleep data from getsummary action."""
        data = {
            "body": {
                "series": [
                    {
                        "startdate": 1704067200,
                        "enddate": 1704096000,
                        "data": {
                            "total_sleep_time": 25200,
                            "deepsleepduration": 7200,
                            "lightsleepduration": 14400,
                            "remsleepduration": 3600,
                            "wakeupcount": 2,
                            "sleep_score": 85,
                            "sleep_efficiency": 0.92,
                            "hr_average": 62,
                            "hr_min": 48,
                            "hr_max": 78,
                            "rr_average": 16,
                            "rr_min": 12,
                            "rr_max": 20,
                        },
                        "deviceid": "device-123",
                    }
                ]
            }
        }

        result = client._process_withings_sleep(data)

        assert len(result) == 1
        assert result[0]["duration"] == 25200
        assert result[0]["deep_sleep_duration"] == 7200
        assert result[0]["wake_up_count"] == 2
        assert result[0]["sleep_score"] == 85
        assert result[0]["hr_average"] == 62
        assert result[0]["rr_average"] == 16

    def test_process_withings_ecg(self, client):
        """Test processing Withings ECG data."""
        data = {
            "body": {
                "series": [
                    {
                        "timestamp": 1704067200,
                        "heart_rate": 72,
                        "deviceid": "device-123",
                        "model": 94,
                        "modified": 1704067260,
                        "ecg": {
                            "signalid": 12345,
                            "afib": 0,
                        },
                    }
                ]
            }
        }

        result = client._process_withings_ecg(data)

        assert len(result) == 1
        assert result[0]["heart_rate"] == 72
        assert result[0]["signal_id"] == 12345
        assert result[0]["afib_result"] == 0
        assert result[0]["afib_classification"] == "Normal sinus rhythm"

    def test_process_withings_blood_pressure_pairing(self, client):
        """Test that blood pressure pairs systolic and diastolic into a single dict record."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 789,
                        "date": 1704067200,
                        "category": 1,
                        "deviceid": "device-bp",
                        "measures": [
                            {"value": 120, "unit": 0, "type": 10},  # Systolic
                            {"value": 80, "unit": 0, "type": 9},  # Diastolic
                        ],
                    }
                ]
            }
        }

        result = client._process_withings_measurements(data, HealthDataType.BLOOD_PRESSURE)

        assert len(result) == 1
        assert result[0]["value"] == {"systolic": 120.0, "diastolic": 80.0}
        assert result[0]["device_id"] == "device-bp"
        assert result[0]["measurement_id"] == 789
        assert result[0]["measurement_source"] == MeasurementSource.DEVICE

    def test_process_withings_blood_pressure_scaled_values(self, client):
        """Test blood pressure with Withings scaling (value * 10^unit)."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 790,
                        "date": 1704067200,
                        "category": 1,
                        "measures": [
                            {"value": 1350, "unit": -1, "type": 10},  # 135.0 systolic
                            {"value": 850, "unit": -1, "type": 9},  # 85.0 diastolic
                        ],
                    }
                ]
            }
        }

        result = client._process_withings_measurements(data, HealthDataType.BLOOD_PRESSURE)

        assert len(result) == 1
        assert result[0]["value"]["systolic"] == 135.0
        assert result[0]["value"]["diastolic"] == 85.0

    def test_process_withings_blood_pressure_incomplete_skipped(self, client):
        """Test that grpids with only systolic or only diastolic are skipped."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 791,
                        "date": 1704067200,
                        "category": 1,
                        "measures": [
                            {"value": 120, "unit": 0, "type": 10},  # Systolic only
                        ],
                    }
                ]
            }
        }

        result = client._process_withings_measurements(data, HealthDataType.BLOOD_PRESSURE)

        assert len(result) == 0

    def test_process_withings_blood_pressure_multiple_groups(self, client):
        """Test blood pressure with multiple measurement groups."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 100,
                        "date": 1704067200,
                        "category": 1,
                        "measures": [
                            {"value": 120, "unit": 0, "type": 10},
                            {"value": 80, "unit": 0, "type": 9},
                        ],
                    },
                    {
                        "grpid": 101,
                        "date": 1704153600,
                        "category": 1,
                        "measures": [
                            {"value": 130, "unit": 0, "type": 10},
                            {"value": 85, "unit": 0, "type": 9},
                        ],
                    },
                ]
            }
        }

        result = client._process_withings_measurements(data, HealthDataType.BLOOD_PRESSURE)

        assert len(result) == 2
        assert result[0]["value"] == {"systolic": 120.0, "diastolic": 80.0}
        assert result[1]["value"] == {"systolic": 130.0, "diastolic": 85.0}

    def test_process_withings_rr_intervals(self, client):
        """Test processing Withings RR interval data from /v2/sleep?action=get."""
        data = {
            "body": {
                "series": [
                    {
                        "startdate": 1704067200,
                        "enddate": 1704070800,
                        "state": 1,
                        "deviceid": "device-hrv",
                        "hr": {
                            "1704067200": 65,
                            "1704067260": 64,
                        },
                        "rr": {
                            "1704067200": 920,
                            "1704067260": 935,
                        },
                        "snoring": {
                            "1704067200": 0,
                        },
                    }
                ]
            }
        }

        result = client._process_withings_rr_intervals(data)

        assert len(result) == 2
        assert result[0]["value"] == 920.0
        assert result[0]["hr"] == 65
        assert result[0]["device_id"] == "device-hrv"
        assert result[0]["measurement_source"] == MeasurementSource.DEVICE
        assert result[1]["value"] == 935.0
        assert result[1]["hr"] == 64

    def test_process_withings_rr_intervals_empty_series(self, client):
        """Test RR intervals with empty series."""
        data = {"body": {"series": []}}

        result = client._process_withings_rr_intervals(data)

        assert len(result) == 0

    def test_process_withings_rr_intervals_no_rr_data(self, client):
        """Test RR intervals when segment has no rr data."""
        data = {
            "body": {
                "series": [
                    {
                        "startdate": 1704067200,
                        "enddate": 1704070800,
                        "hr": {"1704067200": 65},
                        "rr": {},
                    }
                ]
            }
        }

        result = client._process_withings_rr_intervals(data)

        assert len(result) == 0

    def test_process_withings_response_routes_rr_intervals(self, client):
        """Test that _process_withings_response routes RR_INTERVALS correctly."""
        data = {
            "body": {
                "series": [
                    {
                        "startdate": 1704067200,
                        "enddate": 1704070800,
                        "deviceid": "device-hrv",
                        "rr": {"1704067200": 920},
                        "hr": {"1704067200": 65},
                    }
                ]
            }
        }

        result = client._process_withings_response(data, HealthDataType.RR_INTERVALS)

        assert len(result) == 1
        assert result[0]["value"] == 920.0

    def test_process_withings_response_routes_blood_pressure(self, client):
        """Test that _process_withings_response routes BLOOD_PRESSURE to pairing logic."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 999,
                        "date": 1704067200,
                        "category": 1,
                        "measures": [
                            {"value": 120, "unit": 0, "type": 10},
                            {"value": 80, "unit": 0, "type": 9},
                        ],
                    }
                ]
            }
        }

        result = client._process_withings_response(data, HealthDataType.BLOOD_PRESSURE)

        assert len(result) == 1
        assert result[0]["value"] == {"systolic": 120.0, "diastolic": 80.0}


class TestGlobalClient:
    """Tests for global client singleton."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {"base_url": "https://wbsapi.withings.net", "measure_types": {}},
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    def test_get_unified_health_data_client_singleton(self, mock_settings):
        """Test that get_unified_health_data_client returns singleton."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None

        client1 = get_unified_health_data_client()
        client2 = get_unified_health_data_client()

        assert client1 is client2

    def test_get_unified_health_data_client_creates_instance(self, mock_settings):
        """Test that get_unified_health_data_client creates instance if none exists."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None

        client = get_unified_health_data_client()

        assert isinstance(client, UnifiedHealthDataClient)


class TestWithingsErrorHandling:
    """Tests for Withings error status code handling."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {"base_url": "https://wbsapi.withings.net", "measure_types": {}},
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    def test_check_withings_error_success(self, client):
        """Test no exception raised for status 0."""
        client._check_withings_error({"status": 0})

    def test_check_withings_error_auth_failed_numeric(self, client):
        """Test numeric auth failure status codes raise TokenExpiredError."""
        for status in [100, 101, 102, 200, 401]:
            with pytest.raises(TokenExpiredError, match="Authentication failed"):
                client._check_withings_error({"status": status, "error": "auth error"})

    def test_check_withings_error_unauthorized_numeric(self, client):
        """Test numeric unauthorized status codes raise APIError."""
        for status in [214, 277]:
            with pytest.raises(APIError, match="Unauthorized"):
                client._check_withings_error({"status": status, "error": "forbidden"})

    def test_check_withings_error_string_fallback(self, client):
        """Test string-based error detection as fallback."""
        with pytest.raises(TokenExpiredError, match="Token expired"):
            client._check_withings_error({"status": 999, "error": "invalid_token"})

    def test_check_withings_error_generic_api_error(self, client):
        """Test generic API errors raise APIError."""
        with pytest.raises(APIError, match="status 503"):
            client._check_withings_error({"status": 503, "error": "Service unavailable"})


class TestWithingsPagination:
    """Tests for Withings paginated request handling."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {"base_url": "https://wbsapi.withings.net", "measure_types": {}},
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    @responses.activate
    def test_paginated_request_single_page(self, client):
        """Test paginated request with single page (no more data)."""
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/measure",
            json={
                "status": 0,
                "body": {
                    "more": 0,
                    "offset": 0,
                    "measuregrps": [{"grpid": 1, "measures": []}],
                },
            },
        )

        result = client._withings_paginated_request(
            "https://wbsapi.withings.net/measure",
            {"action": "getmeas"},
            {"Authorization": "Bearer test"},
        )

        assert len(responses.calls) == 1
        assert len(result["body"]["measuregrps"]) == 1

    @responses.activate
    def test_paginated_request_multiple_pages(self, client):
        """Test paginated request fetches all pages."""
        # Page 1
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/measure",
            json={
                "status": 0,
                "body": {
                    "more": 1,
                    "offset": 100,
                    "measuregrps": [{"grpid": 1, "measures": []}],
                },
            },
        )
        # Page 2
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/measure",
            json={
                "status": 0,
                "body": {
                    "more": 0,
                    "offset": 0,
                    "measuregrps": [{"grpid": 2, "measures": []}],
                },
            },
        )

        result = client._withings_paginated_request(
            "https://wbsapi.withings.net/measure",
            {"action": "getmeas"},
            {"Authorization": "Bearer test"},
        )

        assert len(responses.calls) == 2
        assert len(result["body"]["measuregrps"]) == 2

    def test_merge_paginated_body_measuregrps(self, client):
        """Test merging paginated measuregrps."""
        target = {"body": {"measuregrps": [{"grpid": 1}]}}
        source = {"body": {"measuregrps": [{"grpid": 2}]}}

        client._merge_paginated_body(target, source)

        assert len(target["body"]["measuregrps"]) == 2

    def test_merge_paginated_body_activities(self, client):
        """Test merging paginated activities."""
        target = {"body": {"activities": [{"date": "2024-01-01"}]}}
        source = {"body": {"activities": [{"date": "2024-01-02"}]}}

        client._merge_paginated_body(target, source)

        assert len(target["body"]["activities"]) == 2

    def test_merge_paginated_body_series(self, client):
        """Test merging paginated series (sleep/ecg)."""
        target = {"body": {"series": [{"startdate": 100}]}}
        source = {"body": {"series": [{"startdate": 200}]}}

        client._merge_paginated_body(target, source)

        assert len(target["body"]["series"]) == 2


class TestWithingsNewDataTypes:
    """Tests for newly supported Withings data types in response processing."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {
                        "base_url": "https://wbsapi.withings.net",
                        "measure_types": {
                            "weight": 1,
                            "heart_rate": 11,
                            "systolic_bp": 10,
                            "diastolic_bp": 9,
                            "temperature": 12,
                            "body_temperature": 71,
                            "skin_temperature": 73,
                            "spo2": 54,
                            "fat_mass_weight": 8,
                            "pulse_wave_velocity": 91,
                        },
                    },
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    def test_process_response_routes_temperature(self, client):
        """Test response processor routes TEMPERATURE to measurements."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 1,
                        "date": 1704067200,
                        "category": 1,
                        "measures": [{"value": 3680, "unit": -2, "type": 12}],
                    }
                ]
            }
        }
        result = client._process_withings_response(data, HealthDataType.TEMPERATURE)
        assert len(result) == 1
        assert result[0]["value"] == pytest.approx(36.8)

    def test_process_response_routes_spo2(self, client):
        """Test response processor routes SPO2 to measurements."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 1,
                        "date": 1704067200,
                        "category": 1,
                        "measures": [{"value": 54, "unit": 0, "type": 54}],
                    }
                ]
            }
        }
        result = client._process_withings_response(data, HealthDataType.SPO2)
        # meastype 54 matches spo2
        assert len(result) == 1

    def test_process_response_routes_fat_mass(self, client):
        """Test response processor routes FAT_MASS to measurements."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 1,
                        "date": 1704067200,
                        "category": 1,
                        "measures": [{"value": 15000, "unit": -3, "type": 8}],
                    }
                ]
            }
        }
        result = client._process_withings_response(data, HealthDataType.FAT_MASS)
        assert len(result) == 1
        assert result[0]["value"] == pytest.approx(15.0)

    def test_process_response_routes_pulse_wave_velocity(self, client):
        """Test response processor routes PULSE_WAVE_VELOCITY to measurements."""
        data = {
            "body": {
                "measuregrps": [
                    {
                        "grpid": 1,
                        "date": 1704067200,
                        "category": 1,
                        "measures": [{"value": 750, "unit": -2, "type": 91}],
                    }
                ]
            }
        }
        result = client._process_withings_response(data, HealthDataType.PULSE_WAVE_VELOCITY)
        assert len(result) == 1
        assert result[0]["value"] == pytest.approx(7.5)

    def test_process_response_unknown_type_logs_warning(self, client):
        """Test unknown data type logs warning and returns empty."""
        data = {"body": {"measuregrps": []}}
        result = client._process_withings_response(data, HealthDataType.HRV)
        assert result == []


class TestExceptionTypes:
    """Tests for custom exception types."""

    def test_api_error(self):
        """Test APIError exception."""
        error = APIError("Test API error")
        assert str(error) == "Test API error"
        assert isinstance(error, Exception)

    def test_token_expired_error(self):
        """Test TokenExpiredError exception."""
        error = TokenExpiredError("Token has expired")
        assert str(error) == "Token has expired"
        assert isinstance(error, APIError)

    def test_rate_limit_error(self):
        """Test RateLimitError exception."""
        error = RateLimitError("Rate limit exceeded")
        assert str(error) == "Rate limit exceeded"
        assert isinstance(error, APIError)


class TestWithingsApplicationLevelRateLimit:
    """Tests for Withings application-level rate limiting."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with Withings per-provider rate limits."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 300,
                "PROVIDER_RATE_LIMITS": {
                    "withings": {
                        "RATE_LIMIT_WINDOW": 1,
                        "MAX_REQUESTS_PER_WINDOW": 3,
                    },
                },
                "ENDPOINTS": {
                    "withings": {"base_url": "https://wbsapi.withings.net"},
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    def test_withings_uses_application_level_key(self, client):
        """Test that Withings rate limit tracks at application level, not per-user."""
        client._check_rate_limit(Provider.WITHINGS, "user-1")
        client._check_rate_limit(Provider.WITHINGS, "user-2")

        # Both users share the same application-level key
        assert len(client._request_times["withings"]) == 2
        assert "withings:user-1" not in client._request_times
        assert "withings:user-2" not in client._request_times

    def test_withings_app_level_limit_shared_across_users(self, client):
        """Test that Withings rate limit is shared across all users."""
        # Limit is 3 requests — split across two users
        client._check_rate_limit(Provider.WITHINGS, "user-1")
        client._check_rate_limit(Provider.WITHINGS, "user-2")
        client._check_rate_limit(Provider.WITHINGS, "user-3")

        assert len(client._request_times["withings"]) == 3


class TestPaginationTruncationWarning:
    """Tests for pagination max_pages exhaustion warning."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {"base_url": "https://wbsapi.withings.net"},
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    @responses.activate
    def test_warns_when_max_pages_exhausted(self, client):
        """Test that a warning is logged when max_pages is reached with more data available."""
        # All 2 pages return more=1 (more data available)
        for _ in range(2):
            responses.add(
                responses.POST,
                "https://wbsapi.withings.net/measure",
                json={
                    "status": 0,
                    "body": {
                        "more": 1,
                        "offset": 100,
                        "measuregrps": [{"grpid": 1, "measures": []}],
                    },
                },
            )

        with patch.object(client, "logger") as mock_logger:
            client._withings_paginated_request(
                "https://wbsapi.withings.net/measure",
                {"action": "getmeas"},
                {"Authorization": "Bearer test"},
                max_pages=2,
            )

            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "pagination limit reached" in warning_msg
            assert "2 pages" in warning_msg

    @responses.activate
    def test_no_warning_when_data_fully_fetched(self, client):
        """Test that no warning is logged when all data is fetched within max_pages."""
        # Page 1: more data
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/measure",
            json={
                "status": 0,
                "body": {
                    "more": 1,
                    "offset": 100,
                    "measuregrps": [{"grpid": 1, "measures": []}],
                },
            },
        )
        # Page 2: no more data
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/measure",
            json={
                "status": 0,
                "body": {
                    "more": 0,
                    "offset": 0,
                    "measuregrps": [{"grpid": 2, "measures": []}],
                },
            },
        )

        with patch.object(client, "logger") as mock_logger:
            client._withings_paginated_request(
                "https://wbsapi.withings.net/measure",
                {"action": "getmeas"},
                {"Authorization": "Bearer test"},
                max_pages=5,
            )

            mock_logger.warning.assert_not_called()


class TestFitbitHeartRateZones:
    """Tests for Fitbit heart rate zone data extraction."""

    @pytest.fixture
    def mock_settings(self):
        """Mock Django settings."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 100,
                "ENDPOINTS": {
                    "withings": {"base_url": "https://wbsapi.withings.net"},
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {"Charge 5": "tracker"},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    def test_extracts_heart_rate_zones(self, client):
        """Test that heart rate zone data is extracted from Fitbit response."""
        mock_fitbit_client = MagicMock()
        mock_fitbit_client.time_series.return_value = {
            "activities-heart": [
                {
                    "dateTime": "2025-02-25",
                    "value": {
                        "restingHeartRate": 68,
                        "heartRateZones": [
                            {"name": "Out of Range", "min": 30, "max": 97, "minutes": 1200, "caloriesOut": 1500.5},
                            {"name": "Fat Burn", "min": 97, "max": 132, "minutes": 30, "caloriesOut": 200.0},
                            {"name": "Cardio", "min": 132, "max": 163, "minutes": 10, "caloriesOut": 100.0},
                            {"name": "Peak", "min": 163, "max": 220, "minutes": 5, "caloriesOut": 50.0},
                        ],
                    },
                }
            ]
        }

        query = DataQuery(
            provider=Provider.FITBIT,
            data_type=HealthDataType.HEART_RATE,
            user_id="test-user",
            date_range=DateRange(
                start=datetime(2025, 2, 25, tzinfo=UTC),
                end=datetime(2025, 2, 26, tzinfo=UTC),
            ),
        )

        results = client._fetch_fitbit_heart_rate(mock_fitbit_client, query, {})

        assert len(results) == 1
        assert results[0]["value"] == 68.0
        assert results[0]["heart_rate_type"] == "resting"
        assert results[0]["heart_rate_zones"] is not None
        assert len(results[0]["heart_rate_zones"]) == 4

        cardio_zone = next(z for z in results[0]["heart_rate_zones"] if z["name"] == "Cardio")
        assert cardio_zone["min"] == 132
        assert cardio_zone["max"] == 163
        assert cardio_zone["minutes"] == 10
        assert cardio_zone["calories_out"] == 100.0

    def test_handles_missing_zones(self, client):
        """Test that missing heartRateZones results in None."""
        mock_fitbit_client = MagicMock()
        mock_fitbit_client.time_series.return_value = {
            "activities-heart": [
                {
                    "dateTime": "2025-02-25",
                    "value": {"restingHeartRate": 72},
                }
            ]
        }

        query = DataQuery(
            provider=Provider.FITBIT,
            data_type=HealthDataType.HEART_RATE,
            user_id="test-user",
            date_range=DateRange(
                start=datetime(2025, 2, 25, tzinfo=UTC),
                end=datetime(2025, 2, 26, tzinfo=UTC),
            ),
        )

        results = client._fetch_fitbit_heart_rate(mock_fitbit_client, query, {})

        assert len(results) == 1
        assert results[0]["heart_rate_zones"] is None


class TestFitbitServerRateLimitHeaders:
    """Tests for Fitbit server-reported rate limit header handling."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with Fitbit rate limits."""
        with patch("ingestors.api_clients.settings") as mock:
            mock.API_CLIENT_CONFIG = {
                "MAX_RETRIES": 3,
                "BACKOFF_FACTOR": 0.5,
                "TIMEOUT": 30,
                "RATE_LIMIT_WINDOW": 60,
                "MAX_REQUESTS_PER_WINDOW": 300,
                "PROVIDER_RATE_LIMITS": {
                    "fitbit": {
                        "RATE_LIMIT_WINDOW": 3600,
                        "MAX_REQUESTS_PER_WINDOW": 150,
                    },
                },
                "ENDPOINTS": {
                    "withings": {"base_url": "https://wbsapi.withings.net"},
                    "fitbit": {
                        "base_url": "https://api.fitbit.com",
                        "source_mapping": {},
                        "logtype_mapping": {},
                    },
                },
            }
            mock.CIRCUIT_BREAKER_CONFIG = {
                "FAILURE_THRESHOLD": 5,
                "SUCCESS_THRESHOLD": 3,
                "PROVIDER_TIMEOUT": 60,
                "FHIR_TIMEOUT": 120,
                "FHIR_FAILURE_THRESHOLD": 5,
                "FHIR_SUCCESS_THRESHOLD": 3,
            }
            yield mock

    @pytest.fixture
    def client(self, mock_settings):
        """Create client instance."""
        import ingestors.api_clients

        ingestors.api_clients._unified_client = None
        return UnifiedHealthDataClient()

    def test_server_reported_exhausted_triggers_sleep(self, client):
        """Test that server-reported rate limit exhaustion triggers sleep."""
        import time

        # Simulate server reporting rate limit exhausted
        client._fitbit_rate_limit_info["user-1"] = {
            "remaining": 0,
            "reset_seconds": 1,
            "updated_at": time.time(),
        }

        with patch("ingestors.api_clients.time") as mock_time:
            mock_time.time.return_value = time.time()
            client._check_rate_limit(Provider.FITBIT, "user-1")

            # Should have slept for 1 second based on server-reported reset
            mock_time.sleep.assert_called_once_with(1)

    def test_stale_server_info_ignored(self, client):
        """Test that stale server-reported info (>5 min old) is ignored."""
        import time

        # Simulate stale server info (6 minutes old)
        client._fitbit_rate_limit_info["user-1"] = {
            "remaining": 0,
            "reset_seconds": 100,
            "updated_at": time.time() - 360,
        }

        # Should fall through to client-side tracking, not sleep for 100s
        client._check_rate_limit(Provider.FITBIT, "user-1")

        # Should have tracked via client-side (1 request recorded)
        assert len(client._request_times["fitbit:user-1"]) == 1

    def test_server_info_with_remaining_allows_request(self, client):
        """Test that server-reported remaining > 0 allows normal client-side tracking."""
        import time

        client._fitbit_rate_limit_info["user-1"] = {
            "remaining": 50,
            "reset_seconds": 1800,
            "updated_at": time.time(),
        }

        client._check_rate_limit(Provider.FITBIT, "user-1")

        # Should proceed normally with client-side tracking
        assert len(client._request_times["fitbit:user-1"]) == 1
