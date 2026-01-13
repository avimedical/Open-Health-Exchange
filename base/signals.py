"""
Django signals for the base app.
Handles automatic cleanup of related models when provider connections are removed.
"""

import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver
from social_django.models import UserSocialAuth

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=UserSocialAuth)
def delete_provider_link_on_social_auth_delete(sender, instance, **kwargs):
    """
    Delete the corresponding ProviderLink when a UserSocialAuth is deleted.

    This ensures that webhook processing won't try to find users for providers
    that have been disconnected.
    """
    from base.models import ProviderLink

    provider_name = instance.provider
    user = instance.user

    try:
        # Find and delete the ProviderLink for this user and provider
        deleted_count, _ = ProviderLink.objects.filter(
            user=user,
            provider__provider_type=provider_name,
        ).delete()

        if deleted_count > 0:
            logger.info(
                f"Deleted {deleted_count} ProviderLink(s) for user {user.username} "
                f"after UserSocialAuth removal for provider {provider_name}"
            )
        else:
            logger.debug(f"No ProviderLink found to delete for user {user.username} and provider {provider_name}")
    except Exception as e:
        logger.error(f"Error deleting ProviderLink for user {user.username} and provider {provider_name}: {e}")
