import logging
import requests
from typing import Any
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
        # Check multiple possible locations for userid
        if response:
            # First check if userid is directly in response (token response)
            if "userid" in response:
                return response["userid"]

            # Then check nested body structure (user data response)
            if "body" in response and "user" in response["body"]:
                return response["body"]["user"].get("id")

            # Also check if it's in the body directly
            if "body" in response and "userid" in response["body"]:
                return response["body"]["userid"]

        # Fallback to details if available
        if details and "username" in details:
            return details["username"]

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
    def refresh_token(self, token: str, *args, **kwargs) -> dict[str, Any]:
        """Refresh Withings access token using refresh token"""
        try:
            key, secret = self.get_key_and_secret()
            response = requests.post(
                self.ACCESS_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": key,
                    "client_secret": secret,
                    "refresh_token": token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )

            if response.status_code != 200:
                logger.error(f"Withings token refresh failed: {response.status_code} - {response.text}")
                return {}

            response_json = response.json()
            if response_json.get("status") != 0:
                error_message = response_json.get("error", "Unknown error")
                logger.error(f"Withings token refresh error: {error_message}")
                return {}

            token_data = response_json.get("body", {})
            logger.info("Successfully refreshed Withings access token")
            return token_data if isinstance(token_data, dict) else {}

        except Exception as e:
            logger.error(f"Exception during Withings token refresh: {e}")
            return {}


class FitbitOAuth2(BaseOAuth2):
    """Custom Fitbit OAuth2 authentication backend."""

    name = "fitbit"
    AUTHORIZATION_URL = "https://www.fitbit.com/oauth2/authorize"
    ACCESS_TOKEN_URL = "https://api.fitbit.com/oauth2/token"
    ACCESS_TOKEN_METHOD = "POST"
    SCOPE_SEPARATOR = " "
    REDIRECT_STATE = False
    STATE_PARAMETER = True
    DEFAULT_SCOPE = ["activity", "heartrate", "profile", "settings", "weight"]
    ID_KEY = "user_id"
    EXTRA_DATA = [
        ("access_token", "access_token"),
        ("refresh_token", "refresh_token"),
        ("expires_in", "expires"),
        ("token_type", "token_type"),
        ("user_id", "user_id"),
        ("scope", "scope"),
    ]

    def get_user_details(self, response):
        """Return user details from Fitbit user profile.

        The response parameter should be the user profile data from the /1/user/-/profile.json endpoint.
        """
        user_data = response.get("user", {})

        return {
            "username": str(user_data.get("encodedId", "")),
            "email": "",  # Fitbit doesn't provide email in profile
            "fullname": user_data.get("fullName", ""),
            "first_name": user_data.get("firstName", ""),
            "last_name": user_data.get("lastName", ""),
        }

    def user_data(self, access_token, *args, **kwargs):
        """Load user data from Fitbit API"""
        # For Fitbit, we get the user_id directly from the token response
        # But we can also fetch additional profile data if needed
        user_id = kwargs.get("user_id")

        if not user_id:
            # Check if user_id is in the response (token response)
            if kwargs.get("response"):
                user_id = kwargs.get("response", {}).get("user_id")

        if not user_id:
            logger.error(f"No user_id found in token response or kwargs: {kwargs}")
            return {}

        logger.info(f"Using user_id: {user_id} for Fitbit user_data request")

        try:
            # Optionally fetch user profile for additional details
            url = "https://api.fitbit.com/1/user/-/profile.json"
            headers = {"Authorization": f"Bearer {access_token}"}

            response = self.request(url, headers=headers)
            if response.status_code == 200:
                profile_data = response.json()
                return {"user": profile_data.get("user", {}), "user_id": user_id}
            else:
                logger.warning(f"Could not fetch user profile: {response.status_code}")
                return {"user_id": user_id}

        except Exception as e:
            logger.warning(f"Error fetching user profile: {e}")
            return {"user_id": user_id}

    def get_user_id(self, details, response):
        """Return the unique user ID from the Fitbit OAuth response."""
        # Check multiple possible locations for user_id
        if response:
            # First check if user_id is directly in response (token response)
            if "user_id" in response:
                return response["user_id"]

            # Check nested user structure (profile response)
            if "user" in response and "encodedId" in response["user"]:
                return response["user"]["encodedId"]

        # Fallback to details if available
        if details and "username" in details:
            return details["username"]

        return None

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
            logger.error(f"Error in Fitbit auth_complete: {e}")
            raise

    def request_access_token(self, *args, **kwargs):
        """
        Request access token from Fitbit using authorization code.
        Fitbit requires HTTP Basic Authentication for server-side applications.
        """
        import base64

        code = self.data.get("code")
        client_id = self.setting("KEY")
        client_secret = self.setting("SECRET")
        redirect_uri = kwargs.get("redirect_uri") or self.get_redirect_uri()

        # Fitbit requires HTTP Basic Authentication for server-side apps
        # Authorization: Basic base64(client_id:client_secret)
        auth_string = f"{client_id}:{client_secret}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')

        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
        }

        # Add PKCE code_verifier if available
        code_verifier = self.strategy.session_get("fitbit_code_verifier")
        if code_verifier:
            data["code_verifier"] = code_verifier
            # Clear the code_verifier from session
            self.strategy.session_set("fitbit_code_verifier", None)

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_b64}"
        }

        logger.info(f"Making Fitbit token request with client_id: {client_id[:8]}...")

        response = self.request(self.ACCESS_TOKEN_URL, method="POST", data=data, headers=headers)

        if response.status_code != 200:
            logger.error(f"Fitbit token request failed: {response.status_code} - {response.text}")
            try:
                error_data = response.json()
                raise AuthTokenError(self, error_data)
            except ValueError:
                raise AuthTokenError(self, f"HTTP {response.status_code}: {response.text}")

        response_json = response.json()
        logger.info(f"Fitbit token response keys: {list(response_json.keys())}")

        # Fitbit returns user_id directly in token response
        if "user_id" not in response_json:
            logger.error(f"No user_id in Fitbit token response: {response_json}")
            raise AuthTokenError(self, "No user_id in token response")

        logger.info(f"Successfully obtained Fitbit access token for user: {response_json.get('user_id')}")
        return response_json

    def get_and_store_state(self, state):
        """Generate and store state parameter"""
        self.strategy.session_set("fitbit_state", state)
        return state

    def validate_state(self):
        """Validate state parameter"""
        request_state = self.data.get("state")
        session_state = self.strategy.session_get("fitbit_state")

        if not request_state or request_state != session_state:
            raise AuthStateMissing(self, "state")

        # Clear state from session after validation
        self.strategy.session_set("fitbit_state", None)
        return request_state
    
    def refresh_token(self, token: str, *args, **kwargs) -> dict[str, Any]:
        """Refresh Fitbit access token using refresh token"""
        try:
            key, secret = self.get_key_and_secret()
            response = requests.post(
                self.ACCESS_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": token,
                },
                auth=(key, secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )

            if response.status_code != 200:
                logger.error(f"Fitbit token refresh failed: {response.status_code} - {response.text}")
                return {}

            token_data = response.json()
            logger.info("Successfully refreshed Fitbit access token")
            return token_data if isinstance(token_data, dict) else {}

        except Exception as e:
            logger.error(f"Exception during Fitbit token refresh: {e}")
            return {}


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
