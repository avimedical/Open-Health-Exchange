"""
Tests for OAuth pipeline functions.
"""

from unittest.mock import MagicMock, patch

import pytest
from social_core.exceptions import AuthForbidden

from base.pipeline import (
    associate_by_token_user,
    create_provider_link,
    handle_existing_social_association,
    initialize_provider_services,
)


class TestAssociateByTokenUser:
    """Tests for associate_by_token_user pipeline function."""

    @pytest.fixture
    def mock_strategy(self):
        """Create mock strategy object."""
        strategy = MagicMock()
        strategy.session = {}
        strategy.session_get = lambda key: strategy.session.get(key)
        strategy.session_set = lambda key, value: strategy.session.__setitem__(key, value)
        strategy.request = MagicMock()
        strategy.request.GET = {}
        strategy.request.user = MagicMock()
        strategy.request.user.is_authenticated = False
        return strategy

    @pytest.fixture
    def mock_backend(self):
        """Create mock backend."""
        backend = MagicMock()
        backend.name = "withings"
        return backend

    def test_associate_with_existing_user_no_session(self, mock_strategy, mock_backend):
        """Test association when user is already provided but no session linking data."""
        existing_user = MagicMock()
        result = associate_by_token_user(mock_strategy, {}, mock_backend, user=existing_user)

        # Should return None and keep existing user when no session override
        assert result is None

    def test_session_ehr_user_overrides_existing_user(self, mock_strategy, mock_backend):
        """Test that session EHR user ID always takes priority over existing user."""
        mock_strategy.session["linking_ehr_user_id"] = "correct-ehr-123"
        mock_strategy.session["linking_provider"] = "withings"

        wrong_user = MagicMock()
        wrong_user.username = "wrong-user"
        correct_user = MagicMock()
        correct_user.username = "correct-user"

        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.objects.get.return_value = correct_user

            result = associate_by_token_user(mock_strategy, {}, mock_backend, user=wrong_user)

            assert result == {"user": correct_user}
            mock_ehr_user.objects.get.assert_called_once_with(ehr_user_id="correct-ehr-123")

    def test_associate_by_session_ehr_user_id(self, mock_strategy, mock_backend):
        """Test association via EHR user ID in session."""
        mock_strategy.session["linking_ehr_user_id"] = "ehr-123"
        mock_strategy.session["linking_provider"] = "withings"

        mock_user = MagicMock()
        mock_user.username = "testuser"

        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.objects.get.return_value = mock_user

            result = associate_by_token_user(mock_strategy, {}, mock_backend)

            assert result == {"user": mock_user}
            mock_ehr_user.objects.get.assert_called_once_with(ehr_user_id="ehr-123")

    def test_associate_preserves_session_for_success_view(self, mock_strategy, mock_backend):
        """Test that session EHR user ID is preserved for ProviderLinkSuccessView to read."""
        mock_strategy.session["linking_ehr_user_id"] = "ehr-123"

        mock_user = MagicMock()
        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.objects.get.return_value = mock_user

            associate_by_token_user(mock_strategy, {}, mock_backend)

            # Session should NOT be cleared - ProviderLinkSuccessView needs it
            assert mock_strategy.session.get("linking_ehr_user_id") == "ehr-123"

    def test_associate_user_not_found_raises_error(self, mock_strategy, mock_backend):
        """Test that session with non-existent user raises error (prevents wrong user association)."""
        mock_strategy.session["linking_ehr_user_id"] = "nonexistent-user"

        with patch("base.models.EHRUser") as mock_ehr_user:
            mock_ehr_user.DoesNotExist = Exception
            mock_ehr_user.objects.get.side_effect = mock_ehr_user.DoesNotExist

            # Should raise AuthForbidden instead of falling back
            with pytest.raises(AuthForbidden) as exc_info:
                associate_by_token_user(mock_strategy, {}, mock_backend)

            # Verify error message contains security context (check exception repr, not str)
            exc_repr = repr(exc_info.value)
            assert "nonexistent-user" in exc_repr
            assert "does not exist" in exc_repr

    def test_associate_by_authenticated_user(self, mock_strategy, mock_backend):
        """Test association via currently authenticated user."""
        mock_strategy.request.user.is_authenticated = True
        mock_strategy.request.user.username = "authuser"

        result = associate_by_token_user(mock_strategy, {}, mock_backend)

        assert result == {"user": mock_strategy.request.user}

    def test_associate_fails_without_user(self, mock_strategy, mock_backend):
        """Test association fails when no user can be found and creation disabled."""
        mock_strategy.setting = lambda key, default: False if key == "SOCIAL_AUTH_CREATE_USERS" else default

        with pytest.raises(AuthForbidden):
            associate_by_token_user(mock_strategy, {}, mock_backend)


class TestHandleExistingSocialAssociation:
    """Tests for handle_existing_social_association pipeline function."""

    @pytest.fixture
    def mock_strategy(self):
        """Create mock strategy."""
        return MagicMock()

    @pytest.fixture
    def mock_backend(self):
        """Create mock backend."""
        backend = MagicMock()
        backend.name = "withings"
        return backend

    def test_handle_no_user_or_uid(self, mock_strategy, mock_backend):
        """Test returns None when user or uid is missing."""
        result = handle_existing_social_association(mock_strategy, {}, mock_backend, user=None, uid=None)
        assert result is None

        result = handle_existing_social_association(mock_strategy, {}, mock_backend, user=MagicMock(), uid=None)
        assert result is None

    def test_handle_no_existing_association(self, mock_strategy, mock_backend):
        """Test returns None when no existing association."""
        with patch("base.pipeline.UserSocialAuth") as mock_social_auth:
            mock_social_auth.objects.filter.return_value.count.return_value = 0

            result = handle_existing_social_association(
                mock_strategy, {}, mock_backend, user=MagicMock(), uid="uid-123"
            )

            assert result is None

    def test_handle_same_user_association(self, mock_strategy, mock_backend):
        """Test returns existing social when same user."""
        mock_user = MagicMock()
        mock_user.ehr_user_id = "ehr-123"

        mock_existing_social = MagicMock()
        mock_existing_social.user = mock_user

        with patch("base.pipeline.UserSocialAuth") as mock_social_auth:
            # filter(provider, uid) returns queryset with 1 result
            mock_qs = MagicMock()
            mock_qs.count.return_value = 1
            mock_qs.filter.return_value.first.return_value = mock_existing_social  # own_social
            mock_qs.exclude.return_value = []  # no other users
            mock_social_auth.objects.filter.return_value = mock_qs

            # For the duplicate check queryset
            mock_own_qs = MagicMock()
            mock_own_qs.count.return_value = 1
            # Second call to filter is for duplicate check
            mock_social_auth.objects.filter.side_effect = [mock_qs, mock_own_qs]

            result = handle_existing_social_association(mock_strategy, {}, mock_backend, user=mock_user, uid="uid-123")

            assert result == {"social": mock_existing_social, "is_new": False}

    def test_handle_deletes_old_user_association(self, mock_strategy, mock_backend):
        """Test deletes social auth from old user and lets pipeline create fresh one."""
        old_user = MagicMock()
        old_user.ehr_user_id = "old-ehr-123"

        new_user = MagicMock()
        new_user.ehr_user_id = "new-ehr-456"

        mock_existing_social = MagicMock()
        mock_existing_social.user = old_user

        with patch("base.pipeline.UserSocialAuth") as mock_social_auth:
            # filter(provider, uid) returns queryset with 1 result for old user
            mock_qs = MagicMock()
            mock_qs.count.return_value = 1
            mock_qs.filter.return_value.first.return_value = None  # no own_social
            mock_qs.exclude.return_value = [mock_existing_social]  # old user's social
            mock_social_auth.objects.filter.return_value = mock_qs

            with patch("base.models.ProviderLink") as mock_provider_link:
                mock_old_link = MagicMock()
                mock_provider_link.objects.filter.return_value.first.return_value = mock_old_link

                # For the duplicate check queryset (own_socials)
                mock_own_qs = MagicMock()
                mock_own_qs.count.return_value = 0
                mock_social_auth.objects.filter.side_effect = [mock_qs, mock_own_qs]

                result = handle_existing_social_association(
                    mock_strategy, {}, mock_backend, user=new_user, uid="uid-123"
                )

                # Should delete old social auth and old ProviderLink
                mock_existing_social.delete.assert_called_once()
                mock_old_link.delete.assert_called_once()
                # Returns None to let pipeline create fresh association
                assert result is None


class TestCreateProviderLink:
    """Tests for create_provider_link pipeline function."""

    @pytest.fixture
    def mock_strategy(self):
        """Create mock strategy."""
        return MagicMock()

    @pytest.fixture
    def mock_backend(self):
        """Create mock backend."""
        backend = MagicMock()
        backend.name = "withings"
        return backend

    def test_create_provider_link_missing_user(self, mock_strategy, mock_backend):
        """Test returns None when user is missing."""
        result = create_provider_link(mock_strategy, {}, mock_backend, user=None, uid="uid-123", response={})
        assert result is None

    def test_create_provider_link_missing_uid(self, mock_strategy, mock_backend):
        """Test returns None when uid is missing."""
        result = create_provider_link(mock_strategy, {}, mock_backend, user=MagicMock(), uid=None, response={})
        assert result is None

    def test_create_provider_link_success(self, mock_strategy, mock_backend):
        """Test successful provider link creation."""
        mock_user = MagicMock()
        mock_user.ehr_user_id = "ehr-123"

        with patch("base.models.Provider") as mock_provider:
            mock_provider_instance = MagicMock()
            mock_provider.objects.get_or_create.return_value = (mock_provider_instance, False)

            with patch("base.models.ProviderLink") as mock_provider_link:
                mock_link_instance = MagicMock()
                mock_provider_link.objects.update_or_create.return_value = (mock_link_instance, True)

                result = create_provider_link(
                    mock_strategy,
                    {},
                    mock_backend,
                    user=mock_user,
                    uid="external-uid-123",
                    response={"access_token": "token"},
                )

                assert result == {"provider_link": mock_link_instance}
                mock_provider_link.objects.update_or_create.assert_called_once()

    def test_create_provider_link_handles_error(self, mock_strategy, mock_backend):
        """Test error handling doesn't fail OAuth flow."""
        mock_user = MagicMock()

        with patch("base.models.Provider") as mock_provider:
            mock_provider.objects.get_or_create.side_effect = Exception("DB error")

            # Should not raise, just return None
            result = create_provider_link(mock_strategy, {}, mock_backend, user=mock_user, uid="uid-123", response={})

            assert result is None


class TestInitializeProviderServices:
    """Tests for initialize_provider_services pipeline function."""

    @pytest.fixture
    def mock_strategy(self):
        """Create mock strategy."""
        return MagicMock()

    @pytest.fixture
    def mock_backend(self):
        """Create mock backend."""
        backend = MagicMock()
        backend.name = "withings"
        return backend

    def test_initialize_no_user(self, mock_strategy, mock_backend):
        """Test returns early when no user provided."""
        result = initialize_provider_services(mock_strategy, {}, mock_backend, user=None, response={})
        assert result is None

    def test_initialize_queues_sync_tasks(self, mock_strategy, mock_backend):
        """Test that sync tasks are queued after OAuth."""
        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_user.ehr_user_id = "ehr-123"

        mock_social_user = MagicMock()
        mock_social_user.access_token = "test_token"
        mock_user.social_auth.filter.return_value.first.return_value = mock_social_user

        with patch("ingestors.constants.Provider") as mock_provider_enum:
            mock_provider_enum.return_value = "withings"

            with patch("ingestors.constants.PROVIDER_CONFIGS") as mock_configs:
                mock_config = MagicMock()
                mock_config.default_health_data_types = ["heart_rate", "steps"]
                mock_config.supports_webhooks = True
                mock_configs.get.return_value = mock_config

                with patch("base.models.Provider") as mock_provider_model:
                    mock_provider_db = MagicMock()
                    mock_provider_db.get_effective_data_types.return_value = ["heart_rate", "steps"]
                    mock_provider_db.is_webhook_enabled.return_value = True
                    mock_provider_model.objects.get.return_value = mock_provider_db

                    with patch("ingestors.tasks.sync_user_devices") as mock_sync_devices:
                        with patch("ingestors.health_data_tasks.sync_user_health_data_initial") as mock_sync_health:
                            with patch("ingestors.tasks.ensure_webhook_subscriptions") as mock_webhooks:
                                initialize_provider_services(
                                    mock_strategy, {}, mock_backend, user=mock_user, response={}
                                )

                                # Verify tasks were queued via .delay()
                                mock_sync_devices.delay.assert_called_once()
                                mock_sync_health.delay.assert_called_once()
                                mock_webhooks.delay.assert_called_once()

    def test_initialize_handles_unsupported_provider(self, mock_strategy, mock_backend):
        """Test handling of unsupported provider."""
        mock_user = MagicMock()
        mock_user.username = "testuser"

        with patch("ingestors.constants.Provider") as mock_provider_enum:
            mock_provider_enum.side_effect = ValueError("Unsupported provider")

            # Should not raise, just log warning and return
            result = initialize_provider_services(mock_strategy, {}, mock_backend, user=mock_user, response={})

            assert result is None

    def test_initialize_handles_import_error(self, mock_strategy, mock_backend):
        """Test graceful handling when tasks are not available."""
        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_user.ehr_user_id = "ehr-123"

        mock_social_user = MagicMock()
        mock_social_user.access_token = "test_token"
        mock_user.social_auth.filter.return_value.first.return_value = mock_social_user

        with patch("ingestors.constants.Provider") as mock_provider_enum:
            mock_provider_enum.return_value = "withings"

            with patch("ingestors.constants.PROVIDER_CONFIGS") as mock_configs:
                mock_config = MagicMock()
                mock_config.default_health_data_types = ["heart_rate"]
                mock_configs.get.return_value = mock_config

                with patch("base.models.Provider") as mock_provider_model:
                    mock_provider_db = MagicMock()
                    mock_provider_db.get_effective_data_types.return_value = ["heart_rate"]
                    mock_provider_db.is_webhook_enabled.return_value = False
                    mock_provider_model.objects.get.return_value = mock_provider_db

                    # Mock import to fail
                    with patch.dict("sys.modules", {"ingestors.health_data_tasks": None}):
                        with patch("ingestors.tasks.sync_user_devices", side_effect=ImportError):
                            # Should not raise
                            initialize_provider_services(mock_strategy, {}, mock_backend, user=mock_user, response={})

    def test_initialize_skips_webhooks_when_disabled(self, mock_strategy, mock_backend):
        """Test webhooks are skipped when disabled for provider."""
        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_user.ehr_user_id = "ehr-123"

        mock_social_user = MagicMock()
        mock_social_user.access_token = "test_token"
        mock_user.social_auth.filter.return_value.first.return_value = mock_social_user

        with patch("ingestors.constants.Provider") as mock_provider_enum:
            mock_provider_enum.return_value = "withings"

            with patch("ingestors.constants.PROVIDER_CONFIGS") as mock_configs:
                mock_config = MagicMock()
                mock_config.default_health_data_types = ["heart_rate"]
                mock_configs.get.return_value = mock_config

                with patch("base.models.Provider") as mock_provider_model:
                    mock_provider_db = MagicMock()
                    mock_provider_db.get_effective_data_types.return_value = ["heart_rate"]
                    mock_provider_db.is_webhook_enabled.return_value = False  # Webhooks disabled
                    mock_provider_model.objects.get.return_value = mock_provider_db

                    with patch("ingestors.tasks.sync_user_devices"):
                        with patch("ingestors.health_data_tasks.sync_user_health_data_initial"):
                            with patch("ingestors.tasks.ensure_webhook_subscriptions") as mock_webhooks:
                                initialize_provider_services(
                                    mock_strategy, {}, mock_backend, user=mock_user, response={}
                                )

                                # Webhooks should not be called
                                mock_webhooks.assert_not_called()
