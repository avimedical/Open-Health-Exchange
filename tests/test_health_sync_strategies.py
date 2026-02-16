"""
Tests for health data sync strategies.
"""

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from ingestors.health_data_constants import (
    AggregationLevel,
    DateRange,
    HealthDataType,
    HealthSyncConfig,
    SyncFrequency,
    SyncTrigger,
)
from ingestors.health_sync_strategies import (
    IncrementalSyncStrategy,
    InitialSyncStrategy,
    ManualSyncStrategy,
    SyncStrategyFactory,
    WebhookSyncStrategy,
    get_default_sync_strategy,
)


def make_sync_config():
    """Create a sample HealthSyncConfig with all required fields."""
    return HealthSyncConfig(
        user_id="test-user",
        enabled_data_types=[HealthDataType.HEART_RATE, HealthDataType.STEPS],
        aggregation_preference=AggregationLevel.INDIVIDUAL,
        sync_frequency=SyncFrequency.REALTIME,
        retention_period=timedelta(days=365),
    )


class TestInitialSyncStrategy:
    """Tests for InitialSyncStrategy class."""

    @pytest.fixture
    def strategy(self):
        """Create InitialSyncStrategy instance."""
        return InitialSyncStrategy(lookback_days=30)

    @pytest.fixture
    def config(self):
        """Create sample HealthSyncConfig."""
        return make_sync_config()

    @freeze_time("2024-01-15 12:00:00", tz_offset=0)
    def test_get_date_range_calculates_correct_range(self, strategy, config):
        """Test initial sync calculates correct date range."""
        date_range = strategy.get_date_range(config)

        # Should be 30 days back from frozen time
        expected_end = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        expected_start = expected_end - timedelta(days=30)

        assert date_range.end == expected_end
        assert date_range.start == expected_start

    def test_get_date_range_custom_lookback(self, config):
        """Test initial sync with custom lookback days."""
        strategy = InitialSyncStrategy(lookback_days=90)

        date_range = strategy.get_date_range(config)

        # Should be approximately 90 days difference
        diff = date_range.end - date_range.start
        assert diff.days == 90

    def test_sync_trigger_is_initial(self, strategy):
        """Test that sync trigger is INITIAL."""
        assert strategy.sync_trigger == SyncTrigger.INITIAL

    def test_get_sync_params_contains_required_fields(self, strategy, config):
        """Test sync params contain all required fields."""
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            config=config,
        )

        assert params["sync_trigger"] == SyncTrigger.INITIAL
        assert params["user_id"] == "test-user"
        assert HealthDataType.HEART_RATE in params["data_types"]
        assert isinstance(params["date_range"], DateRange)
        assert "batch_size" in params
        assert "priority" in params

    def test_get_sync_params_includes_initial_specific_params(self, strategy, config):
        """Test initial sync params include specific flags."""
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.STEPS],
            config=config,
        )

        assert params["include_all_records"] is True
        assert params["skip_recent_check"] is True
        assert params["allow_large_batches"] is True

    def test_batch_size_for_initial_sync(self, strategy, config):
        """Test batch size is large for initial sync."""
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.WEIGHT],
            config=config,
        )

        assert params["batch_size"] == 1000

    def test_priority_for_initial_sync(self, strategy, config):
        """Test priority is low for initial sync."""
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.WEIGHT],
            config=config,
        )

        assert params["priority"] == "low"


class TestIncrementalSyncStrategy:
    """Tests for IncrementalSyncStrategy class."""

    @pytest.fixture
    def strategy(self):
        """Create IncrementalSyncStrategy instance."""
        return IncrementalSyncStrategy(overlap_minutes=5)

    @pytest.fixture
    def config(self):
        """Create sample HealthSyncConfig."""
        return make_sync_config()

    @freeze_time("2024-01-15 12:00:00", tz_offset=0)
    def test_get_date_range_with_last_sync(self, strategy, config):
        """Test incremental sync uses last sync time with overlap."""
        last_sync = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        date_range = strategy.get_date_range(config, last_sync)

        # Start should be 5 minutes before last_sync
        expected_start = last_sync - timedelta(minutes=5)
        assert date_range.start == expected_start
        assert date_range.end == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

    @freeze_time("2024-01-15 12:00:00", tz_offset=0)
    def test_get_date_range_without_last_sync_uses_fallback(self, strategy, config):
        """Test incremental sync uses 24-hour fallback when no last sync."""
        date_range = strategy.get_date_range(config, last_sync=None)

        expected_end = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        expected_start = expected_end - timedelta(hours=24)

        assert date_range.start == expected_start
        assert date_range.end == expected_end

    def test_sync_trigger_is_incremental(self, strategy):
        """Test that sync trigger is INCREMENTAL."""
        assert strategy.sync_trigger == SyncTrigger.INCREMENTAL

    def test_custom_overlap_minutes(self, config):
        """Test incremental sync with custom overlap."""
        strategy = IncrementalSyncStrategy(overlap_minutes=10)
        last_sync = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        date_range = strategy.get_date_range(config, last_sync)

        # Start should be 10 minutes before last_sync
        expected_start = last_sync - timedelta(minutes=10)
        assert date_range.start == expected_start

    def test_get_sync_params_includes_incremental_specific_params(self, strategy, config):
        """Test incremental sync params include specific flags."""
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            config=config,
        )

        assert params["include_all_records"] is False
        assert params["skip_duplicates"] is True
        assert params["use_deduplication"] is True

    def test_batch_size_for_incremental_sync(self, strategy, config):
        """Test batch size is medium for incremental sync."""
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            config=config,
        )

        assert params["batch_size"] == 500

    def test_priority_for_incremental_sync(self, strategy, config):
        """Test priority is low for incremental sync."""
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            config=config,
        )

        assert params["priority"] == "low"


class TestWebhookSyncStrategy:
    """Tests for WebhookSyncStrategy class."""

    @pytest.fixture
    def strategy(self):
        """Create WebhookSyncStrategy instance."""
        return WebhookSyncStrategy(lookback_minutes=15)

    @pytest.fixture
    def config(self):
        """Create sample HealthSyncConfig."""
        return make_sync_config()

    @freeze_time("2024-01-15 12:00:00", tz_offset=0)
    def test_get_date_range_for_webhook(self, strategy, config):
        """Test webhook sync uses short lookback period."""
        date_range = strategy.get_date_range(config)

        expected_end = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        expected_start = expected_end - timedelta(minutes=15)

        assert date_range.start == expected_start
        assert date_range.end == expected_end

    def test_sync_trigger_is_webhook(self, strategy):
        """Test that sync trigger is WEBHOOK."""
        assert strategy.sync_trigger == SyncTrigger.WEBHOOK

    def test_custom_lookback_minutes(self, config):
        """Test webhook sync with custom lookback."""
        strategy = WebhookSyncStrategy(lookback_minutes=30)

        date_range = strategy.get_date_range(config)

        diff = date_range.end - date_range.start
        assert diff == timedelta(minutes=30)

    def test_get_sync_params_includes_webhook_specific_params(self, strategy, config):
        """Test webhook sync params include specific flags."""
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            config=config,
        )

        assert params["include_all_records"] is False
        assert params["real_time_mode"] is True
        assert params["skip_aggregation"] is True
        assert params["high_priority"] is True

    def test_batch_size_for_webhook_sync(self, strategy, config):
        """Test batch size is small for webhook sync."""
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            config=config,
        )

        assert params["batch_size"] == 100

    def test_priority_for_webhook_sync(self, strategy, config):
        """Test priority is high for webhook sync."""
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.HEART_RATE],
            config=config,
        )

        assert params["priority"] == "high"


class TestManualSyncStrategy:
    """Tests for ManualSyncStrategy class."""

    @pytest.fixture
    def config(self):
        """Create sample HealthSyncConfig."""
        return make_sync_config()

    @freeze_time("2024-01-15 12:00:00", tz_offset=0)
    def test_get_date_range_default_without_custom_range(self, config):
        """Test manual sync uses 7-day default when no custom range."""
        strategy = ManualSyncStrategy()

        date_range = strategy.get_date_range(config)

        expected_end = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        expected_start = expected_end - timedelta(days=7)

        assert date_range.start == expected_start
        assert date_range.end == expected_end

    def test_get_date_range_with_custom_range(self, config):
        """Test manual sync uses custom date range when provided."""
        custom_range = DateRange(
            start=datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
            end=datetime(2024, 1, 10, 0, 0, 0, tzinfo=UTC),
        )
        strategy = ManualSyncStrategy(custom_date_range=custom_range)

        date_range = strategy.get_date_range(config)

        assert date_range.start == custom_range.start
        assert date_range.end == custom_range.end

    def test_sync_trigger_is_manual(self):
        """Test that sync trigger is MANUAL."""
        strategy = ManualSyncStrategy()
        assert strategy.sync_trigger == SyncTrigger.MANUAL

    def test_get_sync_params_includes_manual_specific_params(self, config):
        """Test manual sync params include specific flags."""
        strategy = ManualSyncStrategy()
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.WEIGHT],
            config=config,
        )

        assert params["include_all_records"] is True
        assert params["user_triggered"] is True
        assert params["bypass_limits"] is True
        assert params["detailed_logging"] is True

    def test_batch_size_for_manual_sync(self, config):
        """Test batch size is medium for manual sync."""
        strategy = ManualSyncStrategy()
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.WEIGHT],
            config=config,
        )

        assert params["batch_size"] == 500

    def test_priority_for_manual_sync(self, config):
        """Test priority is medium for manual sync."""
        strategy = ManualSyncStrategy()
        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[HealthDataType.WEIGHT],
            config=config,
        )

        assert params["priority"] == "medium"


class TestSyncStrategyFactory:
    """Tests for SyncStrategyFactory class."""

    def test_create_initial_sync_default(self):
        """Test creating initial sync strategy with defaults."""
        strategy = SyncStrategyFactory.create_initial_sync()

        assert isinstance(strategy, InitialSyncStrategy)
        assert strategy.lookback_days == 30

    def test_create_initial_sync_custom_lookback(self):
        """Test creating initial sync strategy with custom lookback."""
        strategy = SyncStrategyFactory.create_initial_sync(lookback_days=60)

        assert isinstance(strategy, InitialSyncStrategy)
        assert strategy.lookback_days == 60

    def test_create_incremental_sync_default(self):
        """Test creating incremental sync strategy with defaults."""
        strategy = SyncStrategyFactory.create_incremental_sync()

        assert isinstance(strategy, IncrementalSyncStrategy)
        assert strategy.overlap_minutes == 5

    def test_create_incremental_sync_custom_overlap(self):
        """Test creating incremental sync strategy with custom overlap."""
        strategy = SyncStrategyFactory.create_incremental_sync(overlap_minutes=15)

        assert isinstance(strategy, IncrementalSyncStrategy)
        assert strategy.overlap_minutes == 15

    def test_create_webhook_sync_default(self):
        """Test creating webhook sync strategy with defaults."""
        strategy = SyncStrategyFactory.create_webhook_sync()

        assert isinstance(strategy, WebhookSyncStrategy)
        assert strategy.lookback_minutes == 15

    def test_create_webhook_sync_custom_lookback(self):
        """Test creating webhook sync strategy with custom lookback."""
        strategy = SyncStrategyFactory.create_webhook_sync(lookback_minutes=30)

        assert isinstance(strategy, WebhookSyncStrategy)
        assert strategy.lookback_minutes == 30

    def test_create_manual_sync_without_range(self):
        """Test creating manual sync strategy without date range."""
        strategy = SyncStrategyFactory.create_manual_sync()

        assert isinstance(strategy, ManualSyncStrategy)
        assert strategy.custom_date_range is None

    def test_create_manual_sync_with_range(self):
        """Test creating manual sync strategy with date range."""
        date_range = DateRange(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 15, tzinfo=UTC),
        )
        strategy = SyncStrategyFactory.create_manual_sync(date_range=date_range)

        assert isinstance(strategy, ManualSyncStrategy)
        assert strategy.custom_date_range == date_range

    def test_create_for_trigger_initial(self):
        """Test creating strategy from INITIAL trigger."""
        strategy = SyncStrategyFactory.create_for_trigger(SyncTrigger.INITIAL)

        assert isinstance(strategy, InitialSyncStrategy)

    def test_create_for_trigger_incremental(self):
        """Test creating strategy from INCREMENTAL trigger."""
        strategy = SyncStrategyFactory.create_for_trigger(SyncTrigger.INCREMENTAL)

        assert isinstance(strategy, IncrementalSyncStrategy)

    def test_create_for_trigger_webhook(self):
        """Test creating strategy from WEBHOOK trigger."""
        strategy = SyncStrategyFactory.create_for_trigger(SyncTrigger.WEBHOOK)

        assert isinstance(strategy, WebhookSyncStrategy)

    def test_create_for_trigger_manual(self):
        """Test creating strategy from MANUAL trigger."""
        strategy = SyncStrategyFactory.create_for_trigger(SyncTrigger.MANUAL)

        assert isinstance(strategy, ManualSyncStrategy)

    def test_create_for_trigger_with_kwargs(self):
        """Test creating strategy from trigger with custom kwargs."""
        strategy = SyncStrategyFactory.create_for_trigger(SyncTrigger.INITIAL, lookback_days=90)

        assert isinstance(strategy, InitialSyncStrategy)
        assert strategy.lookback_days == 90


class TestGetDefaultSyncStrategy:
    """Tests for get_default_sync_strategy function."""

    def test_returns_initial_for_new_user(self):
        """Test returns initial strategy for user who hasn't synced."""
        strategy = get_default_sync_strategy(user_has_synced_before=False)

        assert isinstance(strategy, InitialSyncStrategy)

    def test_returns_incremental_for_existing_user(self):
        """Test returns incremental strategy for user who has synced before."""
        strategy = get_default_sync_strategy(user_has_synced_before=True)

        assert isinstance(strategy, IncrementalSyncStrategy)

    def test_explicit_trigger_overrides_default_initial(self):
        """Test explicit trigger overrides default for new user."""
        strategy = get_default_sync_strategy(user_has_synced_before=False, trigger=SyncTrigger.WEBHOOK)

        assert isinstance(strategy, WebhookSyncStrategy)

    def test_explicit_trigger_overrides_default_existing(self):
        """Test explicit trigger overrides default for existing user."""
        strategy = get_default_sync_strategy(user_has_synced_before=True, trigger=SyncTrigger.MANUAL)

        assert isinstance(strategy, ManualSyncStrategy)

    def test_all_trigger_types(self):
        """Test all trigger types work with explicit trigger."""
        triggers_and_strategies = [
            (SyncTrigger.INITIAL, InitialSyncStrategy),
            (SyncTrigger.INCREMENTAL, IncrementalSyncStrategy),
            (SyncTrigger.WEBHOOK, WebhookSyncStrategy),
            (SyncTrigger.MANUAL, ManualSyncStrategy),
        ]

        for trigger, expected_class in triggers_and_strategies:
            strategy = get_default_sync_strategy(user_has_synced_before=True, trigger=trigger)
            assert isinstance(strategy, expected_class)


class TestBaseSyncStrategyHelpers:
    """Tests for BaseSyncStrategy helper methods via concrete implementations."""

    def test_batch_size_by_trigger_type(self):
        """Test batch sizes are appropriate for each trigger type."""
        strategies = [
            (InitialSyncStrategy(), 1000),
            (IncrementalSyncStrategy(), 500),
            (WebhookSyncStrategy(), 100),
            (ManualSyncStrategy(), 500),
        ]

        for strategy, expected_batch_size in strategies:
            assert strategy._get_batch_size() == expected_batch_size

    def test_priority_by_trigger_type(self):
        """Test priorities are appropriate for each trigger type."""
        strategies = [
            (InitialSyncStrategy(), "low"),
            (IncrementalSyncStrategy(), "low"),
            (WebhookSyncStrategy(), "high"),
            (ManualSyncStrategy(), "medium"),
        ]

        for strategy, expected_priority in strategies:
            assert strategy._get_priority() == expected_priority

    def test_logger_is_created_for_each_strategy(self):
        """Test each strategy has its own logger."""
        initial = InitialSyncStrategy()
        incremental = IncrementalSyncStrategy()
        webhook = WebhookSyncStrategy()
        manual = ManualSyncStrategy()

        assert initial.logger is not None
        assert incremental.logger is not None
        assert webhook.logger is not None
        assert manual.logger is not None

        # Each should have different logger names
        assert initial.logger.name != incremental.logger.name


class TestSyncStrategyMultipleDataTypes:
    """Tests for handling multiple data types."""

    @pytest.fixture
    def config(self):
        """Create sample HealthSyncConfig."""
        return make_sync_config()

    def test_initial_sync_with_multiple_data_types(self, config):
        """Test initial sync params with multiple data types."""
        strategy = InitialSyncStrategy()
        data_types = [
            HealthDataType.HEART_RATE,
            HealthDataType.STEPS,
            HealthDataType.WEIGHT,
            HealthDataType.BLOOD_PRESSURE,
        ]

        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=data_types,
            config=config,
        )

        assert len(params["data_types"]) == 4
        assert all(dt in params["data_types"] for dt in data_types)

    def test_incremental_sync_with_empty_data_types(self, config):
        """Test incremental sync params with empty data types list."""
        strategy = IncrementalSyncStrategy()

        params = strategy.get_sync_params(
            user_id="test-user",
            data_types=[],
            config=config,
        )

        assert params["data_types"] == []
