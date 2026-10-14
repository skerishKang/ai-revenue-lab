"""HTTP contract tests against a loopback-only temporary preview server."""
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from phone_mock import MockPhoneTasks


class PreviewHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.STORE = MockPhoneTasks()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.PreviewHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def get(self, path):
        with urlopen(self.base + path, timeout=3) as response:
            return response.status, response.headers, response.read()

    def post(self, path, data=None, content_type="application/json"):
        payload = json.dumps(data or {}).encode("utf-8")
        req = Request(self.base + path, data=payload, method="POST",
                      headers={"Content-Type": content_type})
        with urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read())

    def test_static_ui_and_own_origin_csp(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"PADIEM", body)
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        for path in ("/app.js", "/styles.css"):
            self.assertEqual(self.get(path)[0], 200)

    def test_create_read_cancel_and_usage_endpoints(self):
        body = {
            "request_id": "http_test001",
            "destination": "가상 상담센터",
            "goal": "업무에 필요한 서류를 확인해 주세요",
            "source": "claw",
            "scenario": "standard",
        }
        status, task = self.post("/api/tasks", body)
        self.assertEqual(status, 202)
        self.assertEqual(task["network_calls"], 0)
        task_id = task["task_id"]
        _, headers, get_body = self.get("/api/tasks/" + task_id)
        self.assertEqual(json.loads(get_body)["source"], "claw")
        status, result = self.post("/api/tasks/" + task_id + "/cancel")
        self.assertEqual(status, 200)
        self.assertEqual(result["state"], "CANCELLED")
        _, _, usage = self.get("/api/usage")
        self.assertEqual(json.loads(usage)["real_calls"], 0)
        self.assertEqual(json.loads(usage)["real_charges"], 0)

    def test_invalid_content_type_is_rejected(self):
        with self.assertRaises(HTTPError) as err:
            self.post("/api/tasks", {"goal": "dummy"}, content_type="text/plain")
        self.assertEqual(err.exception.code, 415)

    def test_invalid_route_is_404(self):
        with self.assertRaises(HTTPError) as err:
            self.get("/nonexistent")
        self.assertEqual(err.exception.code, 404)

    def test_no_file_traversal(self):
        with self.assertRaises(HTTPError):
            self.get("/.env")
        with self.assertRaises(HTTPError):
            self.get("/../../phone_mock.py")


if __name__ == "__main__":
    unittest.main()
