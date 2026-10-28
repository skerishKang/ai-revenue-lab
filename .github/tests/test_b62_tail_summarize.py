"""#4139: the tail summarizer counts what matters and leaks nothing else.

Offline only. The rows here are synthetic; what is proved is that a capture taken
against production traffic can be printed on a shared CI log — outcomes, exception
signatures, paths and colos, never a header, a cookie, a body or a token.
"""
from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "b62_tail_summarize.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "b62-worker-tail-readonly.yml"

spec = importlib.util.spec_from_file_location("b62_tail_summarize", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
summ = importlib.util.module_from_spec(spec)
sys.modules["b62_tail_summarize"] = summ
spec.loader.exec_module(summ)

COOKIE = "padiem_session=eyJhbC.SECRETSUFFIXaaaaaaaaaaaa"
TOKEN = "cfapiv4tokenvalueNOTREAL000000000000"
BODY = "the-whole-request-body-must-never-appear"


def _row(outcome, message, url, colo=None):
    row = {
        "message": message,
        "outcome": outcome,
        "level": "log",
        "timestamp": 1_793_000_000,
        "request": {"method": "GET", "url": url,
                    "headers": {"cookie": COOKIE, "authorization": TOKEN}},
        "event": {"body": BODY},
    }
    if colo is not None:
        row["colo"] = colo
    return row


def _capture(rows):
    out = io.StringIO()
    with redirect_stdout(out):
        summ.emit(summ.summarize(rows))
    return out.getvalue()


class SummarizeTests(unittest.TestCase):
    def test_outcomes_are_bucketed_by_resource_limit_kind(self):
        rows = [
            _row("ok", "hello", "https://chat.padiem.net/health"),
            _row("exception", "TypeError: unhashable", "https://chat.padiem.net/api/pc/pairings"),
            _row("exceedCpu", "worker exceeded CPU time limit", "https://chat.padiem.net/health"),
            _row("exceededMemory", "Memory limit", "https://chat.padiem.net/health"),
            _row("oom", "killed", "https://chat.padiem.net/health"),
        ]
        summary = summ.summarize(rows)
        self.assertEqual(summary["outcomes"]["ok"], 1)
        self.assertEqual(summary["outcomes"]["exception"], 1)
        self.assertEqual(summary["outcomes"]["exceededCpu"], 1)
        self.assertEqual(summary["outcomes"]["exceededMemory"], 2)

    def test_paths_keep_the_path_and_drop_the_query(self):
        rows = [_row("ok", "x", "https://chat.padiem.net/api/pc/result?dispatch_id=abc123&t=SECRET")]
        printed = _capture(rows)
        self.assertIn("/api/pc/result", printed)
        self.assertNotIn("dispatch_id", printed)
        self.assertNotIn("SECRET", printed)

    def test_exception_signatures_are_top_five_and_token_scrubbed(self):
        rows = [_row("exception", "boom", "https://chat.padiem.net/a")
                for _ in range(3)]
        rows.append({"outcome": "exception",
                     "exception": {"pattern": "Error at <tok>" + TOKEN},
                     "message": "irrelevant"})
        summary = summ.summarize(rows)
        top = summary["exceptions"].most_common(1)
        self.assertEqual(top[0][1], 3)
        printed = _capture(rows)
        self.assertNotIn(TOKEN, printed)

    def test_colo_is_counted_when_the_tail_carries_one(self):
        rows = [_row("ok", "x", "https://chat.padiem.net/health", colo="lax"),
                _row("ok", "x", "https://chat.padiem.net/health", colo="ICN")]
        printed = _capture(rows)
        self.assertIn("LAX=1", printed)
        self.assertIn("ICN=1", printed)

    def test_nothing_sensitive_ever_reaches_the_output(self):
        rows = [_row("exception", "TypeError: unhashable", "https://chat.padiem.net/health")]
        printed = _capture(rows)
        for secret in (COOKIE, TOKEN, BODY, "cookie", "authorization"):
            self.assertNotIn(secret, printed)


class LoadTests(unittest.TestCase):
    """The capture shape is what wrangler really writes, not what we guessed.

    The first run produced 4,541 lines and 0 usable rows because wrangler pretty-prints
    one JSON array across many lines. Both shapes must load.
    """

    def _write(self, text):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        handle = pathlib.Path(directory) / "tail.jsonl"
        handle.write_text(text, encoding="utf-8")
        return str(handle)

    def test_a_pretty_printed_json_array_loads(self):
        array = json.dumps([_row("ok", "x", "https://chat.padiem.net/health"),
                            _row("exceedCpu", "cpu", "https://chat.padiem.net/health")], indent=2)
        rows = summ.load(self._write(array))
        self.assertEqual(len(rows), 2)
        summary = summ.summarize(rows)
        self.assertEqual(summary["outcomes"]["ok"], 1)
        self.assertEqual(summary["outcomes"]["exceededCpu"], 1)
        self.assertIn("request", summary["fields"])

    def test_one_object_per_line_still_loads(self):
        text = "\n".join(json.dumps(_row("ok", "x", "https://chat.padiem.net/health"))
                         for _ in range(3))
        self.assertEqual(len(summ.load(self._write(text))), 3)

    def test_wrangler_header_noise_is_skipped_not_counted(self):
        text = ("Connected to padiem-chat...\n"
                "while logs are connected, press ctrl-c to stop\n"
                + json.dumps(_row("exception", "boom", "https://chat.padiem.net/health"))
                + "\n")
        rows = summ.load(self._write(text))
        self.assertEqual(len(rows), 1)
        self.assertEqual(summ.summarize(rows)["outcomes"]["exception"], 1)

    def test_an_empty_capture_says_so_instead_of_printing_nothing(self):
        printed = _capture(summ.load(self._write("")))
        self.assertIn("TAIL_EMPTY=1", printed)


class RealRowShapeTests(unittest.TestCase):
    """The second capture showed the row shape: outcome, exceptions[], logs[], event.

    What matters is that the structured error is read, the request path is read without
    its query, and the app's own log text - which can carry a person's request - never
    reaches a shared CI log.
    """

    ROW = {
        "outcome": "exception",
        "cpuTime": 12,
        "wallTime": 1300,
        "scriptName": "padiem-chat",
        "truncated": False,
        "event": {"request": {"url": "https://chat.padiem.net/api/pc/pairings?t=QUERYSECRET",
                              "headers": {"cookie": COOKIE}},
                  "response": {"status": 500}},
        "exceptions": [{"name": "Error", "pattern": "PythonException: import blew up",
                        "message": "import blew up"}],
        "diagnosticsChannelEvents": [{"body": {"kind": "exception"}}],
        "logs": [{"level": "error", "message": "app log text: " + BODY}],
    }

    def test_signature_path_and_shape_come_out_and_nothing_else_does(self):
        printed = _capture([dict(self.ROW)])
        self.assertIn("PythonException: import blew up", printed)
        self.assertIn("/api/pc/pairings", printed)
        self.assertIn("SHAPE_KEYS=", printed)
        self.assertIn("exceptions[].message", printed)
        self.assertIn("TAIL_TRUNCATED=0/1", printed)
        self.assertNotIn("QUERYSECRET", printed)
        self.assertNotIn(COOKIE, printed)
        self.assertNotIn(BODY, printed)

    def test_the_shape_report_shows_field_lengths_not_field_text(self):
        printed = _capture([dict(self.ROW)])
        self.assertIn("event.request.url=53ch", printed)
        self.assertIn("event.request.<hidden>", printed)
        self.assertNotIn("chat.padiem.net", printed)

    def test_the_response_status_is_read_from_where_the_row_keeps_it(self):
        summary = summ.summarize([dict(self.ROW)])
        self.assertEqual(summary["statuses"]["500"], 1)

    def test_the_colo_comes_from_the_request_cf_metadata(self):
        row = dict(self.ROW)
        row["event"] = dict(row["event"])
        row["event"]["request"] = dict(row["event"]["request"])
        row["event"]["request"]["cf"] = {"colo": "lax", "city": "somewhere",
                                         "asn": 9999, "botManagement": {"verdict": "x"}}
        printed = _capture([row])
        self.assertIn("LAX=1", printed)
        self.assertNotIn("somewhere", printed)

    def test_a_python_worker_that_only_fills_the_stack_still_gives_a_line(self):
        row = {"outcome": "exception",
               "exceptions": [{"name": "", "message": "",
                               "stack": "KeyError: something\n  at module.py line 1\n"}],
               "event": {"request": {"url": ""}}}
        printed = _capture([row])
        self.assertIn("KeyError: something", printed)
        self.assertNotIn("module.py", printed)
        self.assertIn("TAIL_TRUNCATED=0/1", printed)


class WorkflowContractTests(unittest.TestCase):
    def test_the_tail_lane_is_dispatch_only_and_reads_credentials(self):
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)
        self.assertIn("CLOUDFLARE_API_TOKEN", text)
        # Read-only: no deploy, rollback, secret put or d1 apply on this lane.
        for forbidden in ("wrangler deploy", "wrangler rollback", "secret put",
                          "d1 migrations apply", "wrangler versions upload"):
            self.assertNotIn(forbidden, text)
        self.assertIn("b62_tail_summarize.py", text)
        # The tail is always unregistered again, through the API rather than a guessed
        # wrangler flag, so a killed capture cannot leave a live tail behind.
        self.assertIn("TAIL_REGISTERED", text)


if __name__ == "__main__":
    unittest.main()
