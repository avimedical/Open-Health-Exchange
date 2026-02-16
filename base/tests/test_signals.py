"""
Tests for Django signals in the base app.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from base.signals import delete_provider_link_on_social_auth_delete


class TestDeleteProviderLinkSignal(TestCase):
    """Tests for the delete_provider_link_on_social_auth_delete signal handler."""

    @patch("base.models.ProviderLink")
    def test_deletes_provider_link_when_social_auth_deleted(self, mock_provider_link):
        """Test that ProviderLink is deleted when UserSocialAuth is deleted."""
        # Setup mock user and UserSocialAuth instance
        mock_user = MagicMock()
        mock_user.username = "test_user"

        mock_social_auth = MagicMock()
        mock_social_auth.provider = "withings"
        mock_social_auth.user = mock_user

        # Setup mock delete return value
        mock_queryset = MagicMock()
        mock_queryset.delete.return_value = (1, {"base.ProviderLink": 1})
        mock_provider_link.objects.filter.return_value = mock_queryset

        # Call the signal handler
        delete_provider_link_on_social_auth_delete(
            sender=None,
            instance=mock_social_auth,
        )

        # Verify ProviderLink.objects.filter was called with correct args
        mock_provider_link.objects.filter.assert_called_once_with(
            user=mock_user,
            provider__provider_type="withings",
        )

        # Verify delete was called
        mock_queryset.delete.assert_called_once()

    @patch("base.models.ProviderLink")
    def test_handles_no_provider_link_found(self, mock_provider_link):
        """Test that no error occurs if no ProviderLink exists."""
        # Setup mock user and UserSocialAuth instance
        mock_user = MagicMock()
        mock_user.username = "test_user"

        mock_social_auth = MagicMock()
        mock_social_auth.provider = "fitbit"
        mock_social_auth.user = mock_user

        # Setup mock delete return value (no rows deleted)
        mock_queryset = MagicMock()
        mock_queryset.delete.return_value = (0, {})
        mock_provider_link.objects.filter.return_value = mock_queryset

        # Call the signal handler - should not raise
        delete_provider_link_on_social_auth_delete(
            sender=None,
            instance=mock_social_auth,
        )

        # Verify delete was still called
        mock_queryset.delete.assert_called_once()

    @patch("base.models.ProviderLink")
    def test_handles_exception_gracefully(self, mock_provider_link):
        """Test that exceptions are caught and logged."""
        # Setup mock user and UserSocialAuth instance
        mock_user = MagicMock()
        mock_user.username = "test_user"

        mock_social_auth = MagicMock()
        mock_social_auth.provider = "withings"
        mock_social_auth.user = mock_user

        # Setup mock to raise exception
        mock_provider_link.objects.filter.side_effect = Exception("Database error")

        # Call the signal handler - should not raise
        delete_provider_link_on_social_auth_delete(
            sender=None,
            instance=mock_social_auth,
        )

        # Test passes if no exception is raised
