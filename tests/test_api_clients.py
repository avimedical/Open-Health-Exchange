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
                        "device_types": ["tracker", "watch", "scale"],
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
                        "device_types": ["tracker", "watch", "scale"],
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
                        "device_types": ["tracker", "watch", "scale"],
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
        """Test getting primary Fitbit device from device mapping."""
        user_devices = {
            "tracker": "tracker-123",
            "watch": "watch-456",
            "scale": "scale-789",
        }

        device_id = client._get_primary_fitbit_device(user_devices)

        # Should return first matching device type from config
        assert device_id == "tracker-123"

    def test_get_primary_fitbit_device_fallback(self, client):
        """Test fallback when no matching device type."""
        user_devices = {"unknown_type": "device-123"}

        device_id = client._get_primary_fitbit_device(user_devices)

        # Should return first available device
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
                        "device_types": [],
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
        """Test Withings token refresh failure."""
        responses.add(
            responses.POST,
            "https://wbsapi.withings.net/v2/oauth2",
            json={"status": 401, "error": "Invalid refresh token"},
        )

        mock_social_auth = MagicMock()
        mock_social_auth.extra_data = {"refresh_token": "invalid_token"}

        with pytest.raises(TokenExpiredError):
            client._refresh_withings_token(mock_social_auth)

    def test_refresh_withings_token_no_refresh_token(self, client):
        """Test error when no refresh token available."""
        mock_social_auth = MagicMock()
        mock_social_auth.extra_data = {}

        with pytest.raises(TokenExpiredError) as exc_info:
            client._refresh_withings_token(mock_social_auth)

        assert "No refresh token" in str(exc_info.value)


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
                        "device_types": [],
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
        """Test that requests are tracked for rate limiting."""
        # Call _check_rate_limit multiple times
        client._check_rate_limit(Provider.WITHINGS)
        client._check_rate_limit(Provider.WITHINGS)

        # Should have 2 tracked requests
        assert len(client._request_times["withings"]) == 2

    def test_rate_limit_different_providers_independent(self, client):
        """Test rate limits are tracked independently per provider."""
        client._check_rate_limit(Provider.WITHINGS)
        client._check_rate_limit(Provider.FITBIT)

        assert len(client._request_times["withings"]) == 1
        assert len(client._request_times["fitbit"]) == 1


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
                        "device_types": [],
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

    def test_process_withings_sleep(self, client):
        """Test processing Withings sleep data."""
        data = {
            "body": {
                "series": [
                    {
                        "startdate": 1704067200,
                        "enddate": 1704096000,
                        "data": {
                            "totalsleepduration": 25200,
                            "deepsleepduration": 7200,
                            "lightsleepduration": 14400,
                            "remsleepduration": 3600,
                            "wakeupcount": 2,
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
                        "device_types": [],
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
