"""
Tests for base app authentication backends.
"""

from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from base.backends import OidcAuthenticationBackend


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test-oidc-userinfo",
        }
    }
)
class TestOidcUserinfoCaching(SimpleTestCase):
    """The OIDC userinfo response is cached per access_token to avoid hitting
    the accounts service on every authenticated request."""

    def setUp(self):
        cache.clear()
        self.backend = OidcAuthenticationBackend()
        self.claims = {"sub": "user-abc", "groups": ["patients"]}

    @patch("mozilla_django_oidc.auth.OIDCAuthenticationBackend.get_userinfo")
    def test_second_call_with_same_token_hits_cache(self, mock_parent):
        mock_parent.return_value = self.claims

        first = self.backend.get_userinfo("token-A", None, None)
        second = self.backend.get_userinfo("token-A", None, None)

        self.assertEqual(first, self.claims)
        self.assertEqual(second, self.claims)
        self.assertEqual(mock_parent.call_count, 1)

    @patch("mozilla_django_oidc.auth.OIDCAuthenticationBackend.get_userinfo")
    def test_different_token_bypasses_cache(self, mock_parent):
        mock_parent.side_effect = [self.claims, {"sub": "user-xyz", "groups": []}]

        self.backend.get_userinfo("token-A", None, None)
        self.backend.get_userinfo("token-B", None, None)

        self.assertEqual(mock_parent.call_count, 2)

    @patch("mozilla_django_oidc.auth.OIDCAuthenticationBackend.get_userinfo")
    def test_upstream_error_propagates_and_is_not_cached(self, mock_parent):
        mock_parent.side_effect = [requests.HTTPError("500"), self.claims]

        with self.assertRaises(requests.HTTPError):
            self.backend.get_userinfo("token-A", None, None)

        result = self.backend.get_userinfo("token-A", None, None)

        self.assertEqual(result, self.claims)
        self.assertEqual(mock_parent.call_count, 2)
