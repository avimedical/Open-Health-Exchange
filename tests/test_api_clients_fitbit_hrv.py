from datetime import UTC, timedelta
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from ingestors.api_clients import DataQuery, FitbitClient, UnifiedHealthDataClient
from ingestors.constants import Provider
from ingestors.health_data_constants import HealthDataType
from ingestors.health_sync_strategies import DateRange

UTC = UTC


@pytest.fixture
def client_instance():
    client = UnifiedHealthDataClient()
    client.logger = Mock()
    client._check_rate_limit = Mock()
    client.config = {"ENDPOINTS": {"fitbit": {"base_url": "https://api.fitbit.com"}}}
    client._get_primary_fitbit_device = Mock(return_value="test-device-id")
    return client


@pytest.fixture
def fitbit_client():
    client = Mock(spec=FitbitClient)
    client.make_request = Mock()
    return client


@pytest.fixture
def base_query():
    now = timezone.now()
    return DataQuery(
        provider=Provider.FITBIT,
        user_id="user-123",
        data_type=HealthDataType.HRV,
        date_range=DateRange(start=now - timedelta(days=5), end=now),
    )


def test_fetch_fitbit_hrv_summary_success(client_instance, fitbit_client, base_query):
    """Test fetching summary HRV data (default behavior without intraday flag)."""
    with patch("ingestors.api_clients.settings") as mock_settings:
        mock_settings.FITBIT_INTRADAY_HRV_ENABLED = False

        fitbit_client.make_request.return_value = {
            "hrv": [{"dateTime": "2023-10-01", "value": {"dailyRmssd": 45.5, "deepRmssd": 48.0}}]
        }

        results = client_instance._fetch_fitbit_hrv(fitbit_client, base_query, {"test": "device"})

        assert len(results) == 1
        assert results[0]["value"] == 45.5
        assert results[0]["unit"] == "ms"
        assert results[0]["device_id"] == "test-device-id"
        assert "coverage" not in results[0]["hrv_metrics"]

        # Verify rate limit wasn't double-checked
        client_instance._check_rate_limit.assert_not_called()

        # Verify correct URL format
        expected_url = f"https://api.fitbit.com/1/user/-/hrv/date/{base_query.date_range.start.strftime('%Y-%m-%d')}/{base_query.date_range.end.strftime('%Y-%m-%d')}.json"
        fitbit_client.make_request.assert_called_once_with(expected_url)


def test_fetch_fitbit_hrv_intraday_success(client_instance, fitbit_client, base_query):
    """Test fetching intraday HRV data."""
    with patch("ingestors.api_clients.settings") as mock_settings:
        mock_settings.FITBIT_INTRADAY_HRV_ENABLED = True

        fitbit_client.make_request.return_value = {
            "hrv": [
                {
                    "minute": "2023-10-01T08:00:00.000",
                    "value": {"rmssd": 45.5, "coverage": 0.95, "hf": 20.0, "lf": 15.0},
                }
            ]
        }

        results = client_instance._fetch_fitbit_hrv(fitbit_client, base_query, {"test": "device"})

        assert len(results) == 1
        assert results[0]["value"] == 45.5
        assert results[0]["hrv_metrics"]["coverage"] == 0.95
        assert results[0]["hrv_metrics"]["hf"] == 20.0

        client_instance._check_rate_limit.assert_not_called()
        expected_url = f"https://api.fitbit.com/1/user/-/hrv/date/{base_query.date_range.start.strftime('%Y-%m-%d')}/{base_query.date_range.end.strftime('%Y-%m-%d')}/all.json"
        fitbit_client.make_request.assert_called_once_with(expected_url)


def test_fetch_fitbit_hrv_intraday_chunking(client_instance, fitbit_client):
    """Test that intraday queries > 30 days are properly chunked and rate limits are checked."""
    now = timezone.now()
    query = DataQuery(
        provider=Provider.FITBIT,
        user_id="user-123",
        data_type=HealthDataType.HRV,
        date_range=DateRange(start=now - timedelta(days=65), end=now),
    )

    with patch("ingestors.api_clients.settings") as mock_settings:
        mock_settings.FITBIT_INTRADAY_HRV_ENABLED = True

        # Should make 3 requests for a 66 day range (30 + 30 + 6)
        fitbit_client.make_request.return_value = {
            "hrv": [{"minute": "2023-10-01T08:00:00.000", "value": {"rmssd": 40.0}}]
        }

        results = client_instance._fetch_fitbit_hrv(fitbit_client, query, {})

        assert len(results) == 3  # 3 chunks * 1 entry
        assert fitbit_client.make_request.call_count == 3

        # First chunk shouldn't check rate limit (handled upstream), but chunks 2 and 3 should
        assert client_instance._check_rate_limit.call_count == 2
