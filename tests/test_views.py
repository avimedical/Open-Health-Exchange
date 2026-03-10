"""
Tests for base views including ProviderViewSet, HealthSyncViewSet, and provider linking views.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory
from rest_framework.test import APIRequestFactory

from base.views import (
    HealthSyncViewSet,
    InitiateProviderLinkingView,
    ProviderLinkErrorView,
    ProviderLinkSuccessView,
    ProviderViewSet,
    _deeplink_redirect,
    provider_linking_status,
    trigger_device_sync,
    unlink_provider,
)


class TestDeeplinkRedirect:
    """Tests for the _deeplink_redirect helper function."""

    def test_deeplink_redirect_creates_html_response(self):
        """Test that deeplink redirect creates an HTML response with the URL."""
        url = "myapp://oauth/success?status=ok"
        response = _deeplink_redirect(url)

        assert response.status_code == 200
        assert "text/html" in response["Content-Type"]
        content = response.content.decode("utf-8")
        assert url in content
        assert 'meta http-equiv="refresh"' in content
        assert "window.location.href" in content

    def test_deeplink_redirect_escapes_url(self):
        """Test that URLs are properly escaped for security."""
        # URL with special characters that need escaping
        url = 'myapp://oauth?error=<script>alert("xss")</script>'
        response = _deeplink_redirect(url)

        content = response.content.decode("utf-8")
        # The URL should be escaped in the content attribute and href
        # Note: The HTML has its own <script> tag for JS redirect, but the XSS payload should be escaped
        assert "&lt;script&gt;" in content  # XSS payload is escaped
        assert 'alert("xss")' not in content  # Quotes are escaped too
        assert "&quot;xss&quot;" in content  # Properly escaped quotes


class TestProviderViewSet:
    """Tests for ProviderViewSet."""

    @pytest.fixture
    def factory(self):
        """Create API request factory."""
        return APIRequestFactory()

    def test_capabilities_returns_supported_data(self, factory):
        """Test capabilities action returns expected data structure."""
        request = factory.get("/api/base/providers/capabilities/")
        viewset = ProviderViewSet()
        viewset.action = "capabilities"
        viewset.request = request
        viewset.format_kwarg = None

        response = viewset.capabilities(request)

        assert response.status_code == 200
        assert "supported_providers" in response.data
        assert "supported_data_types" in response.data
        assert "webhook_endpoints" in response.data
        assert "sync_frequencies" in response.data
        assert "withings" in response.data["supported_providers"]
        assert "fitbit" in response.data["supported_providers"]


class TestHealthSyncViewSet:
    """Tests for HealthSyncViewSet."""

    @pytest.fixture
    def factory(self):
        """Create API request factory."""
        return APIRequestFactory()

    def _wrap_request(self, request):
        """Wrap Django request to add DRF-style attributes."""
        # Add query_params attribute for DRF compatibility

        if hasattr(request, "GET"):
            request.query_params = request.GET
        if not hasattr(request, "data"):
            request.data = {}
        return request

    def test_status_missing_ehr_user_id(self, factory):
        """Test status endpoint returns error when ehr_user_id is missing."""
        request = self._wrap_request(factory.get("/api/base/sync/status/"))
        viewset = HealthSyncViewSet()
        viewset.action = "status"
        viewset.request = request
        viewset.format_kwarg = None

        response = viewset.status(request)

        assert response.status_code == 400
        assert "ehr_user_id parameter is required" in response.data["error"]

    def test_status_user_not_found(self, factory):
        """Test status endpoint returns 404 for non-existent user."""
        request = self._wrap_request(factory.get("/api/base/sync/status/?ehr_user_id=nonexistent"))
        viewset = HealthSyncViewSet()
        viewset.action = "status"
        viewset.request = request
        viewset.format_kwarg = None

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.side_effect = mock_ehr_user.DoesNotExist

            response = viewset.status(request)

        assert response.status_code == 404
        assert "not found" in response.data["error"]

    def test_status_returns_provider_status(self, factory):
        """Test status endpoint returns sync status for user."""
        request = self._wrap_request(factory.get("/api/base/sync/status/?ehr_user_id=test-user&provider=withings"))
        viewset = HealthSyncViewSet()
        viewset.action = "status"
        viewset.request = request
        viewset.format_kwarg = None

        mock_user = MagicMock()
        mock_user.ehr_user_id = "test-user"

        mock_provider_link = MagicMock()
        mock_provider_link.extra_data = {
            "last_health_data_sync": "2024-01-15T10:00:00Z",
            "last_health_sync_success": True,
            "last_health_sync_fhir_resources_created": 10,
            "last_health_sync_errors": 0,
        }

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("base.views.ProviderLink") as mock_link_model:
                mock_link_model.objects.filter.return_value.first.return_value = mock_provider_link

                response = viewset.status(request)

        assert response.status_code == 200
        assert response.data["ehr_user_id"] == "test-user"
        assert response.data["provider"] == "withings"
        assert response.data["status"] == "completed"

    def test_status_all_providers(self, factory):
        """Test status endpoint returns status for all providers when provider not specified."""
        request = self._wrap_request(factory.get("/api/base/sync/status/?ehr_user_id=test-user"))
        viewset = HealthSyncViewSet()
        viewset.action = "status"
        viewset.request = request
        viewset.format_kwarg = None

        mock_user = MagicMock()

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("base.views.ProviderLink") as mock_link_model:
                mock_link_model.objects.filter.return_value.first.return_value = None

                response = viewset.status(request)

        assert response.status_code == 200
        assert "providers" in response.data
        assert "withings" in response.data["providers"]
        assert "fitbit" in response.data["providers"]

    def test_providers_missing_ehr_user_id(self, factory):
        """Test providers endpoint returns error when ehr_user_id is missing."""
        request = self._wrap_request(factory.get("/api/base/sync/providers/"))
        viewset = HealthSyncViewSet()
        viewset.action = "providers"
        viewset.request = request
        viewset.format_kwarg = None

        response = viewset.providers(request)

        assert response.status_code == 400
        assert "ehr_user_id parameter is required" in response.data["error"]

    def test_providers_returns_connected_providers(self, factory):
        """Test providers endpoint returns connected provider links."""
        request = self._wrap_request(factory.get("/api/base/sync/providers/?ehr_user_id=test-user"))
        viewset = HealthSyncViewSet()
        viewset.action = "providers"
        viewset.request = request
        viewset.format_kwarg = None

        mock_user = MagicMock()

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("base.views.ProviderLink") as mock_link_model:
                mock_link_model.objects.filter.return_value = []

                with patch("base.views.ProviderLinkSerializer") as mock_serializer:
                    mock_serializer.return_value.data = []

                    response = viewset.providers(request)

        assert response.status_code == 200
        assert response.data["ehr_user_id"] == "test-user"
        assert "connected_providers" in response.data
        assert response.data["total_providers"] == 0

    def test_devices_missing_ehr_user_id(self, factory):
        """Test devices endpoint returns error when ehr_user_id is missing."""
        request = self._wrap_request(factory.get("/api/base/sync/devices/"))
        viewset = HealthSyncViewSet()
        viewset.action = "devices"
        viewset.request = request
        viewset.format_kwarg = None

        response = viewset.devices(request)

        assert response.status_code == 400
        assert "ehr_user_id parameter is required" in response.data["error"]

    def test_devices_user_not_found(self, factory):
        """Test devices endpoint returns 404 for non-existent user."""
        request = self._wrap_request(factory.get("/api/base/sync/devices/?ehr_user_id=nonexistent"))
        viewset = HealthSyncViewSet()
        viewset.action = "devices"
        viewset.request = request
        viewset.format_kwarg = None

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.side_effect = mock_ehr_user.DoesNotExist

            response = viewset.devices(request)

        assert response.status_code == 404

    def test_devices_returns_device_list(self, factory):
        """Test devices endpoint returns device list from FHIR."""
        request = self._wrap_request(factory.get("/api/base/sync/devices/?ehr_user_id=test-user&provider=withings"))
        viewset = HealthSyncViewSet()
        viewset.action = "devices"
        viewset.request = request
        viewset.format_kwarg = None

        mock_user = MagicMock()
        mock_user.username = "testuser"

        mock_device = {
            "id": "device-123",
            "manufacturer": "Withings",
            "name": "Scale",
            "status": "active",
            "type": [{"text": "scale"}],
            "identifier": [{"system": "https://withings.com", "value": "123456"}],
            "meta": {"lastUpdated": "2024-01-15T10:00:00Z"},
        }

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("publishers.fhir.device_publisher.DevicePublisher") as mock_publisher_class:
                mock_publisher = MagicMock()
                mock_publisher.find_devices_by_provider.return_value = [mock_device]
                mock_publisher_class.return_value = mock_publisher

                response = viewset.devices(request)

        assert response.status_code == 200
        assert response.data["ehr_user_id"] == "test-user"
        assert response.data["total_devices"] == 1
        assert response.data["devices"][0]["id"] == "device-123"

    def test_devices_deduplication(self, factory):
        """Test devices endpoint deduplicates devices by provider_device_id."""
        request = self._wrap_request(factory.get("/api/base/sync/devices/?ehr_user_id=test-user"))
        viewset = HealthSyncViewSet()
        viewset.action = "devices"
        viewset.request = request
        viewset.format_kwarg = None

        mock_user = MagicMock()

        # Two devices with same provider_device_id but different timestamps
        mock_device_old = {
            "id": "device-old",
            "manufacturer": "Withings",
            "name": "Scale",
            "status": "active",
            "type": [],
            "identifier": [{"system": "https://withings.com", "value": "same-device"}],
            "meta": {"lastUpdated": "2024-01-01T10:00:00Z"},
        }
        mock_device_new = {
            "id": "device-new",
            "manufacturer": "Withings",
            "name": "Scale Updated",
            "status": "active",
            "type": [],
            "identifier": [{"system": "https://withings.com", "value": "same-device"}],
            "meta": {"lastUpdated": "2024-01-15T10:00:00Z"},
        }

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("publishers.fhir.device_publisher.DevicePublisher") as mock_publisher_class:
                mock_publisher = MagicMock()
                mock_publisher.find_devices_by_provider.return_value = [mock_device_old, mock_device_new]
                mock_publisher_class.return_value = mock_publisher

                response = viewset.devices(request)

        assert response.status_code == 200
        # Should have only 1 device after deduplication (the newer one)
        assert response.data["total_devices"] == 1
        assert response.data["devices"][0]["id"] == "device-new"

    def test_trigger_device_sync_invalid_data(self, factory):
        """Test trigger_device_sync with invalid request data."""
        request = factory.post("/api/base/sync/trigger_device_sync/", {}, format="json")
        request.data = {}
        viewset = HealthSyncViewSet()
        viewset.action = "trigger_device_sync"
        viewset.request = request
        viewset.format_kwarg = None

        with patch("base.views.DeviceSyncRequestSerializer") as mock_serializer:
            mock_instance = MagicMock()
            mock_instance.is_valid.return_value = False
            mock_instance.errors = {"ehr_user_id": ["This field is required"]}
            mock_serializer.return_value = mock_instance

            response = viewset.trigger_device_sync(request)

        assert response.status_code == 400


class TestInitiateProviderLinkingView:
    """Tests for InitiateProviderLinkingView."""

    @pytest.fixture
    def factory(self):
        """Create request factory."""
        return RequestFactory()

    def test_linking_without_ehr_user_id(self, factory):
        """Test initiating linking without EHR user ID returns error."""
        request = factory.get("/api/base/link/withings/")
        request.user = MagicMock(is_authenticated=False)
        request.session = {}
        request.META = {}

        view = InitiateProviderLinkingView()
        response = view.get(request, "withings")

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No EHR user ID provided" in data["error"]

    def test_linking_unsupported_provider(self, factory):
        """Test initiating linking with unsupported provider returns error."""
        request = factory.get("/api/base/link/unsupported/?ehr_user_id=test-user")
        request.user = MagicMock(is_authenticated=False)
        request.session = {}
        request.META = {}

        view = InitiateProviderLinkingView()
        response = view.get(request, "unsupported")

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "Unsupported provider" in data["error"]

    def test_linking_user_not_found(self, factory):
        """Test initiating linking with non-existent user returns error."""
        request = factory.get("/api/base/link/withings/?ehr_user_id=nonexistent")
        request.user = MagicMock(is_authenticated=False)
        request.session = {}
        request.META = {}

        # EHRUser is imported inside the view's get method from base.models
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.side_effect = mock_ehr_user.DoesNotExist

            view = InitiateProviderLinkingView()
            response = view.get(request, "withings")

        assert response.status_code == 404
        data = json.loads(response.content)
        assert "not found" in data["error"]

    def test_linking_success_redirects_to_oauth(self, factory):
        """Test successful linking initiation redirects to OAuth flow."""
        request = factory.get("/api/base/link/withings/?ehr_user_id=test-user")
        request.user = MagicMock(is_authenticated=False)
        # Use a dict with a save method for session
        session_data = {}

        class MockSession(dict):
            def save(self):
                pass

        request.session = MockSession(session_data)
        request.META = {}

        mock_user = MagicMock()

        # EHRUser is imported inside the view
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("base.views.Provider") as mock_provider:
                mock_provider.DoesNotExist = Exception
                mock_provider.objects.get.side_effect = mock_provider.DoesNotExist

                with patch("base.views.reverse") as mock_reverse:
                    mock_reverse.return_value = "/social/login/withings/"

                    view = InitiateProviderLinkingView()
                    response = view.get(request, "withings")

        assert response.status_code == 302
        assert request.session.get("linking_ehr_user_id") == "test-user"
        assert request.session.get("linking_provider") == "withings"

    def test_linking_with_custom_deeplink_urls(self, factory):
        """Test linking stores custom deeplink URLs in session."""
        request = factory.get(
            "/api/base/link/withings/?ehr_user_id=test-user&success_url=myapp://success&error_url=myapp://error"
        )
        request.user = MagicMock(is_authenticated=False)
        # Use a dict with a save method for session
        session_data = {}

        class MockSession(dict):
            def save(self):
                pass

        request.session = MockSession(session_data)
        request.META = {}

        mock_user = MagicMock()

        # EHRUser is imported inside the view
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("base.views.Provider") as mock_provider:
                mock_provider.DoesNotExist = Exception
                mock_provider.objects.get.side_effect = mock_provider.DoesNotExist

                with patch("base.views.reverse") as mock_reverse:
                    mock_reverse.return_value = "/social/login/withings/"

                    view = InitiateProviderLinkingView()
                    response = view.get(request, "withings")

        assert response.status_code == 302
        assert request.session.get("linking_success_url") == "myapp://success"
        assert request.session.get("linking_error_url") == "myapp://error"

    def test_linking_uses_provider_model_deeplinks(self, factory):
        """Test linking uses deeplink URLs from Provider model when not in query params."""
        request = factory.get("/api/base/link/withings/?ehr_user_id=test-user")
        request.user = MagicMock(is_authenticated=False)

        class MockSession(dict):
            def save(self):
                pass

        request.session = MockSession({})
        request.META = {}

        mock_user = MagicMock()
        mock_provider_obj = MagicMock()
        mock_provider_obj.success_deeplink_url = "myapp://db-success"
        mock_provider_obj.error_deeplink_url = "myapp://db-error"

        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("base.views.Provider") as mock_provider:
                mock_provider.DoesNotExist = Exception
                mock_provider.objects.get.return_value = mock_provider_obj

                with patch("base.views.reverse") as mock_reverse:
                    mock_reverse.return_value = "/social/login/withings/"

                    view = InitiateProviderLinkingView()
                    response = view.get(request, "withings")

        assert response.status_code == 302
        assert request.session.get("linking_success_url") == "myapp://db-success"
        assert request.session.get("linking_error_url") == "myapp://db-error"

    def test_linking_query_params_override_provider_model(self, factory):
        """Test query param deeplinks override Provider model deeplinks."""
        request = factory.get("/api/base/link/withings/?ehr_user_id=test-user&success_url=myapp://query-success")
        request.user = MagicMock(is_authenticated=False)

        class MockSession(dict):
            def save(self):
                pass

        request.session = MockSession({})
        request.META = {}

        mock_user = MagicMock()
        mock_provider_obj = MagicMock()
        mock_provider_obj.success_deeplink_url = "myapp://db-success"
        mock_provider_obj.error_deeplink_url = "myapp://db-error"

        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("base.views.Provider") as mock_provider:
                mock_provider.DoesNotExist = Exception
                mock_provider.objects.get.return_value = mock_provider_obj

                with patch("base.views.reverse") as mock_reverse:
                    mock_reverse.return_value = "/social/login/withings/"

                    view = InitiateProviderLinkingView()
                    response = view.get(request, "withings")

        assert response.status_code == 302
        # Query param overrides Provider model
        assert request.session.get("linking_success_url") == "myapp://query-success"
        # Provider model is used as fallback when query param not provided
        assert request.session.get("linking_error_url") == "myapp://db-error"


class TestProviderLinkingStatus:
    """Tests for provider_linking_status function-based view."""

    @pytest.fixture
    def factory(self):
        """Create API request factory."""
        return APIRequestFactory()

    def test_status_missing_ehr_user_id(self, factory):
        """Test status returns error when ehr_user_id is missing."""
        request = factory.get("/api/base/link/withings/status/")
        request.user = MagicMock(is_authenticated=False)

        response = provider_linking_status(request, "withings")

        assert response.status_code == 400
        assert "No EHR user ID provided" in response.data["error"]

    def test_status_user_not_found(self, factory):
        """Test status returns 404 for non-existent user."""
        request = factory.get("/api/base/link/withings/status/?ehr_user_id=nonexistent")
        request.user = MagicMock(is_authenticated=False)

        # EHRUser is imported inside the function from base.models
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.side_effect = mock_ehr_user.DoesNotExist

            response = provider_linking_status(request, "withings")

        assert response.status_code == 404

    def test_status_returns_link_info(self, factory):
        """Test status returns link information for connected provider."""
        request = factory.get("/api/base/link/withings/status/?ehr_user_id=test-user")
        request.user = MagicMock(is_authenticated=False)

        mock_user = MagicMock()
        mock_link = MagicMock()
        mock_link.provider.name = "Withings"
        mock_link.provider.provider_type = "withings"
        mock_link.external_user_id = "ext-123"
        mock_link.provider.active = True
        mock_link.linked_at = None

        # EHRUser and ProviderLink are imported inside the function
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("base.models.ProviderLink") as mock_link_model:
                mock_link_model.objects.filter.return_value = [mock_link]

                response = provider_linking_status(request, "withings")

        assert response.status_code == 200
        assert response.data["linked"] is True
        assert response.data["total_links"] == 1


class TestProviderLinkSuccessView:
    """Tests for ProviderLinkSuccessView."""

    @pytest.fixture
    def factory(self):
        """Create request factory."""
        return RequestFactory()

    def test_success_view_renders_template(self, factory):
        """Test success view renders template when no deeplink configured."""
        request = factory.get("/api/base/link/success/")
        request.session = {
            "linking_provider": "withings",
            "linking_ehr_user_id": "test-user",
        }

        view = ProviderLinkSuccessView()

        with patch("base.views.render") as mock_render:
            mock_render.return_value = MagicMock(status_code=200)
            _response = view.get(request)

        mock_render.assert_called_once()
        assert "base/provider_link_success.html" in str(mock_render.call_args)

    def test_success_view_redirects_to_deeplink(self, factory):
        """Test success view redirects to deeplink when configured."""
        request = factory.get("/api/base/link/success/")
        request.session = {
            "linking_provider": "withings",
            "linking_ehr_user_id": "test-user",
            "linking_success_url": "myapp://oauth/success",
        }

        view = ProviderLinkSuccessView()
        response = view.get(request)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "myapp://oauth/success" in content
        assert "provider=withings" in content
        assert "ehr_user_id=test-user" in content
        assert "status=success" in content

    def test_success_view_clears_session(self, factory):
        """Test success view clears session data after processing."""
        request = factory.get("/api/base/link/success/")
        request.session = {
            "linking_provider": "withings",
            "linking_ehr_user_id": "test-user",
            "linking_timestamp": "2024-01-15T10:00:00Z",
            "linking_success_url": "myapp://success",
            "linking_error_url": "myapp://error",
        }

        view = ProviderLinkSuccessView()
        view.get(request)

        assert request.session.get("linking_provider") is None
        assert request.session.get("linking_ehr_user_id") is None
        assert request.session.get("linking_success_url") is None
        assert request.session.get("linking_error_url") is None


class TestProviderLinkErrorView:
    """Tests for ProviderLinkErrorView."""

    @pytest.fixture
    def factory(self):
        """Create request factory."""
        return RequestFactory()

    def test_error_view_renders_template(self, factory):
        """Test error view renders template when no deeplink configured."""
        request = factory.get("/api/base/link/error/?error=access_denied&error_description=User%20denied")
        request.session = {
            "linking_provider": "withings",
            "linking_ehr_user_id": "test-user",
        }

        view = ProviderLinkErrorView()

        with patch("base.views.render") as mock_render:
            mock_render.return_value = MagicMock(status_code=200)
            _response = view.get(request)

        mock_render.assert_called_once()
        call_args = mock_render.call_args
        assert "base/provider_link_error.html" in str(call_args)
        context = call_args[0][2]
        assert context["error_code"] == "access_denied"
        assert context["error_message"] == "User denied"

    def test_error_view_redirects_to_deeplink(self, factory):
        """Test error view redirects to deeplink when configured."""
        request = factory.get("/api/base/link/error/?error=access_denied&error_description=User%20denied")
        request.session = {
            "linking_provider": "withings",
            "linking_ehr_user_id": "test-user",
            "linking_error_url": "myapp://oauth/error",
        }

        view = ProviderLinkErrorView()
        response = view.get(request)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "myapp://oauth/error" in content
        assert "error=access_denied" in content
        assert "status=error" in content


class TestTriggerDeviceSync:
    """Tests for trigger_device_sync function-based view."""

    @pytest.fixture
    def factory(self):
        """Create API request factory."""
        return APIRequestFactory()

    def test_trigger_missing_ehr_user_id(self, factory):
        """Test trigger returns error when ehr_user_id is missing."""
        request = factory.post("/api/base/sync/trigger/withings/", {}, format="json")
        request.user = MagicMock(is_authenticated=False)
        request.data = {}

        response = trigger_device_sync(request, "withings")

        assert response.status_code == 400
        assert "No EHR user ID provided" in response.data["error"]

    def test_trigger_user_not_found(self, factory):
        """Test trigger returns 404 for non-existent user."""
        request = factory.post("/api/base/sync/trigger/withings/", {"ehr_user_id": "nonexistent"}, format="json")
        request.user = MagicMock(is_authenticated=False)
        request.data = {"ehr_user_id": "nonexistent"}

        # EHRUser is imported inside the function from base.models
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.side_effect = mock_ehr_user.DoesNotExist

            response = trigger_device_sync(request, "withings")

        assert response.status_code == 404

    def test_trigger_no_provider_link(self, factory):
        """Test trigger returns 404 when no provider link exists."""
        request = factory.post("/api/base/sync/trigger/withings/", {"ehr_user_id": "test-user"}, format="json")
        request.user = MagicMock(is_authenticated=False)
        request.data = {"ehr_user_id": "test-user"}

        mock_user = MagicMock()

        # EHRUser and ProviderLink are imported inside the function
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            with patch("base.models.ProviderLink") as mock_link_model:
                mock_link_model.objects.filter.return_value.first.return_value = None

                response = trigger_device_sync(request, "withings")

        assert response.status_code == 404
        assert "No active" in response.data["error"]


class TestUnlinkProvider:
    """Tests for unlink_provider function-based view."""

    @pytest.fixture
    def factory(self):
        """Create API request factory."""
        return APIRequestFactory()

    def test_unlink_missing_ehr_user_id(self, factory):
        """Test unlink returns error when ehr_user_id is missing."""
        request = factory.post("/api/base/unlink/withings/", {}, format="json")
        request.user = MagicMock(is_authenticated=False)
        request.data = {}
        request.query_params = {}

        response = unlink_provider(request, "withings")

        assert response.status_code == 400
        assert "No EHR user ID provided" in response.data["error"]

    def test_unlink_unsupported_provider(self, factory):
        """Test unlink returns error for unsupported provider."""
        request = factory.post("/api/base/unlink/unsupported/", {"ehr_user_id": "test-user"}, format="json")
        request.user = MagicMock(is_authenticated=False)
        request.data = {"ehr_user_id": "test-user"}
        request.query_params = {}

        response = unlink_provider(request, "unsupported")

        assert response.status_code == 400
        assert "Unsupported provider" in response.data["error"]

    def test_unlink_user_not_found(self, factory):
        """Test unlink returns 404 for non-existent user."""
        request = factory.post("/api/base/unlink/withings/", {"ehr_user_id": "nonexistent"}, format="json")
        request.user = MagicMock(is_authenticated=False)
        request.data = {"ehr_user_id": "nonexistent"}
        request.query_params = {}

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.side_effect = mock_ehr_user.DoesNotExist

            response = unlink_provider(request, "withings")

        assert response.status_code == 404

    def test_unlink_success(self, factory):
        """Test successful provider unlinking."""
        request = factory.post("/api/base/unlink/withings/", {"ehr_user_id": "test-user"}, format="json")
        request.user = MagicMock(is_authenticated=False)
        request.data = {"ehr_user_id": "test-user"}
        request.query_params = {}

        mock_user = MagicMock()
        mock_social_auth = MagicMock()

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            # UserSocialAuth is imported inside the function from social_django.models
            with patch("social_django.models.UserSocialAuth") as mock_social_model:
                mock_social_model.DoesNotExist = Exception
                mock_social_model.objects.get.return_value = mock_social_auth

                response = unlink_provider(request, "withings")

        assert response.status_code == 200
        assert response.data["status"] == "unlinked"
        mock_social_auth.delete.assert_called_once()

    def test_unlink_no_connection_found(self, factory):
        """Test unlink returns 404 when no connection exists."""
        request = factory.post("/api/base/unlink/withings/", {"ehr_user_id": "test-user"}, format="json")
        request.user = MagicMock(is_authenticated=False)
        request.data = {"ehr_user_id": "test-user"}
        request.query_params = {}

        mock_user = MagicMock()

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            # UserSocialAuth is imported inside the function
            with patch("social_django.models.UserSocialAuth") as mock_social_model:
                mock_social_model.DoesNotExist = Exception
                mock_social_model.objects.get.side_effect = mock_social_model.DoesNotExist

                with patch("base.views.ProviderLink") as mock_link_model:
                    mock_link_model.objects.filter.return_value.first.return_value = None

                    response = unlink_provider(request, "withings")

        assert response.status_code == 404
        assert "No withings connection found" in response.data["error"]

    def test_unlink_cleans_up_orphan_link(self, factory):
        """Test unlink cleans up orphan ProviderLink when UserSocialAuth doesn't exist."""
        request = factory.post("/api/base/unlink/withings/", {"ehr_user_id": "test-user"}, format="json")
        request.user = MagicMock(is_authenticated=False)
        request.data = {"ehr_user_id": "test-user"}
        request.query_params = {}

        mock_user = MagicMock()
        mock_orphan_link = MagicMock()

        with patch("base.views.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.return_value = mock_user

            # UserSocialAuth is imported inside the function
            with patch("social_django.models.UserSocialAuth") as mock_social_model:
                mock_social_model.DoesNotExist = Exception
                mock_social_model.objects.get.side_effect = mock_social_model.DoesNotExist

                with patch("base.views.ProviderLink") as mock_link_model:
                    mock_link_model.objects.filter.return_value.first.return_value = mock_orphan_link

                    response = unlink_provider(request, "withings")

        assert response.status_code == 200
        assert "orphan link" in response.data["message"]
        mock_orphan_link.delete.assert_called_once()
