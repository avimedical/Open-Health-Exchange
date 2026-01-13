"""
Tests for OAuth2 authentication backends (Withings, Fitbit, OIDC).
"""

from unittest.mock import MagicMock, patch

import pytest
from social_core.exceptions import AuthStateMissing, AuthTokenError

from base.backends import FitbitOAuth2, OidcAuthenticationBackend, WithingsOAuth2


class TestWithingsOAuth2:
    """Tests for Withings OAuth2 backend."""

    @pytest.fixture
    def backend(self):
        """Create a Withings OAuth2 backend instance."""
        strategy = MagicMock()
        strategy.session = {}
        strategy.session_get = lambda key: strategy.session.get(key)
        strategy.session_set = lambda key, value: strategy.session.__setitem__(key, value)
        backend = WithingsOAuth2(strategy)
        backend.data = {}
        return backend

    def test_backend_name(self, backend):
        """Test backend has correct name."""
        assert backend.name == "withings"

    def test_default_scope(self, backend):
        """Test backend has correct default scope."""
        assert "user.info" in backend.DEFAULT_SCOPE
        assert "user.metrics" in backend.DEFAULT_SCOPE
        assert "user.activity" in backend.DEFAULT_SCOPE

    def test_get_user_details(self, backend):
        """Test extracting user details from response."""
        response = {
            "body": {
                "user": {
                    "id": "123456",
                    "email": "test@example.com",
                    "firstname": "John",
                    "lastname": "Doe",
                }
            }
        }

        details = backend.get_user_details(response)

        assert details["username"] == "123456"
        assert details["email"] == "test@example.com"
        assert details["first_name"] == "John"
        assert details["last_name"] == "Doe"
        assert details["fullname"] == "John Doe"

    def test_get_user_details_empty_response(self, backend):
        """Test handling empty response."""
        response = {}

        details = backend.get_user_details(response)

        # When there's no user data, username will be str(None) = "None"
        assert details["username"] == "None"
        assert details["email"] == ""

    def test_user_data(self, backend):
        """Test user_data method returns userid."""
        result = backend.user_data(
            access_token="test-token",
            userid="123456",
        )

        assert result["userid"] == "123456"

    def test_user_data_from_response(self, backend):
        """Test user_data extracts userid from response."""
        result = backend.user_data(access_token="test-token", response={"userid": "789"})

        assert result["userid"] == "789"

    def test_user_data_from_nested_response(self, backend):
        """Test user_data extracts userid from nested body structure."""
        result = backend.user_data(access_token="test-token", response={"body": {"userid": "456"}})

        assert result["userid"] == "456"

    def test_user_data_no_userid(self, backend):
        """Test user_data returns empty dict when no userid found."""
        result = backend.user_data(access_token="test-token")

        assert result == {}

    def test_get_user_id_from_response(self, backend):
        """Test get_user_id extracts ID from response."""
        response = {"userid": "123456"}
        details = {}

        user_id = backend.get_user_id(details, response)

        assert user_id == "123456"

    def test_get_user_id_from_nested_body(self, backend):
        """Test get_user_id extracts ID from nested body structure."""
        response = {"body": {"user": {"id": "789"}}}
        details = {}

        user_id = backend.get_user_id(details, response)

        assert user_id == "789"

    def test_get_user_id_from_body_userid(self, backend):
        """Test get_user_id extracts ID from body.userid."""
        response = {"body": {"userid": "456"}}
        details = {}

        user_id = backend.get_user_id(details, response)

        assert user_id == "456"

    def test_get_user_id_fallback_to_details(self, backend):
        """Test get_user_id falls back to details when response has no ID."""
        response = {}
        details = {"username": "fallback-user"}

        user_id = backend.get_user_id(details, response)

        assert user_id == "fallback-user"

    def test_get_session_state(self, backend):
        """Test get_session_state retrieves state from session."""
        backend.strategy.session["withings_state"] = "test-state"

        state = backend.get_session_state()

        assert state == "test-state"

    def test_validate_state_success(self, backend):
        """Test validate_state returns state when present."""
        backend.strategy.session["withings_state"] = "valid-state"

        state = backend.validate_state()

        assert state == "valid-state"

    def test_validate_state_missing(self, backend):
        """Test validate_state raises exception when state missing."""
        with pytest.raises(AuthStateMissing):
            backend.validate_state()

    def test_auth_complete_passes_authenticated_user(self, backend):
        """Test auth_complete passes authenticated user to parent."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        backend.strategy.request = MagicMock()
        backend.strategy.request.user = mock_user

        with patch.object(backend.__class__.__bases__[0], "auth_complete") as mock_parent:
            mock_parent.return_value = mock_user
            backend.auth_complete()

            # Verify user was passed
            _, kwargs = mock_parent.call_args
            assert kwargs.get("user") == mock_user

    def test_request_access_token_success(self, backend):
        """Test successful token request."""
        backend.data = {"code": "auth-code"}
        backend.setting = MagicMock(side_effect=lambda x: "client-id" if x == "KEY" else "client-secret")
        backend.get_redirect_uri = MagicMock(return_value="https://example.com/callback")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": 0, "body": {"access_token": "token"}}
        backend.request = MagicMock(return_value=mock_response)

        result = backend.request_access_token()

        assert result["access_token"] == "token"

    def test_request_access_token_http_error(self, backend):
        """Test token request handles HTTP error."""
        backend.data = {"code": "auth-code"}
        backend.setting = MagicMock(side_effect=lambda x: "client-id" if x == "KEY" else "client-secret")
        backend.get_redirect_uri = MagicMock(return_value="https://example.com/callback")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "invalid_grant"}
        backend.request = MagicMock(return_value=mock_response)

        with pytest.raises(AuthTokenError):
            backend.request_access_token()

    def test_request_access_token_api_error(self, backend):
        """Test token request handles Withings API error status."""
        backend.data = {"code": "auth-code"}
        backend.setting = MagicMock(side_effect=lambda x: "client-id" if x == "KEY" else "client-secret")
        backend.get_redirect_uri = MagicMock(return_value="https://example.com/callback")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": 503, "error": "service unavailable"}
        backend.request = MagicMock(return_value=mock_response)

        with pytest.raises(AuthTokenError):
            backend.request_access_token()

    def test_refresh_token_success(self, backend):
        """Test successful token refresh."""
        backend.get_key_and_secret = MagicMock(return_value=("client-id", "client-secret"))

        with patch("base.backends.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": 0,
                "body": {"access_token": "new-token", "refresh_token": "new-refresh"},
            }
            mock_post.return_value = mock_response

            result = backend.refresh_token("old-refresh-token")

        assert result["access_token"] == "new-token"

    def test_refresh_token_http_error(self, backend):
        """Test token refresh handles HTTP error."""
        backend.get_key_and_secret = MagicMock(return_value=("client-id", "client-secret"))

        with patch("base.backends.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = "invalid_grant"
            mock_post.return_value = mock_response

            result = backend.refresh_token("old-refresh-token")

        assert result == {}

    def test_refresh_token_api_error(self, backend):
        """Test token refresh handles API error status."""
        backend.get_key_and_secret = MagicMock(return_value=("client-id", "client-secret"))

        with patch("base.backends.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": 503, "error": "service unavailable"}
            mock_post.return_value = mock_response

            result = backend.refresh_token("old-refresh-token")

        assert result == {}

    def test_refresh_token_exception(self, backend):
        """Test token refresh handles exception."""
        backend.get_key_and_secret = MagicMock(return_value=("client-id", "client-secret"))

        with patch("base.backends.requests.post") as mock_post:
            mock_post.side_effect = Exception("Network error")

            result = backend.refresh_token("old-refresh-token")

        assert result == {}


class TestFitbitOAuth2:
    """Tests for Fitbit OAuth2 backend."""

    @pytest.fixture
    def backend(self):
        """Create a Fitbit OAuth2 backend instance."""
        strategy = MagicMock()
        strategy.session = {}
        strategy.session_get = lambda key: strategy.session.get(key)
        strategy.session_set = lambda key, value: strategy.session.__setitem__(key, value)
        backend = FitbitOAuth2(strategy)
        backend.data = {}
        return backend

    def test_backend_name(self, backend):
        """Test backend has correct name."""
        assert backend.name == "fitbit"

    def test_default_scope(self, backend):
        """Test backend has correct default scope."""
        assert "activity" in backend.DEFAULT_SCOPE
        assert "heartrate" in backend.DEFAULT_SCOPE
        assert "profile" in backend.DEFAULT_SCOPE

    def test_get_user_details(self, backend):
        """Test extracting user details from response."""
        response = {
            "user": {
                "encodedId": "ABC123",
                "fullName": "John Doe",
                "firstName": "John",
                "lastName": "Doe",
            }
        }

        details = backend.get_user_details(response)

        assert details["username"] == "ABC123"
        assert details["fullname"] == "John Doe"
        assert details["first_name"] == "John"
        assert details["last_name"] == "Doe"
        assert details["email"] == ""  # Fitbit doesn't provide email

    def test_get_user_details_empty_response(self, backend):
        """Test handling empty response."""
        response = {}

        details = backend.get_user_details(response)

        assert details["username"] == ""
        assert details["email"] == ""

    def test_user_data_with_user_id(self, backend):
        """Test user_data returns data when user_id provided."""
        backend.request = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user": {"encodedId": "ABC123"}}
        backend.request.return_value = mock_response

        result = backend.user_data(access_token="test-token", user_id="ABC123")

        assert result["user_id"] == "ABC123"

    def test_user_data_from_response(self, backend):
        """Test user_data extracts user_id from response."""
        backend.request = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user": {"encodedId": "XYZ789"}}
        backend.request.return_value = mock_response

        result = backend.user_data(access_token="test-token", response={"user_id": "XYZ789"})

        assert result["user_id"] == "XYZ789"

    def test_user_data_no_user_id(self, backend):
        """Test user_data returns empty dict when no user_id found."""
        result = backend.user_data(access_token="test-token")

        assert result == {}

    def test_user_data_api_error(self, backend):
        """Test user_data handles API error gracefully."""
        backend.request = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        backend.request.return_value = mock_response

        result = backend.user_data(access_token="test-token", user_id="ABC123")

        assert result["user_id"] == "ABC123"

    def test_get_user_id_from_response(self, backend):
        """Test get_user_id extracts ID from response."""
        response = {"user_id": "ABC123"}
        details = {}

        user_id = backend.get_user_id(details, response)

        assert user_id == "ABC123"

    def test_get_user_id_from_profile(self, backend):
        """Test get_user_id extracts ID from profile response."""
        response = {"user": {"encodedId": "XYZ789"}}
        details = {}

        user_id = backend.get_user_id(details, response)

        assert user_id == "XYZ789"

    def test_get_user_id_fallback_to_details(self, backend):
        """Test get_user_id falls back to details."""
        response = {}
        details = {"username": "fallback-user"}

        user_id = backend.get_user_id(details, response)

        assert user_id == "fallback-user"

    def test_auth_complete_passes_authenticated_user(self, backend):
        """Test auth_complete passes authenticated user to parent."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        backend.strategy.request = MagicMock()
        backend.strategy.request.user = mock_user

        with patch.object(backend.__class__.__bases__[0], "auth_complete") as mock_parent:
            mock_parent.return_value = mock_user
            backend.auth_complete()

            _, kwargs = mock_parent.call_args
            assert kwargs.get("user") == mock_user

    def test_request_access_token_success(self, backend):
        """Test successful token request with Basic auth."""
        backend.data = {"code": "auth-code"}
        backend.setting = MagicMock(side_effect=lambda x: "client-id" if x == "KEY" else "client-secret")
        backend.get_redirect_uri = MagicMock(return_value="https://example.com/callback")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "token", "refresh_token": "refresh", "user_id": "ABC123"}
        backend.request = MagicMock(return_value=mock_response)

        result = backend.request_access_token()

        assert result["access_token"] == "token"
        assert result["user_id"] == "ABC123"

        # Verify Basic auth header was used
        call_args = backend.request.call_args
        headers = call_args[1]["headers"]
        assert "Basic" in headers["Authorization"]

    def test_request_access_token_with_pkce(self, backend):
        """Test token request includes PKCE code_verifier."""
        backend.data = {"code": "auth-code"}
        backend.setting = MagicMock(side_effect=lambda x: "client-id" if x == "KEY" else "client-secret")
        backend.get_redirect_uri = MagicMock(return_value="https://example.com/callback")
        backend.strategy.session["fitbit_code_verifier"] = "pkce-verifier"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "token", "user_id": "ABC123"}
        backend.request = MagicMock(return_value=mock_response)

        backend.request_access_token()

        call_args = backend.request.call_args
        data = call_args[1]["data"]
        assert data["code_verifier"] == "pkce-verifier"
        # PKCE verifier should be cleared from session
        assert backend.strategy.session.get("fitbit_code_verifier") is None

    def test_request_access_token_http_error(self, backend):
        """Test token request handles HTTP error."""
        backend.data = {"code": "auth-code"}
        backend.setting = MagicMock(side_effect=lambda x: "client-id" if x == "KEY" else "client-secret")
        backend.get_redirect_uri = MagicMock(return_value="https://example.com/callback")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"
        mock_response.json.return_value = {"error": "invalid_grant"}
        backend.request = MagicMock(return_value=mock_response)

        with pytest.raises(AuthTokenError):
            backend.request_access_token()

    def test_request_access_token_no_user_id(self, backend):
        """Test token request raises error when no user_id in response."""
        backend.data = {"code": "auth-code"}
        backend.setting = MagicMock(side_effect=lambda x: "client-id" if x == "KEY" else "client-secret")
        backend.get_redirect_uri = MagicMock(return_value="https://example.com/callback")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "token"}  # No user_id
        backend.request = MagicMock(return_value=mock_response)

        with pytest.raises(AuthTokenError):
            backend.request_access_token()

    def test_get_and_store_state(self, backend):
        """Test get_and_store_state stores state in session."""
        state = backend.get_and_store_state("my-state")

        assert state == "my-state"
        assert backend.strategy.session.get("fitbit_state") == "my-state"

    def test_validate_state_success(self, backend):
        """Test validate_state returns state when valid."""
        backend.strategy.session["fitbit_state"] = "valid-state"
        backend.data = {"state": "valid-state"}

        state = backend.validate_state()

        assert state == "valid-state"
        # State should be cleared after validation
        assert backend.strategy.session.get("fitbit_state") is None

    def test_validate_state_missing(self, backend):
        """Test validate_state raises exception when state missing."""
        backend.data = {}

        with pytest.raises(AuthStateMissing):
            backend.validate_state()

    def test_validate_state_mismatch(self, backend):
        """Test validate_state raises exception when state doesn't match."""
        backend.strategy.session["fitbit_state"] = "expected-state"
        backend.data = {"state": "different-state"}

        with pytest.raises(AuthStateMissing):
            backend.validate_state()

    def test_refresh_token_success(self, backend):
        """Test successful token refresh."""
        backend.get_key_and_secret = MagicMock(return_value=("client-id", "client-secret"))

        with patch("base.backends.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"access_token": "new-token", "refresh_token": "new-refresh"}
            mock_post.return_value = mock_response

            result = backend.refresh_token("old-refresh-token")

        assert result["access_token"] == "new-token"
        # Verify auth tuple was used (Fitbit uses HTTP Basic)
        call_args = mock_post.call_args
        assert call_args[1]["auth"] == ("client-id", "client-secret")

    def test_refresh_token_http_error(self, backend):
        """Test token refresh handles HTTP error."""
        backend.get_key_and_secret = MagicMock(return_value=("client-id", "client-secret"))

        with patch("base.backends.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = "invalid_grant"
            mock_post.return_value = mock_response

            result = backend.refresh_token("old-refresh-token")

        assert result == {}

    def test_refresh_token_exception(self, backend):
        """Test token refresh handles exception."""
        backend.get_key_and_secret = MagicMock(return_value=("client-id", "client-secret"))

        with patch("base.backends.requests.post") as mock_post:
            mock_post.side_effect = Exception("Network error")

            result = backend.refresh_token("old-refresh-token")

        assert result == {}


class TestOidcAuthenticationBackend:
    """Tests for OIDC authentication backend."""

    @pytest.fixture
    def backend(self):
        """Create an OIDC backend instance."""
        backend = OidcAuthenticationBackend()
        return backend

    def test_get_username(self, backend):
        """Test get_username extracts sub claim."""
        claims = {"sub": "user-123"}

        username = backend.get_username(claims)

        assert username == "user-123"

    def test_filter_users_by_claims(self, backend):
        """Test filter_users_by_claims filters by username."""
        claims = {"sub": "user-123"}

        with patch.object(backend, "UserModel") as mock_model:
            mock_model.objects.filter.return_value = []

            backend.filter_users_by_claims(claims)

            mock_model.objects.filter.assert_called_once_with(username="user-123")

    def test_create_user(self, backend):
        """Test create_user creates user with groups."""
        claims = {"sub": "user-123", "groups": ["admin", "users"]}

        with patch.object(backend, "UserModel") as mock_model:
            mock_user = MagicMock()
            mock_model.objects.create_user.return_value = mock_user

            with patch("base.backends.Group") as mock_group:
                mock_group.objects.get_or_create.side_effect = [
                    (MagicMock(name="admin"), True),
                    (MagicMock(name="users"), True),
                ]

                user = backend.create_user(claims)

        assert user == mock_user
        mock_model.objects.create_user.assert_called_once_with("user-123", email="")
        mock_user.groups.set.assert_called_once()

    def test_create_user_no_groups(self, backend):
        """Test create_user handles missing groups claim."""
        claims = {"sub": "user-123"}

        with patch.object(backend, "UserModel") as mock_model:
            mock_user = MagicMock()
            mock_model.objects.create_user.return_value = mock_user

            with patch("base.backends.Group") as mock_group:
                mock_group.objects.get_or_create.return_value = (MagicMock(), False)

                user = backend.create_user(claims)

        assert user == mock_user
        # Should set empty groups list
        mock_user.groups.set.assert_called_once_with([])

    def test_update_user(self, backend):
        """Test update_user updates groups."""
        mock_user = MagicMock()
        claims = {"groups": ["new-group"]}

        with patch.object(backend.__class__.__bases__[0], "update_user") as mock_parent:
            mock_parent.return_value = mock_user

            with patch("base.backends.Group") as mock_group:
                mock_group.objects.get_or_create.return_value = (MagicMock(name="new-group"), False)

                result = backend.update_user(mock_user, claims)

        assert result == mock_user
        mock_user.groups.set.assert_called_once()

    def test_userinfo_needs_update_different_groups(self, backend):
        """Test userinfo_needs_update returns True when groups differ."""
        mock_user = MagicMock()
        mock_user.groups.all.return_value = [MagicMock(name="old-group")]
        claims = {"groups": ["new-group"]}

        with patch("base.backends.Group") as mock_group:
            mock_group.objects.get_or_create.return_value = (MagicMock(name="new-group"), False)

            result = backend.userinfo_needs_update(mock_user, claims)

        # Groups are different, so update is needed
        assert result is True

    def test_update_user_if_outdated_updates(self, backend):
        """Test update_user_if_outdated updates when needed."""
        mock_user = MagicMock()
        claims = {"groups": ["new-group"]}

        with patch.object(backend, "userinfo_needs_update") as mock_needs_update:
            mock_needs_update.return_value = True

            with patch.object(backend, "update_user") as mock_update:
                mock_update.return_value = mock_user

                result = backend.update_user_if_outdated(mock_user, claims, "access-token")

        mock_update.assert_called_once_with(mock_user, claims)
        assert result == mock_user

    def test_update_user_if_outdated_no_update(self, backend):
        """Test update_user_if_outdated skips update when not needed."""
        mock_user = MagicMock()
        claims = {"groups": ["same-group"]}

        with patch.object(backend, "userinfo_needs_update") as mock_needs_update:
            mock_needs_update.return_value = False

            with patch.object(backend, "update_user") as mock_update:
                result = backend.update_user_if_outdated(mock_user, claims, "access-token")

        mock_update.assert_not_called()
        assert result == mock_user

    def test_get_or_create_user_single_user(self, backend):
        """Test get_or_create_user returns existing user when one found."""
        mock_user = MagicMock()

        with patch.object(backend, "get_userinfo") as mock_userinfo:
            mock_userinfo.return_value = {"sub": "user-123", "groups": []}

            with patch.object(backend, "verify_claims") as mock_verify:
                mock_verify.return_value = True

                with patch.object(backend, "filter_users_by_claims") as mock_filter:
                    mock_filter.return_value = [mock_user]

                    with patch.object(backend, "update_user_if_outdated") as mock_update:
                        mock_update.return_value = mock_user

                        result = backend.get_or_create_user("access", "id", {})

        assert result == mock_user

    def test_get_or_create_user_creates_new(self, backend):
        """Test get_or_create_user creates new user when none found."""
        mock_new_user = MagicMock()

        with patch.object(backend, "get_userinfo") as mock_userinfo:
            mock_userinfo.return_value = {"sub": "user-123", "groups": []}

            with patch.object(backend, "verify_claims") as mock_verify:
                mock_verify.return_value = True

                with patch.object(backend, "filter_users_by_claims") as mock_filter:
                    mock_filter.return_value = []

                    with patch.object(backend, "get_settings") as mock_settings:
                        mock_settings.return_value = True

                        with patch.object(backend, "create_user") as mock_create:
                            mock_create.return_value = mock_new_user

                            result = backend.get_or_create_user("access", "id", {})

        assert result == mock_new_user

    def test_get_or_create_user_multiple_users_raises(self, backend):
        """Test get_or_create_user raises when multiple users match."""
        from django.core.exceptions import SuspiciousOperation

        with patch.object(backend, "get_userinfo") as mock_userinfo:
            mock_userinfo.return_value = {"sub": "user-123", "groups": []}

            with patch.object(backend, "verify_claims") as mock_verify:
                mock_verify.return_value = True

                with patch.object(backend, "filter_users_by_claims") as mock_filter:
                    mock_filter.return_value = [MagicMock(), MagicMock()]  # Two users

                    with pytest.raises(SuspiciousOperation, match="Multiple users"):
                        backend.get_or_create_user("access", "id", {})

    def test_get_or_create_user_invalid_claims_raises(self, backend):
        """Test get_or_create_user raises when claims verification fails."""
        from django.core.exceptions import SuspiciousOperation

        with patch.object(backend, "get_userinfo") as mock_userinfo:
            mock_userinfo.return_value = {"sub": "user-123"}

            with patch.object(backend, "verify_claims") as mock_verify:
                mock_verify.return_value = False

                with pytest.raises(SuspiciousOperation, match="Claims verification"):
                    backend.get_or_create_user("access", "id", {})

    def test_get_or_create_user_no_create_returns_none(self, backend):
        """Test get_or_create_user returns None when user creation disabled."""
        with patch.object(backend, "get_userinfo") as mock_userinfo:
            mock_userinfo.return_value = {"sub": "user-123", "groups": []}

            with patch.object(backend, "verify_claims") as mock_verify:
                mock_verify.return_value = True

                with patch.object(backend, "filter_users_by_claims") as mock_filter:
                    mock_filter.return_value = []

                    with patch.object(backend, "get_settings") as mock_settings:
                        mock_settings.return_value = False  # User creation disabled

                        result = backend.get_or_create_user("access", "id", {})

        assert result is None
