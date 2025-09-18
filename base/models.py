from django.db import models
from django.contrib.auth.models import AbstractUser


class EHRUser(AbstractUser):
    """
    Custom User model for EHR users.
    """

    ehr_user_id = models.CharField(max_length=255, unique=True)

    def save(self, *args, **kwargs):
        self.ehr_user_id = self.username
        super().save(*args, **kwargs)


class Provider(models.Model):
    PROVIDER_CHOICES = [
        ("withings", "Withings"),
        ("fitbit", "Fitbit"),
        ("beurer", "Beurer"),
        ("omron", "Omron"),
    ]
    name = models.CharField(max_length=255, unique=True)
    provider_type = models.CharField(max_length=50, choices=PROVIDER_CHOICES, default="withings")
    active = models.BooleanField(default=False)
    credentials = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"{self.name}"


class ProviderLink(models.Model):
    """
    This is used for linking providers to users, whether using python-social-auth or custom authentication
    """

    external_user_id = models.CharField(max_length=255)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE)
    user = models.ForeignKey(EHRUser, on_delete=models.CASCADE)
    extra_data = models.JSONField(null=True, blank=True)

    class Meta:
        unique_together = ("provider", "user")

    def __str__(self):
        return f"{self.user.username} - {self.provider.name}"
