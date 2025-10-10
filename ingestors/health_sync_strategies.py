"""
Health data sync strategies for different sync scenarios
"""
import logging
from typing import Protocol
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

from .health_data_constants import (
    HealthDataType, DateRange, SyncTrigger, HealthSyncConfig
)


logger = logging.getLogger(__name__)


class SyncStrategy(Protocol):
    """Protocol for health data sync strategies"""

    def get_sync_params(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> dict:
        """Get sync parameters for this strategy"""
        ...

    def get_date_range(
        self,
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> DateRange:
        """Get date range for this sync strategy"""
        ...


class BaseSyncStrategy(ABC):
    """Base class for sync strategies"""

    def __init__(self, sync_trigger: SyncTrigger):
        self.sync_trigger = sync_trigger
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    def get_date_range(
        self,
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> DateRange:
        """Get date range for this sync strategy"""
        pass

    def get_sync_params(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> dict:
        """Get common sync parameters"""
        date_range = self.get_date_range(config, last_sync)

        return {
            "sync_trigger": self.sync_trigger,
            "date_range": date_range,
            "user_id": user_id,
            "data_types": data_types,
            "config": config,
            "batch_size": self._get_batch_size(),
            "priority": self._get_priority()
        }

    def _get_batch_size(self) -> int:
        """Get appropriate batch size for this strategy"""
        match self.sync_trigger:
            case SyncTrigger.INITIAL:
                return 1000  # Large batches for historical data
            case SyncTrigger.INCREMENTAL:
                return 500   # Medium batches for regular sync
            case SyncTrigger.WEBHOOK:
                return 100   # Small batches for real-time
            case SyncTrigger.MANUAL:
                return 500   # Medium batches for manual sync

    def _get_priority(self) -> str:
        """Get priority level for this strategy"""
        match self.sync_trigger:
            case SyncTrigger.WEBHOOK:
                return "high"     # Real-time has highest priority
            case SyncTrigger.MANUAL:
                return "medium"   # User-triggered is medium
            case SyncTrigger.INCREMENTAL:
                return "low"      # Regular sync is low
            case SyncTrigger.INITIAL:
                return "low"      # Initial sync is low (can be slow)


class InitialSyncStrategy(BaseSyncStrategy):
    """Strategy for initial historical data sync"""

    def __init__(self, lookback_days: int = 30):
        super().__init__(SyncTrigger.INITIAL)
        self.lookback_days = lookback_days

    def get_date_range(
        self,
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> DateRange:
        """Get date range for initial sync"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=self.lookback_days)

        self.logger.info(f"Initial sync date range: {start_date} to {end_date}")

        return DateRange(start_date, end_date)

    def get_sync_params(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> dict:
        """Get initial sync parameters"""
        params = super().get_sync_params(user_id, data_types, config, last_sync)

        # Add initial sync specific parameters
        params.update({
            "include_all_records": True,
            "skip_recent_check": True,  # Don't skip "recent" data in initial sync
            "allow_large_batches": True
        })

        return params


class IncrementalSyncStrategy(BaseSyncStrategy):
    """Strategy for incremental updates since last sync"""

    def __init__(self, overlap_minutes: int = 5):
        super().__init__(SyncTrigger.INCREMENTAL)
        self.overlap_minutes = overlap_minutes

    def get_date_range(
        self,
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> DateRange:
        """Get date range for incremental sync"""
        end_date = datetime.utcnow()

        if last_sync is None:
            # Fallback to recent data if no last sync
            start_date = end_date - timedelta(hours=24)
            self.logger.warning(f"No last sync found, using 24-hour fallback: {start_date} to {end_date}")
        else:
            # Small overlap to handle timezone issues and potential missed data
            start_date = last_sync - timedelta(minutes=self.overlap_minutes)
            self.logger.info(f"Incremental sync from {start_date} (with {self.overlap_minutes}min overlap)")

        return DateRange(start_date, end_date)

    def get_sync_params(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> dict:
        """Get incremental sync parameters"""
        params = super().get_sync_params(user_id, data_types, config, last_sync)

        # Add incremental sync specific parameters
        params.update({
            "include_all_records": False,
            "skip_duplicates": True,    # Skip data we've already processed
            "use_deduplication": True   # Enable deduplication for overlapping data
        })

        return params


class WebhookSyncStrategy(BaseSyncStrategy):
    """Strategy for real-time webhook-triggered sync"""

    def __init__(self, lookback_minutes: int = 15):
        super().__init__(SyncTrigger.WEBHOOK)
        self.lookback_minutes = lookback_minutes

    def get_date_range(
        self,
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> DateRange:
        """Get date range for webhook sync"""
        end_date = datetime.utcnow()
        # Only sync very recent data for webhooks
        start_date = end_date - timedelta(minutes=self.lookback_minutes)

        self.logger.info(f"Webhook sync for recent {self.lookback_minutes} minutes: {start_date} to {end_date}")

        return DateRange(start_date, end_date)

    def get_sync_params(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> dict:
        """Get webhook sync parameters"""
        params = super().get_sync_params(user_id, data_types, config, last_sync)

        # Add webhook sync specific parameters
        params.update({
            "include_all_records": False,
            "real_time_mode": True,     # Process immediately
            "skip_aggregation": True,   # Don't aggregate real-time data
            "high_priority": True       # Process before other tasks
        })

        return params


class ManualSyncStrategy(BaseSyncStrategy):
    """Strategy for user-triggered manual sync"""

    def __init__(self, custom_date_range: DateRange | None = None):
        super().__init__(SyncTrigger.MANUAL)
        self.custom_date_range = custom_date_range

    def get_date_range(
        self,
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> DateRange:
        """Get date range for manual sync"""
        if self.custom_date_range:
            self.logger.info(f"Manual sync with custom range: {self.custom_date_range.start} to {self.custom_date_range.end}")
            return self.custom_date_range

        # Default to recent data if no custom range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)  # Last week

        self.logger.info(f"Manual sync with default range: {start_date} to {end_date}")

        return DateRange(start_date, end_date)

    def get_sync_params(
        self,
        user_id: str,
        data_types: list[HealthDataType],
        config: HealthSyncConfig,
        last_sync: datetime | None = None
    ) -> dict:
        """Get manual sync parameters"""
        params = super().get_sync_params(user_id, data_types, config, last_sync)

        # Add manual sync specific parameters
        params.update({
            "include_all_records": True,
            "user_triggered": True,      # User explicitly requested this
            "bypass_limits": True,       # Allow larger data sets
            "detailed_logging": True     # More verbose logging for user feedback
        })

        return params


class SyncStrategyFactory:
    """Factory for creating sync strategies"""

    @classmethod
    def create_initial_sync(cls, lookback_days: int = 30) -> InitialSyncStrategy:
        """Create initial sync strategy"""
        return InitialSyncStrategy(lookback_days)

    @classmethod
    def create_incremental_sync(cls, overlap_minutes: int = 5) -> IncrementalSyncStrategy:
        """Create incremental sync strategy"""
        return IncrementalSyncStrategy(overlap_minutes)

    @classmethod
    def create_webhook_sync(cls, lookback_minutes: int = 15) -> WebhookSyncStrategy:
        """Create webhook sync strategy"""
        return WebhookSyncStrategy(lookback_minutes)

    @classmethod
    def create_manual_sync(cls, date_range: DateRange | None = None) -> ManualSyncStrategy:
        """Create manual sync strategy"""
        return ManualSyncStrategy(date_range)

    @classmethod
    def create_for_trigger(
        cls,
        trigger: SyncTrigger,
        **kwargs
    ) -> SyncStrategy:
        """Create strategy based on sync trigger"""
        match trigger:
            case SyncTrigger.INITIAL:
                return cls.create_initial_sync(kwargs.get('lookback_days', 30))
            case SyncTrigger.INCREMENTAL:
                return cls.create_incremental_sync(kwargs.get('overlap_minutes', 5))
            case SyncTrigger.WEBHOOK:
                return cls.create_webhook_sync(kwargs.get('lookback_minutes', 15))
            case SyncTrigger.MANUAL:
                return cls.create_manual_sync(kwargs.get('date_range'))
            case _:
                raise ValueError(f"Unsupported sync trigger: {trigger}")


def get_default_sync_strategy(
    user_has_synced_before: bool,
    trigger: SyncTrigger | None = None
) -> SyncStrategy:
    """Get default sync strategy based on user history"""

    if trigger:
        return SyncStrategyFactory.create_for_trigger(trigger)

    if user_has_synced_before:
        return SyncStrategyFactory.create_incremental_sync()
    else:
        return SyncStrategyFactory.create_initial_sync()