"""
Tests for base app views.
"""

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from social_django.models import UserSocialAuth

from base.models import EHRUser, Provider, ProviderLink


class TestUnlinkProviderView(TestCase):
    """Tests for the unlink_provider view."""

    def setUp(self):
        self.client = APIClient()

        # Create test user
        self.user = EHRUser.objects.create_user(
            username="test-user-123",
            password="testpass123",
        )

        # Create provider
        self.provider = Provider.objects.create(
            name="Withings",
            provider_type="withings",
            active=True,
        )

    def test_unlink_provider_success(self):
        """Test successful provider unlinking."""
        # Create social auth and provider link
        social_auth = UserSocialAuth.objects.create(
            user=self.user,
            provider="withings",
            uid="12345",
        )
        ProviderLink.objects.create(
            user=self.user,
            provider=self.provider,
            external_user_id="12345",
        )

        response = self.client.post(
            "/api/base/link/withings/unlink/",
            {"ehr_user_id": "test-user-123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "unlinked")
        self.assertEqual(response.data["provider"], "withings")

        # Verify social auth was deleted
        self.assertFalse(UserSocialAuth.objects.filter(id=social_auth.id).exists())

        # Verify provider link was deleted (via signal)
        self.assertFalse(ProviderLink.objects.filter(user=self.user, provider=self.provider).exists())

    def test_unlink_provider_missing_ehr_user_id(self):
        """Test error when ehr_user_id is not provided."""
        response = self.client.post(
            "/api/base/link/withings/unlink/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_unlink_provider_user_not_found(self):
        """Test error when user is not found."""
        response = self.client.post(
            "/api/base/link/withings/unlink/",
            {"ehr_user_id": "nonexistent-user"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("not found", response.data["error"])

    def test_unlink_provider_unsupported_provider(self):
        """Test error for unsupported provider."""
        response = self.client.post(
            "/api/base/link/unsupported/unlink/",
            {"ehr_user_id": "test-user-123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("supported_providers", response.data)

    def test_unlink_provider_no_connection_found(self):
        """Test error when no provider connection exists."""
        response = self.client.post(
            "/api/base/link/withings/unlink/",
            {"ehr_user_id": "test-user-123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("No withings connection found", response.data["error"])

    def test_unlink_provider_cleans_orphan_link(self):
        """Test that orphan ProviderLink is cleaned up when UserSocialAuth doesn't exist."""
        # Create only provider link (no social auth - orphan state)
        provider_link = ProviderLink.objects.create(
            user=self.user,
            provider=self.provider,
            external_user_id="12345",
        )

        response = self.client.post(
            "/api/base/link/withings/unlink/",
            {"ehr_user_id": "test-user-123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "unlinked")
        self.assertIn("orphan", response.data["message"])

        # Verify orphan link was deleted
        self.assertFalse(ProviderLink.objects.filter(id=provider_link.id).exists())

    def test_unlink_provider_delete_method(self):
        """Test that DELETE method also works."""
        # Create social auth
        UserSocialAuth.objects.create(
            user=self.user,
            provider="withings",
            uid="12345",
        )

        response = self.client.delete(
            "/api/base/link/withings/unlink/?ehr_user_id=test-user-123",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "unlinked")

    def test_unlink_fitbit_provider(self):
        """Test unlinking Fitbit provider."""
        # Create Fitbit provider
        fitbit_provider = Provider.objects.create(
            name="Fitbit",
            provider_type="fitbit",
            active=True,
        )

        # Create social auth and provider link for Fitbit
        UserSocialAuth.objects.create(
            user=self.user,
            provider="fitbit",
            uid="ABC123",
        )
        ProviderLink.objects.create(
            user=self.user,
            provider=fitbit_provider,
            external_user_id="ABC123",
        )

        response = self.client.post(
            "/api/base/link/fitbit/unlink/",
            {"ehr_user_id": "test-user-123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["provider"], "fitbit")

        # Verify both were deleted
        self.assertFalse(UserSocialAuth.objects.filter(user=self.user, provider="fitbit").exists())
        self.assertFalse(ProviderLink.objects.filter(user=self.user, provider=fitbit_provider).exists())
