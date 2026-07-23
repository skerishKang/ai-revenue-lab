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
