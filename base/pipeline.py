import logging
from social_core.exceptions import AuthForbidden
from mozilla_django_oidc.contrib.drf import get_oidc_backend


logger = logging.getLogger(__name__)


def associate_by_token_user(strategy, details, backend, user=None, *args, **kwargs):
    """
    Associate the current authenticated user with the social account.
    If no authenticated user is present, continue the pipeline.
    """
    print("!!!! associate_by_token_user")

    if not user:
        bearer_token = strategy.request.GET.get("token") or strategy.session_get("token")
        logger.info(f"Using bearer token: {bearer_token}")
        current_user = get_oidc_backend().get_or_create_user(bearer_token, None, None)
        if current_user and current_user.is_authenticated:
            logger.info(f"Using authenticated user {current_user.username} for social account linking")
            return {"user": current_user}

    # If we don't have a user and are not creating new ones, stop the pipeline
    if not user and not strategy.setting("SOCIAL_AUTH_CREATE_USERS", True):
        raise AuthForbidden(backend, "No user to associate with social account and user creation is disabled")

    return None


def load_devices(strategy, details, backend, user, response, *args, **kwargs):
    ''''
    Load the devices for the authenticated user from the provider.
    '''
    pass