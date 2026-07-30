"""Tests for audit_cloudflare_pages_credentials.py."""

import os
import sys
import socket
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError
from io import BytesIO, StringIO
from contextlib import redirect_stdout, redirect_stderr

# Add scripts to path
script_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(script_dir))
import audit_cloudflare_pages_credentials as audit_mod


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b""):
        self.status = status
        self._body = body
        self._read = False

    def read(self) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def make_http_error(code: int, body: bytes) -> HTTPError:
    return HTTPError("http://fake", code, "msg", {}, BytesIO(body))


class TestAuditCloudflarePagesCredentials(unittest.TestCase):
    def setUp(self):
        self.valid_project = {
            "name": audit_mod.B37_PROJECT,
            "production_branch": audit_mod.EXPECTED_BRANCH,
            "source": {
                "type": "github",
                "config": {
                    "owner": audit_mod.EXPECTED_REPOSITORY.split("/")[0],
                    "repo_name": audit_mod.EXPECTED_REPOSITORY.split("/")[1],
                    "production_branch": audit_mod.EXPECTED_BRANCH,
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
        self.valid_env = {
            "CLOUDFLARE_API_TOKEN": "token",
            "CLOUDFLARE_ACCOUNT_ID": audit_mod.EXPECTED_ACCOUNT_ID
        }

    def _mock_success(self):
        import json
        def fake_urlopen(req, timeout=None):
            if "verify" in req.full_url:
                return _FakeResponse(200, b'{"success": true}')
            if f"/projects/{audit_mod.B37_PROJECT}" in req.full_url:
                return _FakeResponse(200, json.dumps({"success": True, "result": self.valid_project}).encode("utf-8"))
            if "/pages/projects" in req.full_url:
                return _FakeResponse(200, b'{"success": true}')
            # For production status
            return _FakeResponse(200, b'')
        return fake_urlopen

    def test_missing_token(self):
        env = self.valid_env.copy()
        env.pop("CLOUDFLARE_API_TOKEN")
        with mock.patch.dict(os.environ, env, clear=True):
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = audit_mod.main()
                self.assertEqual(code, 1)
                self.assertIn("CLOUDFLARE_API_TOKEN missing", stderr.getvalue())

    def test_missing_account_id(self):
        env = self.valid_env.copy()
        env.pop("CLOUDFLARE_ACCOUNT_ID")
        with mock.patch.dict(os.environ, env, clear=True):
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = audit_mod.main()
                self.assertEqual(code, 1)
                self.assertIn("CLOUDFLARE_ACCOUNT_ID missing", stderr.getvalue())

    def test_account_id_mismatch(self):
        env = self.valid_env.copy()
        env["CLOUDFLARE_ACCOUNT_ID"] = "dummy"
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("CLOUDFLARE_ACCOUNT_ID mismatch", stderr.getvalue())

    def test_end_to_end_success(self):
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 0)
                    self.assertIn("All Cloudflare Pages credential health checks passed.", stdout.getvalue())

    def test_token_verify_fails_401(self):
        def fake_urlopen(req, timeout=None):
            if "verify" in req.full_url:
                raise make_http_error(401, b'{"success": false}')
            return self._mock_success()(req, timeout)

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("token verification FAIL", stderr.getvalue())

    def test_pages_api_fails_403(self):
        def fake_urlopen(req, timeout=None):
            if "/pages/projects" in req.full_url and "verify" not in req.full_url:
                if audit_mod.B37_PROJECT not in req.full_url:
                    raise make_http_error(403, b'{"success": false}')
            return self._mock_success()(req, timeout)

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("Pages API FAIL", stderr.getvalue())

    def test_project_missing(self):
        def fake_urlopen(req, timeout=None):
            if f"/projects/{audit_mod.B37_PROJECT}" in req.full_url:
                raise make_http_error(404, b'{"success": false}')
            return self._mock_success()(req, timeout)

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("project missing", stderr.getvalue())

    def test_project_contract_direct_upload(self):
        self.valid_project["source"] = {"type": "direct_upload"}
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: source.type null/direct-upload rejected", stderr.getvalue())

    def test_project_contract_wrong_repository(self):
        self.valid_project["source"]["config"]["owner"] = "wrongOwner"
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: wrong source owner rejected", stderr.getvalue())

    def test_project_contract_wrong_production_branch(self):
        self.valid_project["production_branch"] = "dev"
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: wrong top-level production branch", stderr.getvalue())

    def test_project_contract_wrong_repo_name(self):
        self.valid_project["source"]["config"]["repo_name"] = "wrong-repo"
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: wrong repo_name rejected", stderr.getvalue())

    def test_project_contract_source_wrong_branch(self):
        self.valid_project["source"]["config"]["production_branch"] = "dev"
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: wrong source production branch rejected", stderr.getvalue())

    def test_project_contract_preview_enabled(self):
        self.valid_project["source"]["config"]["preview_deployment_setting"] = "all"
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: Preview enabled rejected", stderr.getvalue())

    def test_malformed_json_200(self):
        def fake_urlopen(req, timeout=None):
            return _FakeResponse(200, b'bad json')

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("token verification FAIL", stderr.getvalue())

    def test_malformed_json_400(self):
        def fake_urlopen(req, timeout=None):
            raise make_http_error(400, b'bad json')

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("token verification FAIL", stderr.getvalue())

    def test_urlerror_handled(self):
        def fake_urlopen(req, timeout=None):
            raise URLError("offline")

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)

    def test_timeout_handled(self):
        def fake_urlopen(req, timeout=None):
            raise socket.timeout("timeout")

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)

    def test_production_url_fails(self):
        def fake_urlopen(req, timeout=None):
            if "pages.dev" in req.full_url:
                raise make_http_error(500, b'error')
            return self._mock_success()(req, timeout)

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("Production URL failure", stderr.getvalue())

    def test_no_token_leakage(self):
        env = self.valid_env.copy()
        env["CLOUDFLARE_API_TOKEN"] = "SUPER_SECRET_TOKEN_VALUE"
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    audit_mod.main()
                    out = stdout.getvalue() + stderr.getvalue()
                    self.assertNotIn("SUPER_SECRET_TOKEN_VALUE", out)
                    self.assertNotIn("token_fingerprint", out)

    def test_project_contract_build_config_root_dir_wrong(self):
        self.valid_project["build_config"]["root_dir"] = "wrong-dir"
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: wrong root directory rejected", stderr.getvalue())

    def test_project_contract_build_config_destination_dir_wrong(self):
        self.valid_project["build_config"]["destination_dir"] = "dist"
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: wrong destination directory rejected", stderr.getvalue())

    def test_project_contract_build_config_build_command_wrong(self):
        self.valid_project["build_config"]["build_command"] = "npm run build"
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: non-empty build command rejected", stderr.getvalue())

    def test_project_contract_deployments_disabled(self):
        self.valid_project["source"]["config"]["production_deployments_enabled"] = False
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: production_deployments_enabled false rejected", stderr.getvalue())

    def test_project_contract_pr_comments_enabled(self):
        self.valid_project["source"]["config"]["pr_comments_enabled"] = True
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: PR comments enabled rejected", stderr.getvalue())

    def test_project_contract_wrong_project_name(self):
        self.valid_project["name"] = "wrong-project-name"
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: wrong project.name", stderr.getvalue())

    def test_project_payload_is_list(self):
        def fake_urlopen(req, timeout=None):
            if f"/projects/{audit_mod.B37_PROJECT}" in req.full_url:
                import json
                return _FakeResponse(200, json.dumps({"success": True, "result": []}).encode("utf-8"))
            return self._mock_success()(req, timeout)

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: project payload is not an object", stderr.getvalue())

    def test_project_payload_is_string(self):
        def fake_urlopen(req, timeout=None):
            if f"/projects/{audit_mod.B37_PROJECT}" in req.full_url:
                import json
                return _FakeResponse(200, json.dumps({"success": True, "result": "mystring"}).encode("utf-8"))
            return self._mock_success()(req, timeout)

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: project payload is not an object", stderr.getvalue())

    def test_source_config_is_list(self):
        self.valid_project["source"]["config"] = []
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: source config is not an object", stderr.getvalue())

    def test_build_config_is_list(self):
        self.valid_project["build_config"] = []
        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("contract: build_config is not an object", stderr.getvalue())

    def test_http_200_non_utf8_body(self):
        def fake_urlopen(req, timeout=None):
            return _FakeResponse(200, b'\xff\xfe\xfd')

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 1)
                    self.assertIn("token verification FAIL", stderr.getvalue())

    def test_all_requests_are_get_and_paths_verified(self):
        methods = []
        urls = []
        def fake_urlopen(req, timeout=None):
            methods.append(req.method)
            urls.append(req.full_url)
            return self._mock_success()(req, timeout)

        with mock.patch.dict(os.environ, self.valid_env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=fake_urlopen):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = audit_mod.main()
                    self.assertEqual(code, 0)
                    for m in methods:
                        self.assertEqual(m, "GET")
                    
                    self.assertIn("https://api.cloudflare.com/client/v4/user/tokens/verify", urls)
                    self.assertIn(f"https://api.cloudflare.com/client/v4/accounts/{audit_mod.EXPECTED_ACCOUNT_ID}/pages/projects", urls)
                    self.assertIn(f"https://api.cloudflare.com/client/v4/accounts/{audit_mod.EXPECTED_ACCOUNT_ID}/pages/projects/{audit_mod.B37_PROJECT}", urls)
                    self.assertIn(audit_mod.B37_URL, urls)

    def test_no_sensitive_info_in_output2(self):
        env = self.valid_env.copy()
        env["CLOUDFLARE_API_TOKEN"] = "SUPER_SECRET_TOKEN_VALUE"
        env["CLOUDFLARE_ACCOUNT_ID"] = "MY_ACCOUNT_ID_SECRET"
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(audit_mod.urllib.request, "urlopen", side_effect=self._mock_success()):
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    audit_mod.main()
                    out = stdout.getvalue() + stderr.getvalue()
                    self.assertNotIn("SUPER_SECRET_TOKEN_VALUE", out)
                    self.assertNotIn("MY_ACCOUNT_ID_SECRET", out)
                    self.assertNotIn("Authorization", out)
                    self.assertNotIn("Bearer", out)
                    self.assertNotIn("fingerprint", out.lower())

if __name__ == "__main__":
    unittest.main()



