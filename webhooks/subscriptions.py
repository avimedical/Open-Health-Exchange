"""
Webhook subscription management for health data providers
Handles creating, updating, and deleting webhook subscriptions
"""
import requests
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from social_django.models import UserSocialAuth

from ingestors.health_data_constants import Provider


logger = logging.getLogger(__name__)


@dataclass
class WebhookSubscription:
    """Represents a webhook subscription"""
    provider: Provider
    user_id: str
    subscription_id: Optional[str] = None
    callback_url: Optional[str] = None
    data_types: Optional[List[str]] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WebhookSubscriptionError(Exception):
    """Raised when webhook subscription operations fail"""
    pass


class WebhookSubscriptionManager:
    """Manages webhook subscriptions with health data providers"""

    def __init__(self):
        self.base_webhook_url = settings.WEBHOOK_BASE_URL

    def create_withings_subscription(
        self,
        user_id: str,
        data_types: Optional[List[str]] = None
    ) -> WebhookSubscription:
        """
        Create webhook subscription with Withings

        Args:
            user_id: EHR user ID
            data_types: List of data types to subscribe to
        """
        try:
            # Get user's access token
            social_auth = self._get_user_social_auth(user_id, Provider.WITHINGS)
            access_token = social_auth.access_token

            # Withings subscription API endpoint
            url = "https://wbsapi.withings.net/notify"
            callback_url = f"{self.base_webhook_url}withings/"

            # Map data types to Withings application IDs
            appli_types = self._map_data_types_to_withings_appli(data_types or ['heart_rate', 'steps'])

            created_subscriptions = []
            for appli in appli_types:
                params = {
                    'action': 'subscribe',
                    'access_token': access_token,
                    'callbackurl': callback_url,
                    'comment': f'health_sync_{user_id}_{appli}',
                    'appli': appli
                }

                try:
                    response = requests.post(url, params=params, timeout=settings.WEBHOOK_CONFIG['TIMEOUT'])
                    response.raise_for_status()

                    result = response.json()
                    if result.get('status') == 0:  # Withings returns 0 for success
                        subscription = WebhookSubscription(
                            provider=Provider.WITHINGS,
                            user_id=user_id,
                            callback_url=callback_url,
                            data_types=[str(appli)],
                            created_at=datetime.utcnow()
                        )
                        created_subscriptions.append(subscription)
                        logger.info(f"Created Withings subscription for user {user_id}, appli {appli}")
                    else:
                        logger.error(f"Withings subscription failed for appli {appli}: {result}")

                except requests.RequestException as e:
                    logger.error(f"Failed to create Withings subscription for appli {appli}: {e}")

            if not created_subscriptions:
                raise WebhookSubscriptionError("Failed to create any Withings subscriptions")

            # Return the first subscription (could be extended to return all)
            return created_subscriptions[0]

        except Exception as e:
            logger.error(f"Error creating Withings subscription for user {user_id}: {e}")
            raise WebhookSubscriptionError(f"Failed to create Withings subscription: {e}")

    def create_fitbit_subscription(
        self,
        user_id: str,
        subscription_id: Optional[str] = None,
        collection_types: Optional[List[str]] = None
    ) -> WebhookSubscription:
        """
        Create webhook subscription with Fitbit

        Args:
            user_id: EHR user ID
            subscription_id: Custom subscription ID (optional)
            collection_types: List of collection types to subscribe to
        """
        try:
            # Get user's access token
            social_auth = self._get_user_social_auth(user_id, Provider.FITBIT)
            access_token = social_auth.access_token

            # Generate subscription ID if not provided
            if not subscription_id:
                subscription_id = f"health_sync_{user_id}_{int(datetime.utcnow().timestamp())}"

            # Default collection types
            collections = collection_types or ['activities', 'body']

            created_subscriptions = []
            for collection_type in collections:
                # Fitbit subscription API endpoint
                url = f"https://api.fitbit.com/1/user/{social_auth.extra_data.get('user_id', user_id)}/{collection_type}/apiSubscriptions/{subscription_id}.json"

                headers = {
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                }

                try:
                    response = requests.post(url, headers=headers, timeout=settings.WEBHOOK_CONFIG['TIMEOUT'])

                    if response.status_code == 201:  # Created
                        subscription = WebhookSubscription(
                            provider=Provider.FITBIT,
                            user_id=user_id,
                            subscription_id=subscription_id,
                            data_types=[collection_type],
                            created_at=datetime.utcnow()
                        )
                        created_subscriptions.append(subscription)
                        logger.info(f"Created Fitbit subscription for user {user_id}, collection {collection_type}")

                    elif response.status_code == 409:  # Subscription already exists
                        logger.info(f"Fitbit subscription already exists for user {user_id}, collection {collection_type}")
                        subscription = WebhookSubscription(
                            provider=Provider.FITBIT,
                            user_id=user_id,
                            subscription_id=subscription_id,
                            data_types=[collection_type],
                            created_at=datetime.utcnow()
                        )
                        created_subscriptions.append(subscription)

                    else:
                        logger.error(f"Fitbit subscription failed for collection {collection_type}: {response.status_code} - {response.text}")

                except requests.RequestException as e:
                    logger.error(f"Failed to create Fitbit subscription for collection {collection_type}: {e}")

            if not created_subscriptions:
                raise WebhookSubscriptionError("Failed to create any Fitbit subscriptions")

            return created_subscriptions[0]

        except Exception as e:
            logger.error(f"Error creating Fitbit subscription for user {user_id}: {e}")
            raise WebhookSubscriptionError(f"Failed to create Fitbit subscription: {e}")

    def delete_withings_subscription(self, user_id: str, appli: int) -> bool:
        """Delete Withings webhook subscription"""
        try:
            social_auth = self._get_user_social_auth(user_id, Provider.WITHINGS)
            access_token = social_auth.access_token

            url = "https://wbsapi.withings.net/notify"
            params = {
                'action': 'revoke',
                'access_token': access_token,
                'callbackurl': f"{self.base_webhook_url}withings/",
                'appli': appli
            }

            response = requests.post(url, params=params, timeout=settings.WEBHOOK_CONFIG['TIMEOUT'])
            response.raise_for_status()

            result = response.json()
            success = result.get('status') == 0

            if success:
                logger.info(f"Deleted Withings subscription for user {user_id}, appli {appli}")
            else:
                logger.error(f"Failed to delete Withings subscription: {result}")

            return bool(success)

        except Exception as e:
            logger.error(f"Error deleting Withings subscription: {e}")
            return False

    def delete_fitbit_subscription(self, user_id: str, subscription_id: str, collection_type: str = 'activities') -> bool:
        """Delete Fitbit webhook subscription"""
        try:
            social_auth = self._get_user_social_auth(user_id, Provider.FITBIT)
            access_token = social_auth.access_token
            fitbit_user_id = social_auth.extra_data.get('user_id', user_id)

            url = f"https://api.fitbit.com/1/user/{fitbit_user_id}/{collection_type}/apiSubscriptions/{subscription_id}.json"
            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            response = requests.delete(url, headers=headers, timeout=settings.WEBHOOK_CONFIG['TIMEOUT'])
            success = response.status_code == 204  # No Content

            if success:
                logger.info(f"Deleted Fitbit subscription for user {user_id}, subscription {subscription_id}")
            else:
                logger.error(f"Failed to delete Fitbit subscription: {response.status_code} - {response.text}")

            return success

        except Exception as e:
            logger.error(f"Error deleting Fitbit subscription: {e}")
            return False

    def list_user_subscriptions(self, user_id: str) -> List[WebhookSubscription]:
        """List all webhook subscriptions for a user"""
        subscriptions = []

        # Check Withings subscriptions
        try:
            # Withings doesn't have a direct API to list subscriptions
            # We would need to track them in our database
            logger.info(f"Checking Withings subscriptions for user {user_id}")
        except Exception as e:
            logger.error(f"Error checking Withings subscriptions: {e}")

        # Check Fitbit subscriptions
        try:
            social_auth = self._get_user_social_auth(user_id, Provider.FITBIT)
            access_token = social_auth.access_token
            fitbit_user_id = social_auth.extra_data.get('user_id', user_id)

            url = f"https://api.fitbit.com/1/user/{fitbit_user_id}/apiSubscriptions.json"
            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            response = requests.get(url, headers=headers, timeout=settings.WEBHOOK_CONFIG['TIMEOUT'])
            if response.status_code == 200:
                data = response.json()
                for sub in data.get('apiSubscriptions', []):
                    subscription = WebhookSubscription(
                        provider=Provider.FITBIT,
                        user_id=user_id,
                        subscription_id=sub.get('subscriptionId'),
                        data_types=[sub.get('collectionType', 'unknown')]
                    )
                    subscriptions.append(subscription)
            else:
                logger.error(f"Failed to list Fitbit subscriptions: {response.status_code}")

        except Exception as e:
            logger.error(f"Error listing Fitbit subscriptions: {e}")

        return subscriptions

    def _get_user_social_auth(self, user_id: str, provider: Provider) -> UserSocialAuth:
        """Get user's social auth for provider"""
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()

            user = User.objects.get(ehr_user_id=user_id)
            social_auth = UserSocialAuth.objects.get(
                user=user,
                provider=provider.value
            )
            return social_auth

        except Exception as e:
            raise WebhookSubscriptionError(f"User {user_id} not connected to {provider.value}: {e}")

    def _map_data_types_to_withings_appli(self, data_types: List[str]) -> List[int]:
        """Map data types to Withings application IDs"""
        mapping = {
            'weight': [1],                    # Weight scale
            'heart_rate': [4, 44],           # Activity + Heart rate
            'steps': [4],                    # Activity data
            'blood_pressure': [46],          # Blood pressure monitor
            'ecg': [50],                     # ECG device
            'temperature': [21],             # Temperature
            'spo2': [54],                    # Oxygen saturation
            'rr_intervals': [44]             # Heart rate variability
        }

        appli_set = set()
        for data_type in data_types:
            if data_type in mapping:
                appli_set.update(mapping[data_type])

        return list(appli_set) if appli_set else [4]  # Default to activity data