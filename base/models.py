from django.contrib.auth.models import AbstractUser
from django.db import models


class EHRUser(AbstractUser):
    """
    Custom User model for EHR users.
    """

    ehr_user_id: str = models.CharField(max_length=255, unique=True)  # type: ignore[assignment]

    def save(self, *args, **kwargs):
        self.ehr_user_id = self.username
        super().save(*args, **kwargs)


class Provider(models.Model):
    PROVIDER_CHOICES = [
        ("beurer", "Beurer"),
        ("fitbit", "Fitbit"),
        ("omron", "Omron"),
        ("withings", "Withings"),
    ]
    name: str = models.CharField(max_length=255, unique=True)  # type: ignore[assignment]
    provider_type: str = models.CharField(max_length=50, choices=PROVIDER_CHOICES, default="withings")  # type: ignore[assignment]
    active: bool = models.BooleanField(default=False)  # type: ignore[assignment]
    credentials = models.JSONField(null=True, blank=True)
    default_data_types: list = models.JSONField(
        default=list, help_text="Default data types for health sync (empty = use provider config defaults)"
    )  # type: ignore[assignment]
    excluded_data_types: list = models.JSONField(default=list, help_text="Data types to exclude from sync (opt-out)")  # type: ignore[assignment]
    supports_webhooks: bool = models.BooleanField(default=True, help_text="Provider supports webhook subscriptions")  # type: ignore[assignment]
    webhook_enabled: bool = models.BooleanField(
        default=True, help_text="Enable webhook subscriptions for this provider"
    )  # type: ignore[assignment]
    success_deeplink_url: str = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Optional deeplink URL for mobile app success redirect (e.g., myapp://oauth/success/withings/)",
    )  # type: ignore[assignment]
    error_deeplink_url: str = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Optional deeplink URL for mobile app error redirect (e.g., myapp://oauth/error/withings/)",
    )  # type: ignore[assignment]

    def __str__(self):
        return f"{self.name}"

    def get_available_data_types(self):
        """
        Get all data types supported by this provider from provider_mappings.

        This is the complete list of what CAN be synchronized.
        Returns empty list if provider type is invalid.
        """
        from ingestors.provider_mappings import Provider as ProviderEnum
        from ingestors.provider_mappings import get_supported_data_types

        try:
            # Provider enum values are uppercase (WITHINGS, FITBIT)
            # but model provider_type is lowercase (withings, fitbit)
            provider_enum = ProviderEnum[self.provider_type.upper()]
            return get_supported_data_types(provider_enum)
        except (ValueError, AttributeError, KeyError):
            return []

    def get_default_data_types(self):
        """
        Get default data types for this provider.

        For backward compatibility, checks model's default_data_types first,
        then falls back to all available types from provider_mappings.
        """
        if self.default_data_types:
            # Legacy: use explicitly configured defaults
            return self.default_data_types.copy()

        # New behavior: all available types are default
        return self.get_available_data_types()

    def get_effective_data_types(self):
        """
        Get effective data types for this provider after applying exclusions.

        This is what WILL actually be synchronized.
        Formula: defaults - exclusions
        """
        defaults = self.get_default_data_types()

        # Remove excluded data types (opt-out)
        if self.excluded_data_types:
            return [dt for dt in defaults if dt not in self.excluded_data_types]

        return defaults

    def is_webhook_enabled(self):
        """Check if webhooks are enabled for this provider"""
        return self.supports_webhooks and self.webhook_enabled


class ProviderLink(models.Model):
    """
    This is used for linking providers to users, whether using python-social-auth or custom authentication
    """

    external_user_id: str = models.CharField(max_length=255)  # type: ignore[assignment]
    provider: Provider = models.ForeignKey(Provider, on_delete=models.CASCADE)  # type: ignore[assignment]
    user: EHRUser = models.ForeignKey(EHRUser, on_delete=models.CASCADE)  # type: ignore[assignment]
    extra_data = models.JSONField(null=True, blank=True)
    linked_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the provider link was created"
    )

    class Meta:
        unique_together = ("provider", "user")

    def __str__(self):
        return f"{self.user.username} - {self.provider.name}"
