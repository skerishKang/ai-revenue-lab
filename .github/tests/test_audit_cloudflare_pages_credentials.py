"""Tests for audit_cloudflare_pages_credentials.py."""

import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import BytesIO, StringIO
from unittest import mock
from urllib.error import HTTPError, URLError

# import the module directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))
import audit_cloudflare_pages_credentials as audit_mod


class _FakeResponse:
    def __init__(self, status: int, payload: object | None = None, raw_body: bytes | None = None) -> None:
        self.status = status
        if raw_body is not None:
            self._body = raw_body
        else:
            self._body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self._read = False

    def read(self) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def make_http_error(url: str, code: int, body: bytes) -> HTTPError:
    return HTTPError(url=url, code=code, msg="synthetic error", hdrs={}, fp=BytesIO(body))


class TestCliBoundarySubprocess(unittest.TestCase):
    """Only CLI and missing-environment behavior."""

    def test_py_compile_success(self):
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "audit_cloudflare_pages_credentials.py")
        result = subprocess.run([sys.executable, "-m", "py_compile", script], capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_cloudflare_api_token_missing(self):
        env = os.environ.copy()
        env.pop("CLOUDFLARE_API_TOKEN", None)
        env["CLOUDFLARE_ACCOUNT_ID"] = "dummy"
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "audit_cloudflare_pages_credentials.py")
        result = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("CLOUDFLARE_API_TOKEN missing", result.stderr)

    def test_cloudflare_account_id_missing(self):
        env = os.environ.copy()
        env["CLOUDFLARE_API_TOKEN"] = "dummy"
        env.pop("CLOUDFLARE_ACCOUNT_ID", None)
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "audit_cloudflare_pages_credentials.py")
        result = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("CLOUDFLARE_ACCOUNT_ID missing", result.stderr)

    def test_both_missing(self):
        env = os.environ.copy()
        env.pop("CLOUDFLARE_API_TOKEN", None)
        env.pop("CLOUDFLARE_ACCOUNT_ID", None)
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "audit_cloudflare_pages_credentials.py")
        result = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("CLOUDFLARE_API_TOKEN missing", result.stderr)
        self.assertIn("CLOUDFLARE_ACCOUNT_ID missing", result.stderr)


class TestHttpHelpersInProcess(unittest.TestCase):
    """HTTP 200/error/non-JSON/network behavior."""

    def test_request_json_200(self):
        with mock.patch.object(audit_mod.urllib.request, "urlopen") as mock_urlopen:
            mock_urlopen.return_value = _FakeResponse(200, {"success": True})
            status, data = audit_mod.request_json("/test", "token")
            self.assertEqual(status, 200)
            self.assertTrue(data["success"])

    def test_request_json_401(self):
        with mock.patch.object(audit_mod.urllib.request, "urlopen") as mock_urlopen:
            mock_urlopen.side_effect = make_http_error("http://url", 401, b'{"error": "unauthorized"}')
            status, data = audit_mod.request_json("/test", "token")
            self.assertEqual(status, 401)
            self.assertEqual(data.get("error"), "unauthorized")

    def test_request_json_403(self):
        with mock.patch.object(audit_mod.urllib.request, "urlopen") as mock_urlopen:
            mock_urlopen.side_effect = make_http_error("http://url", 403, b'{"error": "forbidden"}')
            status, data = audit_mod.request_json("/test", "token")
            self.assertEqual(status, 403)
            self.assertEqual(data.get("error"), "forbidden")

    def test_request_json_non_json_error(self):
        with mock.patch.object(audit_mod.urllib.request, "urlopen") as mock_urlopen:
            mock_urlopen.side_effect = make_http_error("http://url", 500, b'Internal Server Error')
            status, data = audit_mod.request_json("/test", "token")
            self.assertEqual(status, 500)
            self.assertEqual(data, {})

    def test_request_json_malformed_json_response(self):
        with mock.patch.object(audit_mod.urllib.request, "urlopen") as mock_urlopen:
            mock_urlopen.side_effect = make_http_error("http://url", 400, b'{malformed')
            status, data = audit_mod.request_json("/test", "token")
            self.assertEqual(status, 400)
            self.assertEqual(data, {})

    def test_request_json_urlerror(self):
        with mock.patch.object(audit_mod.urllib.request, "urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("not reachable")
            status, data = audit_mod.request_json("/test", "token")
            self.assertEqual(status, 0)
            self.assertEqual(data, {})

    def test_request_json_timeout(self):
        import socket
        with mock.patch.object(audit_mod.urllib.request, "urlopen") as mock_urlopen:
            mock_urlopen.side_effect = socket.timeout()
            status, data = audit_mod.request_json("/test", "token")
            self.assertEqual(status, 0)
            self.assertEqual(data, {})


class TestProjectContractInProcess(unittest.TestCase):
    """Cloudflare project contract validation."""

    def test_valid_project(self):
        proj = {
            "name": audit_mod.B37_PROJECT,
            "production_branch": "main",
            "source": {
                "type": "github",
                "config": {
                    "owner": "skerishKang",
                    "repo_name": "ai-revenue-lab",
                    "production_branch": "main",
                    "production_deployments_enabled": True,
                    "preview_deployment_setting": "none",
                    "pr_comments_enabled": False
                }
            },
            "build_config": {
                "root_dir": "reference/business-37-ai-safe-route-v1",
                "destination_dir": ".",
                "build_command": ""
            }
        }
        self.assertEqual(audit_mod.validate_project_contract(proj), [])

    def test_missing_project(self):
        self.assertIn("contract: wrong project.name", audit_mod.validate_project_contract({}))

    def test_source_type_null(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "main", "source": {"type": "direct_upload"}}
        self.assertIn("contract: source.type null/direct-upload rejected", audit_mod.validate_project_contract(proj))

    def test_wrong_owner(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "main", "source": {"type": "github", "config": {"owner": "wrong"}}}
        self.assertIn("contract: wrong source owner rejected", audit_mod.validate_project_contract(proj))

    def test_wrong_repo(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "main", "source": {"type": "github", "config": {"owner": "skerishKang", "repo_name": "wrong"}}}
        self.assertIn("contract: wrong repo_name rejected", audit_mod.validate_project_contract(proj))

    def test_wrong_source_production_branch(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "main", "source": {"type": "github", "config": {"owner": "skerishKang", "repo_name": "ai-revenue-lab", "production_branch": "dev"}}}
        self.assertIn("contract: wrong source production branch rejected", audit_mod.validate_project_contract(proj))

    def test_wrong_top_level_branch(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "dev"}
        self.assertIn("contract: wrong top-level production branch", audit_mod.validate_project_contract(proj))

    def test_deployments_disabled(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "main", "source": {"type": "github", "config": {"owner": "skerishKang", "repo_name": "ai-revenue-lab", "production_branch": "main", "production_deployments_enabled": False}}}
        self.assertIn("contract: production_deployments_enabled false rejected", audit_mod.validate_project_contract(proj))

    def test_preview_enabled(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "main", "source": {"type": "github", "config": {"owner": "skerishKang", "repo_name": "ai-revenue-lab", "production_branch": "main", "production_deployments_enabled": True, "preview_deployment_setting": "all"}}}
        self.assertIn("contract: Preview enabled rejected", audit_mod.validate_project_contract(proj))

    def test_pr_comments_enabled(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "main", "source": {"type": "github", "config": {"owner": "skerishKang", "repo_name": "ai-revenue-lab", "production_branch": "main", "production_deployments_enabled": True, "preview_deployment_setting": "none", "pr_comments_enabled": True}}}
        self.assertIn("contract: PR comments enabled rejected", audit_mod.validate_project_contract(proj))

    def test_wrong_root_dir(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "main", "source": {"type": "github", "config": {"owner": "skerishKang", "repo_name": "ai-revenue-lab", "production_branch": "main", "production_deployments_enabled": True, "preview_deployment_setting": "none", "pr_comments_enabled": False}}, "build_config": {"root_dir": "wrong"}}
        self.assertIn("contract: wrong root directory rejected", audit_mod.validate_project_contract(proj))

    def test_wrong_destination_dir(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "main", "source": {"type": "github", "config": {"owner": "skerishKang", "repo_name": "ai-revenue-lab", "production_branch": "main", "production_deployments_enabled": True, "preview_deployment_setting": "none", "pr_comments_enabled": False}}, "build_config": {"root_dir": "reference/business-37-ai-safe-route-v1", "destination_dir": "wrong"}}
        self.assertIn("contract: wrong destination directory rejected", audit_mod.validate_project_contract(proj))

    def test_non_empty_build_command(self):
        proj = {"name": audit_mod.B37_PROJECT, "production_branch": "main", "source": {"type": "github", "config": {"owner": "skerishKang", "repo_name": "ai-revenue-lab", "production_branch": "main", "production_deployments_enabled": True, "preview_deployment_setting": "none", "pr_comments_enabled": False}}, "build_config": {"root_dir": "reference/business-37-ai-safe-route-v1", "destination_dir": ".", "build_command": "npm run build"}}
        self.assertIn("contract: non-empty build command rejected", audit_mod.validate_project_contract(proj))


class TestAuditMainInProcess(unittest.TestCase):
    """Complete mocked audit flow."""
    def test_all_pass(self):
        def fake_urlopen(req, timeout=None):
            if "/user/tokens/verify" in req.full_url:
                return _FakeResponse(200, {"success": True})
            if req.full_url.endswith("/pages/projects") or "/pages/projects?" in req.full_url:
                return _FakeResponse(200, {"success": True})
            if "/pages/projects/" in req.full_url:
                proj = {
                    "name": audit_mod.B37_PROJECT, "production_branch": "main",
                    "source": {"type": "github", "config": {"owner": "skerishKang", "repo_name": "ai-revenue-lab", "production_branch": "main", "production_deployments_enabled": True, "preview_deployment_setting": "none", "pr_comments_enabled": False}},
                    "build_config": {"root_dir": "reference/business-37-ai-safe-route-v1", "destination_dir": ".", "build_command": ""}
                }
                return _FakeResponse(200, {"success": True, "result": proj})
            if req.full_url == audit_mod.B37_URL:
                return _FakeResponse(200, {})
            raise make_http_error(req.full_url, 404, b'{}')

        with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "token", "CLOUDFLARE_ACCOUNT_ID": audit_mod.EXPECTED_ACCOUNT_ID}, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout = StringIO()
                stderr = StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(audit_mod.main(), 0)

    def test_pages_api_http_403(self):
        def fake_urlopen(req, timeout=None):
            if "/user/tokens/verify" in req.full_url:
                return _FakeResponse(200, {"success": True})
            if req.full_url.endswith("/pages/projects") or "/pages/projects?" in req.full_url:
                raise make_http_error(req.full_url, 403, b'{}')
            raise make_http_error(req.full_url, 404, b'{}')

        with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "token", "CLOUDFLARE_ACCOUNT_ID": audit_mod.EXPECTED_ACCOUNT_ID}, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout = StringIO()
                stderr = StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(audit_mod.main(), 1)


class TestNoCredentialLeak(unittest.TestCase):
    """stdout/stderr credential leak assertions."""

    def test_no_credential_leak(self):
        synthetic_token = "synthetic-very-secret-token"
        synthetic_account = "synthetic-account-id-1234567890"

        def fake_urlopen(req, timeout=None):
            raise make_http_error(req.full_url, 401, b'{"error": "unauthorized"}')

        stdout = StringIO()
        stderr = StringIO()

        with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": synthetic_token, "CLOUDFLARE_ACCOUNT_ID": synthetic_account}, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    audit_mod.main()

        output = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(synthetic_token, output)
        self.assertNotIn(synthetic_account, output)
        self.assertNotIn("Authorization", output)
        self.assertNotIn("Bearer", output)
        self.assertNotIn("unauthorized", output) # response body should not be leaked


class TestReadOnlyRequests(unittest.TestCase):
    """Every request uses GET only."""

    def test_all_requests_get(self):
        requests_made = []
        def fake_urlopen(req, timeout=None):
            requests_made.append(req)
            return _FakeResponse(200, {"success": True})

        with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "token", "CLOUDFLARE_ACCOUNT_ID": audit_mod.EXPECTED_ACCOUNT_ID}, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout = StringIO()
                stderr = StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    audit_mod.main()

        self.assertTrue(len(requests_made) > 0)
        for req in requests_made:
            self.assertEqual(req.method, "GET")

if __name__ == "__main__":
    unittest.main()
