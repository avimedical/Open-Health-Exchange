from django.db import models
from django.contrib.auth.models import AbstractUser


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
    default_data_types: list = models.JSONField(default=list, help_text="Default data types for health sync (empty = use provider config defaults)")  # type: ignore[assignment]
    excluded_data_types: list = models.JSONField(default=list, help_text="Data types to exclude from sync (opt-out)")  # type: ignore[assignment]
    supports_webhooks: bool = models.BooleanField(default=True, help_text="Provider supports webhook subscriptions")  # type: ignore[assignment]
    webhook_enabled: bool = models.BooleanField(default=True, help_text="Enable webhook subscriptions for this provider")  # type: ignore[assignment]

    def __str__(self):
        return f"{self.name}"

    def get_effective_data_types(self):
        """
        Get effective data types for this provider, considering opt-out preferences.
        Returns the provider's default data types minus any excluded types.
        """
        from ingestors.constants import Provider as ProviderEnum, PROVIDER_CONFIGS

        try:
            provider_enum = ProviderEnum(self.provider_type)
            config = PROVIDER_CONFIGS.get(provider_enum)

            if not config:
                return []

            # Start with provider config defaults or model overrides
            if self.default_data_types:
                data_types = self.default_data_types.copy()
            else:
                data_types = config.default_health_data_types.copy()

            # Remove excluded data types (opt-out)
            if self.excluded_data_types:
                data_types = [dt for dt in data_types if dt not in self.excluded_data_types]

            return data_types

        except (ValueError, AttributeError):
            return []

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
    linked_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, help_text="Timestamp when the provider link was created")

    class Meta:
        unique_together = ("provider", "user")

    def __str__(self):
        return f"{self.user.username} - {self.provider.name}"
