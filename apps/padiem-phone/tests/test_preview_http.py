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
from phone_scripts import ScriptStore


class PreviewHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.STORE = MockPhoneTasks()
        server.SCRIPTS = ScriptStore()  # Fresh, non-persistent test fixture.
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
        for path in ("/app.js", "/styles.css", "/assets/padiem-glass-female.jpg"):
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

    def test_script_crud_and_immutable_task_snapshot(self):
        script_data = {
            "title": "견적 확인",
            "destination": "가상 거래처",
            "goal": "견적 항목의 명칭과 규격을 문의해 줘",
            "questions": "규격은 무엇인가요?",
            "notes": "결제 또는 확정하지 마세요",
        }
        status, saved = self.post("/api/scripts", script_data)
        self.assertEqual(status, 201)
        self.assertEqual(saved["revision"], 1)
        _, _, raw = self.get("/api/scripts")
        self.assertEqual(len(json.loads(raw)["scripts"]), 4)

        task_data = {
            "request_id": "http_script001",
            "source": "claw",
            "scenario": "standard",
            "script_id": saved["script_id"],
            "goal": saved["goal"],
            "destination": saved["destination"],
        }
        status, task = self.post("/api/tasks", task_data)
        self.assertEqual(status, 202)
        self.assertEqual(task["notes"], script_data["notes"])
        self.assertEqual(task["questions"], script_data["questions"])
        self.assertEqual(task["script_id"], saved["script_id"])
        self.assertEqual(task["network_calls"], 0)

        update = {**script_data, "title": "바뀐 제목", "notes": "변경된 주의사항", "revision": 1}
        req = Request(self.base + "/api/scripts/" + saved["script_id"],
                      data=json.dumps(update, ensure_ascii=False).encode("utf-8"), method="PUT",
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=3) as resp:
            revised = json.loads(resp.read())
        self.assertEqual(revised["revision"], 2)
        _, _, old_result = self.get("/api/tasks/" + task["task_id"])
        self.assertEqual(json.loads(old_result)["notes"], script_data["notes"])

        request = Request(self.base + "/api/scripts/" + saved["script_id"],
                          data=json.dumps({"revision": 2}).encode(), method="DELETE",
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=3) as resp:
            self.assertTrue(json.loads(resp.read())["deleted"])
        _, _, result = self.get("/api/tasks/" + task["task_id"])
        self.assertEqual(json.loads(result)["notes"], script_data["notes"])

    def test_script_spoofing_and_cross_origin_rejected(self):
        _, _, raw = self.get("/api/scripts")
        built_in = json.loads(raw)["scripts"][0]
        body = {
            "request_id": "http_spoof001", "source": "claw",
            "goal": "다른 목표", "destination": built_in["destination"],
            "script_id": built_in["script_id"],
        }
        with self.assertRaises(HTTPError) as error:
            self.post("/api/tasks", body)
        self.assertEqual(error.exception.code, 409)

        with self.assertRaises(HTTPError) as error:
            self.post("/api/tasks", {**body, "script_id": []})
        self.assertEqual(error.exception.code, 400)
        malicious = Request(self.base + "/api/scripts", data=b"{}",
                            method="POST", headers={
                                "Content-Type": "application/json",
                                "Origin": "https://untrusted.example",
                            })
        with self.assertRaises(HTTPError) as error:
            urlopen(malicious, timeout=3)
        self.assertEqual(error.exception.code, 403)

        wrong_host = Request(self.base + "/api/scripts", headers={"Host": "untrusted.example"})
        with self.assertRaises(HTTPError) as error:
            urlopen(wrong_host, timeout=3)
        self.assertEqual(error.exception.code, 403)

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
