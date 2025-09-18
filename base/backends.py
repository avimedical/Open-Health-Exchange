import logging
from social_core.backends.oauth import BaseOAuth2
from social_core.exceptions import AuthStateMissing, AuthTokenError
from django.core.exceptions import SuspiciousOperation
from django.contrib.auth.models import Group
from mozilla_django_oidc.auth import OIDCAuthenticationBackend


logger = logging.getLogger(__name__)


class WithingsOAuth2(BaseOAuth2):
    """Withings OAuth2 authentication backend."""

    name = "withings"
    AUTHORIZATION_URL = "https://account.withings.com/oauth2_user/authorize2"
    ACCESS_TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
    ACCESS_TOKEN_METHOD = "POST"
    SCOPE_SEPARATOR = ","
    REDIRECT_STATE = False
    STATE_PARAMETER = True
    DEFAULT_SCOPE = ["user.info", "user.metrics", "user.activity"]
    ID_KEY = "userid"
    EXTRA_DATA = [
        ("access_token", "access_token"),
        ("refresh_token", "refresh_token"),
        ("expires_in", "expires"),
        ("token_type", "token_type"),
        ("userid", "userid"),
    ]

    def get_user_details(self, response):
        """Return user details from Withings account.

        The response parameter is the body from user data endpoint,
        not the token response.
        """
        body = response.get("body", {})
        user = body.get("user", {})

        return {
            "username": str(user.get("id")),
            "email": user.get("email", ""),
            "fullname": user.get("firstname", "") + " " + user.get("lastname", ""),
            "first_name": user.get("firstname", ""),
            "last_name": user.get("lastname", ""),
        }

    def user_data(self, access_token, *args, **kwargs):
        """Load user data from Withings API"""
        # First check if userid is directly in kwargs
        userid = kwargs.get("userid")

        # If not in kwargs, check if it's directly in the response (flat structure)
        if not userid and kwargs.get("response"):
            userid = kwargs.get("response", {}).get("userid")

        # Lastly, check if it's in the nested body structure
        if not userid and kwargs.get("response", {}).get("body"):
            userid = kwargs.get("response", {}).get("body", {}).get("userid")

        if not userid:
            logger.error(f"No userid found in token response or kwargs: {kwargs}")
            return {}

        logger.info(f"Using userid: {userid} for user_data request")

        return {"userid": userid}

    def get_user_id(self, details, response):
        """Return the unique user ID from the Withings API response."""
        if response and "body" in response:
            return response.get("body", {}).get("user", {}).get("id")
        return None

    def get_session_state(self):
        return self.strategy.session_get("withings_state")

    def validate_state(self):
        state = self.get_session_state()
        if not state:
            raise AuthStateMissing(self, "state")
        return state

    def auth_complete(self, *args, **kwargs):
        """Completes login process, returns user instance."""
        try:
            # Get user from the request if it's there
            user = kwargs.get("user") or self.strategy.request.user

            # If user is authenticated, pass it to the next step
            if user and user.is_authenticated:
                kwargs["user"] = user

            return super().auth_complete(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in auth_complete: {e}")
            raise

    def request_access_token(self, *args, **kwargs):
        """
        Request access token from Withings using authorization code.
        """
        code = self.data.get("code")
        client_id = self.setting("KEY")
        client_secret = self.setting("SECRET")

        # Get the redirect_uri that was originally used in the authorization request
        # This should match exactly what was sent during the initial authorization request
        redirect_uri = kwargs.get("redirect_uri") or self.get_redirect_uri()

        data = {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = self.request(self.ACCESS_TOKEN_URL, method="POST", data=data, headers=headers)

        if response.status_code != 200:
            raise AuthTokenError(self, response.json())

        response_json = response.json()
        if response_json.get("status") != 0:
            error_message = response_json.get("error", "Unknown error")
            raise AuthTokenError(self, error_message)

        return response_json.get("body", {})


class OidcAuthenticationBackend(OIDCAuthenticationBackend):
    """
    This backend is used to create users from the oidc claims.
    """

    def create_user(self, claims: dict):
        """Creates pseudonomized shadow-users. Users only have a group and a username."""
        username = self.get_username(claims)
        user = self.UserModel.objects.create_user(username, email="")
        # writes to db immediately
        user.groups.set([Group.objects.get_or_create(name=group)[0] for group in claims.get("groups", [])])
        return user

    def update_user(self, user, claims):
        user = super().update_user(user, claims)
        # writes to db immediatly
        user.groups.set([Group.objects.get_or_create(name=group)[0] for group in claims.get("groups", [])])
        return user

    def filter_users_by_claims(self, claims):
        username = claims.get("sub")
        return self.UserModel.objects.filter(username=username)

    def get_username(self, claims):
        return claims.get("sub")

    def userinfo_needs_update(self, user, claims):
        return user.groups.all() != [Group.objects.get_or_create(name=group)[0] for group in claims.get("groups", [])]

    def update_user_if_outdated(self, user, claims, access_token):
        """Updates user if the claims are outdated."""
        if self.userinfo_needs_update(user, claims):
            return self.update_user(user, claims)
        return user

    def get_or_create_user(self, access_token, id_token, payload):
        # copied from source but added acces_token to update_user
        """Returns a User instance if 1 user is found. Creates a user if not found
        and configured to do so. Returns nothing if multiple users are matched."""
        user_info: dict = self.get_userinfo(access_token, id_token, payload)
        if not self.verify_claims(user_info):
            msg = "Claims verification failed"
            raise SuspiciousOperation(msg)
        # email based filtering
        users = self.filter_users_by_claims(user_info)
        if len(users) == 1:
            return self.update_user_if_outdated(users[0], user_info, access_token)
        if len(users) > 1:
            # In the rare case that two user accounts have the same email address,
            # bail. Randomly selecting one seems really wrong.
            msg = "Multiple users returned"
            raise SuspiciousOperation(msg)
        if self.get_settings("OIDC_CREATE_USER", True):
            return self.create_user(user_info)
        return None
