"""Tests for Firebase credential fail-fast and CORS wildcard rejection (Tasks F & G)."""

from __future__ import annotations

import json
import os

import pytest


class TestFirebaseCredentialFailFast:
    def test_staging_firebase_no_credential_fails(self, monkeypatch):
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        from app.config import Settings

        with pytest.raises(ValueError, match="FIREBASE_SERVICE_ACCOUNT_JSON"):
            Settings(
                auth_mode="firebase",
                environment="staging",
                firebase_project_id="test-project",
            )

    def test_staging_firebase_malformed_json_fails(self, monkeypatch):
        monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", "not-valid-json{{{")
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        from app.config import Settings

        with pytest.raises(ValueError, match="not valid JSON"):
            Settings(
                auth_mode="firebase",
                environment="staging",
                firebase_project_id="test-project",
            )

    def test_staging_firebase_non_object_json_fails(self, monkeypatch):
        monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", '["array"]')
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        from app.config import Settings

        with pytest.raises(ValueError, match="JSON object"):
            Settings(
                auth_mode="firebase",
                environment="staging",
                firebase_project_id="test-project",
            )

    def test_staging_firebase_missing_fields_fails(self, monkeypatch):
        monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", '{"type": "service_account"}')
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        from app.config import Settings

        with pytest.raises(ValueError, match="missing required fields"):
            Settings(
                auth_mode="firebase",
                environment="staging",
                firebase_project_id="test-project",
            )

    def test_staging_firebase_valid_synthetic_json_passes(self, monkeypatch):
        sa = {
            "type": "service_account",
            "project_id": "test-project",
            "private_key": "SYNTHETIC_KEY_MARKER",
            "client_email": "test@test-project.iam.gserviceaccount.com",
        }
        monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", json.dumps(sa))
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        from app.config import Settings

        s = Settings(
            auth_mode="firebase",
            environment="staging",
            firebase_project_id="test-project",
            allowed_origins="https://test.example.com",
        )
        assert s.auth_mode == "firebase"

    def test_testing_firebase_no_credential_passes(self, monkeypatch):
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        from app.config import Settings

        s = Settings(
            auth_mode="firebase",
            environment="testing",
            firebase_project_id="test-project",
        )
        assert s.environment == "testing"

    def test_legacy_no_credential_passes(self, monkeypatch):
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        from app.config import Settings

        s = Settings(environment="testing", auth_mode="legacy")
        assert s.auth_mode == "legacy"

    def test_error_text_no_private_key_marker(self, monkeypatch):
        sa = {
            "type": "service_account",
            "project_id": "test-project",
            "private_key": "SYNTHETIC_KEY_MARKER",
        }
        monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", json.dumps(sa))
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        from app.config import Settings

        with pytest.raises(ValueError) as exc:
            Settings(
                auth_mode="firebase",
                environment="staging",
                firebase_project_id="test-project",
            )
        assert "SYNTHETIC_KEY_MARKER" not in str(exc.value)

    def test_gac_nonexistent_file_fails(self, monkeypatch):
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/path/cred.json")
        from app.config import Settings

        with pytest.raises(ValueError, match="readable file"):
            Settings(
                auth_mode="firebase",
                environment="staging",
                firebase_project_id="test-project",
            )

    def test_gac_existing_file_passes(self, monkeypatch, tmp_path):
        cred_file = tmp_path / "cred.json"
        cred_file.write_text("{}")
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(cred_file))
        from app.config import Settings

        s = Settings(
            auth_mode="firebase",
            environment="staging",
            firebase_project_id="test-project",
            allowed_origins="https://test.example.com",
        )
        assert s.auth_mode == "firebase"


class TestCorsWildcardRejection:
    def test_exact_https_origin_passes(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            allowed_origins="https://ai-revenue-living-travel.pages.dev",
        )
        assert s.allowed_origin_list == ["https://ai-revenue-living-travel.pages.dev"]

    def test_localhost_http_passes(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            allowed_origins="http://localhost:8788",
        )
        assert s.allowed_origin_list == ["http://localhost:8788"]

    def test_wildcard_star_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="wildcard"):
            Settings(environment="testing", allowed_origins="*")

    def test_wildcard_subdomain_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="wildcard"):
            Settings(environment="testing", allowed_origins="https://*.pages.dev")

    def test_trailing_wildcard_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="wildcard"):
            Settings(environment="testing", allowed_origins="https://example.com*")

    def test_path_in_origin_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="path"):
            Settings(environment="testing", allowed_origins="https://pages.dev/path")

    def test_javascript_scheme_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="scheme"):
            Settings(environment="testing", allowed_origins="javascript:alert(1)")

    def test_comma_separated_exact_origins_pass(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            allowed_origins="https://a.example.com,https://b.example.com",
        )
        assert s.allowed_origin_list == ["https://a.example.com", "https://b.example.com"]

    def test_empty_origins_testing_passes(self):
        from app.config import Settings

        s = Settings(environment="testing", allowed_origins="")
        assert s.allowed_origin_list == []

    def test_query_in_origin_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="query"):
            Settings(environment="testing", allowed_origins="https://example.com?foo=bar")

    def test_fragment_in_origin_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="fragment"):
            Settings(environment="testing", allowed_origins="https://example.com#frag")

    def test_userinfo_in_origin_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="userinfo"):
            Settings(environment="testing", allowed_origins="https://user@example.com")

    def test_userinfo_with_password_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="userinfo"):
            Settings(environment="testing", allowed_origins="https://user:pass@example.com")

    def test_empty_scheme_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="hostname"):
            Settings(environment="testing", allowed_origins="http://")

    def test_https_no_host_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="hostname"):
            Settings(environment="testing", allowed_origins="https://")

    def test_triple_slash_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="hostname"):
            Settings(environment="testing", allowed_origins="https:///example.com")

    def test_trailing_slash_path_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="path"):
            Settings(environment="testing", allowed_origins="https://example.com/")

    def test_staging_empty_origins_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="must not be empty"):
            Settings(
                environment="staging",
                auth_mode="legacy",
                operator_secret="test-secret-12345",
                allowed_origins="",
            )

    def test_production_empty_origins_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="must not be empty"):
            Settings(
                environment="production",
                auth_mode="legacy",
                operator_secret="test-secret-12345",
                allowed_origins="",
            )

    def test_development_empty_origins_passes(self):
        from app.config import Settings

        s = Settings(
            environment="development",
            auth_mode="legacy",
            operator_secret="test-secret-12345",
            allowed_origins="",
        )
        assert s.allowed_origin_list == []

    def test_branch_subdomain_origin_passes(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            allowed_origins="https://branch-name.ai-revenue-living-travel.pages.dev",
        )
        assert s.allowed_origin_list == [
            "https://branch-name.ai-revenue-living-travel.pages.dev"
        ]

    def test_trailing_comma_empty_segment_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="empty entries"):
            Settings(environment="testing", allowed_origins="https://a.example.com,")

    def test_leading_comma_empty_segment_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="empty entries"):
            Settings(environment="testing", allowed_origins=",https://a.example.com")

    def test_double_comma_empty_segment_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="empty entries"):
            Settings(
                environment="testing",
                allowed_origins="https://a.example.com,,https://b.example.com",
            )

    def test_whitespace_only_segment_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="empty entries"):
            Settings(
                environment="testing",
                allowed_origins="https://a.example.com,   ,https://b.example.com",
            )

    def test_invalid_port_string_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="invalid port"):
            Settings(environment="testing", allowed_origins="https://example.com:invalid")

    def test_port_out_of_range_high_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="invalid port"):
            Settings(environment="testing", allowed_origins="https://example.com:99999")

    def test_port_negative_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="invalid port"):
            Settings(environment="testing", allowed_origins="https://example.com:-1")

    def test_port_zero_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="invalid port"):
            Settings(environment="testing", allowed_origins="https://example.com:0")

    def test_port_443_passes(self):
        from app.config import Settings

        s = Settings(environment="testing", allowed_origins="https://example.com:443")
        assert s.allowed_origin_list == ["https://example.com:443"]

    def test_port_8788_passes(self):
        from app.config import Settings

        s = Settings(environment="testing", allowed_origins="http://localhost:8788")
        assert s.allowed_origin_list == ["http://localhost:8788"]


class TestGacReadableFile:
    def test_gac_directory_fails(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path))
        from app.config import Settings

        with pytest.raises(ValueError, match="readable file"):
            Settings(
                auth_mode="firebase",
                environment="staging",
                firebase_project_id="test-project",
            )

    def test_gac_unreadable_file_deterministic(self, monkeypatch, tmp_path):
        import builtins

        cred_file = tmp_path / "cred.json"
        cred_file.write_text("{}")
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(cred_file))

        real_open = builtins.open

        def guarded_open(file, *args, **kwargs):
            if os.fspath(file) == str(cred_file):
                raise PermissionError("synthetic denial")
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", guarded_open)
        from app.config import Settings

        with pytest.raises(ValueError, match="readable file") as exc:
            Settings(
                auth_mode="firebase",
                environment="staging",
                firebase_project_id="test-project",
                allowed_origins="https://test.example.com",
            )
        assert str(cred_file) not in str(exc.value)

    def test_gac_error_no_path_leak(self, monkeypatch):
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/secret/path.json")
        from app.config import Settings

        with pytest.raises(ValueError) as exc:
            Settings(
                environment="staging",
                auth_mode="firebase",
                firebase_project_id="test-project",
            )
        assert "/nonexistent/secret/path.json" not in str(exc.value)


class TestAIProviderSettings:
    def test_default_provider_is_mock(self):
        from app.config import Settings

        s = Settings(environment="testing")
        assert s.ai_provider == "mock"

    def test_default_mock_does_not_require_ai_url_key_or_model(self):
        from app.config import Settings

        s = Settings(environment="testing")
        assert s.ai_base_url == ""
        assert s.ai_api_key == ""
        assert s.ai_model == ""

    def test_mock_is_always_valid(self):
        from app.config import Settings

        s = Settings(environment="testing", ai_provider="mock")
        assert s.ai_provider == "mock"

    def test_unsupported_provider_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="LT_AI_PROVIDER"):
            Settings(environment="testing", ai_provider="azure")

    def test_typo_provider_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="LT_AI_PROVIDER"):
            Settings(environment="testing", ai_provider="open_ai")

    def test_missing_base_url_fails_for_openai_compatible(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="LT_AI_BASE_URL"):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_api_key="sk-test-key",
                ai_model="gpt-4o-mini",
            )

    def test_missing_api_key_fails_for_openai_compatible(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="LT_AI_API_KEY"):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_base_url="https://api.openai.com",
                ai_model="gpt-4o-mini",
            )

    def test_missing_model_fails_for_openai_compatible(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="LT_AI_MODEL"):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_base_url="https://api.openai.com",
                ai_api_key="sk-test-key",
            )

    def test_valid_openai_compatible_passes(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
        )
        assert s.ai_provider == "openai_compatible"

    def test_invalid_timeout_negative_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="LT_AI_TIMEOUT_SECONDS"):
            Settings(environment="testing", ai_timeout_seconds=-1)

    def test_invalid_timeout_zero_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="LT_AI_TIMEOUT_SECONDS"):
            Settings(environment="testing", ai_timeout_seconds=0)

    def test_invalid_timeout_too_large_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="LT_AI_TIMEOUT_SECONDS"):
            Settings(environment="testing", ai_timeout_seconds=121)

    def test_valid_timeout_min_edge(self):
        from app.config import Settings

        s = Settings(environment="testing", ai_timeout_seconds=1)
        assert s.ai_timeout_seconds == 1

    def test_valid_timeout_max_edge(self):
        from app.config import Settings

        s = Settings(environment="testing", ai_timeout_seconds=120)
        assert s.ai_timeout_seconds == 120

    def test_invalid_cost_class_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="LT_AI_COST_CLASS"):
            Settings(environment="testing", ai_cost_class="premium")

    def test_valid_cost_classes(self):
        from app.config import Settings

        for cls in ("free", "paid", "local", "unknown"):
            s = Settings(environment="testing", ai_cost_class=cls)
            assert s.ai_cost_class == cls

    def test_staging_http_url_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="https"):
            Settings(
                environment="staging",
                ai_provider="openai_compatible",
                ai_base_url="http://api.openai.com",
                ai_api_key="sk-test-key",
                ai_model="gpt-4o-mini",
            )

    def test_staging_localhost_https_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="localhost|private|loopback"):
            Settings(
                environment="staging",
                allowed_origins="https://example.com",
                ai_provider="openai_compatible",
                ai_base_url="https://localhost:11434",
                ai_api_key="test-key",
                ai_model="test-model",
            )

    def test_staging_private_ip_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="localhost|private|loopback|global"):
            Settings(
                environment="staging",
                allowed_origins="https://example.com",
                ai_provider="openai_compatible",
                ai_base_url="https://10.0.0.1:11434",
                ai_api_key="test-key",
                ai_model="test-model",
            )

    def test_staging_link_local_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="localhost|private|loopback|global"):
            Settings(
                environment="staging",
                allowed_origins="https://example.com",
                ai_provider="openai_compatible",
                ai_base_url="https://169.254.1.1",
                ai_api_key="test-key",
                ai_model="test-model",
            )

    def test_development_localhost_http_allowed(self):
        from app.config import Settings

        s = Settings(
            environment="development",
            ai_provider="openai_compatible",
            ai_base_url="http://localhost:11434",
            ai_api_key="test-key",
            ai_model="test-model",
        )
        assert s.ai_base_url == "http://localhost:11434"

    def test_testing_http_localhost_allowed(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="http://localhost:11434",
            ai_api_key="test-key",
            ai_model="test-model",
        )
        assert s.ai_base_url == "http://localhost:11434"

    def test_testing_http_non_localhost_blocked(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="HTTP LT_AI_BASE_URL in testing/development is only allowed for localhost or loopback addresses."):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_base_url="http://example.com",
                ai_api_key="test-key",
                ai_model="test-model",
            )

    def test_development_non_loopback_http_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="HTTP LT_AI_BASE_URL in testing/development is only allowed for localhost or loopback addresses."):
            Settings(
                environment="development",
                ai_provider="openai_compatible",
                ai_base_url="http://example.com",
                ai_api_key="test-key",
                ai_model="test-model",
            )

    def test_url_userinfo_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="userinfo"):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_base_url="https://user:pass@api.openai.com",
                ai_api_key="sk-test-key",
                ai_model="gpt-4o-mini",
            )

    def test_url_query_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="query"):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_base_url="https://api.openai.com?foo=bar",
                ai_api_key="sk-test-key",
                ai_model="gpt-4o-mini",
            )

    def test_url_fragment_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="fragment"):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_base_url="https://api.openai.com#section",
                ai_api_key="sk-test-key",
                ai_model="gpt-4o-mini",
            )

    def test_url_malformed_port_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="invalid port|port"):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_base_url="https://api.openai.com:invalid",
                ai_api_key="sk-test-key",
                ai_model="gpt-4o-mini",
            )

    def test_url_out_of_range_port_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="port"):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_base_url="https://api.openai.com:99999",
                ai_api_key="sk-test-key",
                ai_model="gpt-4o-mini",
            )

    def test_validation_message_no_api_key(self):
        from app.config import Settings

        with pytest.raises(ValueError) as exc:
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_base_url="https://api.openai.com",
                ai_api_key="super-secret-api-key-12345",
            )
        msg = str(exc.value)
        assert "super-secret-api-key-12345" not in msg
        assert "LT_AI_MODEL" in msg

    def test_chat_completions_url_with_v1_prefix(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com/v1",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
        )
        url = s.ai_chat_completions_url
        assert url == "https://api.openai.com/v1/chat/completions"
        assert "//v1" not in url.replace("https://", "").split("/", 1)[1]

    def test_chat_completions_url_without_v1_prefix(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
        )
        url = s.ai_chat_completions_url
        assert url == "https://api.openai.com/v1/chat/completions"

    def test_chat_completions_url_double_slash_prevention(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com/v1/",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
        )
        url = s.ai_chat_completions_url
        assert "//chat" not in url.replace("https://", "").split("/", 1)[1]

    def test_development_127_0_0_1_http_allowed(self):
        from app.config import Settings

        s = Settings(
            environment="development",
            ai_provider="openai_compatible",
            ai_base_url="http://127.0.0.1:11434",
            ai_api_key="test-key",
            ai_model="test-model",
        )
        assert s.ai_base_url == "http://127.0.0.1:11434"

    def test_development_localhost_https_allowed(self):
        from app.config import Settings

        s = Settings(
            environment="development",
            ai_provider="openai_compatible",
            ai_base_url="https://localhost:11434",
            ai_api_key="test-key",
            ai_model="test-model",
        )
        assert s.ai_base_url == "https://localhost:11434"

    def test_production_http_url_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="https"):
            Settings(
                environment="production",
                ai_provider="openai_compatible",
                ai_base_url="http://api.openai.com",
                ai_api_key="sk-test-key",
                ai_model="gpt-4o-mini",
            )

    def test_testing_http_non_localhost_blocked(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="HTTP LT_AI_BASE_URL in testing/development is only allowed for localhost or loopback addresses."):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_base_url="http://api.openai.com",
                ai_api_key="sk-test-key",
                ai_model="gpt-4o-mini",
            )
