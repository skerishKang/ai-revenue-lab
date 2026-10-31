"""Checks for the public chat.padiem.net ingress examples.

The files are examples only: nothing installs them, so these tests are the
review of their shape. They parse the YAML subset cloudflared ingress uses
(top-level keys plus one list of maps) instead of adding a dependency, and
they never contact Cloudflare.

What is pinned:
* exactly one hostname rule per file, on chat.padiem.net;
* the production origin is the COM2 Chat port 8798 on loopback;
* both files end with the http_status:404 catch-all;
* the two files differ only in the origin line;
* only placeholders are committed (no tunnel UUID, credentials path or token).
"""
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PRODUCTION = HERE / "cloudflared-chat-public-com2.example.yml"
ROLLBACK = HERE / "cloudflared-chat-public-worker-rollback.example.yml"
HOSTNAME = "chat.padiem.net"
COM2_CHAT_PORT = "8798"
ORIGIN_KEYS = {"service", "httpHostHeader"}


def parse(path):
    """Return ``(top_level_scalars, ingress_entries)`` for a flat config."""

    top = {}
    entries = []
    current = None
    in_ingress = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.strip() == "ingress:":
            in_ingress = True
            continue
        if not in_ingress:
            key, _, value = line.partition(":")
            top[key.strip()] = value.strip()
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            current = {}
            entries.append(current)
            stripped = stripped[2:]
        if current is None:
            continue
        key, _, value = stripped.partition(":")
        current[key.strip()] = value.strip()
    return top, entries


def skeleton(path):
    """The file with comments, blank lines and origin lines removed."""

    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        body = raw.split("#", 1)[0].strip()
        if body.startswith("service:") or body.startswith("httpHostHeader:"):
            continue
        if body:
            lines.append(body)
    return lines


class PublicIngressExamples(unittest.TestCase):
    def setUp(self):
        self.production_top, self.production = parse(PRODUCTION)
        self.rollback_top, self.rollback = parse(ROLLBACK)

    def test_each_file_has_one_hostname_rule(self):
        for name, entries in (
            ("production", self.production),
            ("rollback", self.rollback),
        ):
            hostnames = [entry for entry in entries if "hostname" in entry]
            self.assertEqual(len(hostnames), 1, name)
            self.assertEqual(hostnames[0]["hostname"], HOSTNAME, name)

    def test_both_files_end_with_the_catch_all(self):
        for name, entries in (
            ("production", self.production),
            ("rollback", self.rollback),
        ):
            self.assertEqual(len(entries), 2, name)
            self.assertEqual(entries[-1].get("service"), "http_status:404", name)
            self.assertNotIn("hostname", entries[-1], name)
            self.assertEqual(entries[0].get("service") != "http_status:404", True, name)

    def test_the_production_origin_is_the_com2_chat_port(self):
        entry = self.production[0]
        self.assertEqual(entry["service"], f"http://127.0.0.1:{COM2_CHAT_PORT}")
        # No Host or path rewrite: the edge proof signs the exact path.
        self.assertNotIn("httpHostHeader", entry)
        self.assertNotIn("path", entry)
        text = PRODUCTION.read_text(encoding="utf-8")
        self.assertIn("disableChunkedEncoding: false", text)
        self.assertIn(f"--port {COM2_CHAT_PORT}", text)

    def test_the_production_origin_matches_the_service_unit(self):
        unit = (HERE / "padiem-chat-com2.service").read_text(encoding="utf-8")
        self.assertIn(f"--port {COM2_CHAT_PORT}", unit)
        self.assertNotIn("--host 0.0.0.0", unit)

    def test_the_rollback_origin_is_not_the_com2_host(self):
        origin = self.rollback[0]["service"]
        self.assertTrue(origin.startswith("https://"), origin)
        self.assertNotIn(COM2_CHAT_PORT, origin)
        self.assertNotIn("127.0.0.1", origin)
        self.assertIn("PADIEM_CHAT_WORKERS_DEV_ORIGIN", origin)

    def test_the_two_files_differ_only_in_the_origin(self):
        self.assertEqual(self.production_top, self.rollback_top)
        self.assertEqual(len(self.production), len(self.rollback))

        differences = [
            (left, right)
            for left, right in zip(self.production, self.rollback)
            if left != right
        ]
        self.assertEqual(len(differences), 1)

        left, right = differences[0]
        changed = {key for key in left if left.get(key) != right.get(key)}
        changed |= {key for key in right if key not in left}
        self.assertTrue(changed <= ORIGIN_KEYS, changed)
        self.assertEqual(set(left) - ORIGIN_KEYS, set(right) - ORIGIN_KEYS)

        self.assertEqual(skeleton(PRODUCTION), skeleton(ROLLBACK))

    def test_no_real_tunnel_identity_is_committed(self):
        for path in (PRODUCTION, ROLLBACK):
            text = path.read_text(encoding="utf-8")
            self.assertIn("tunnel: CHAT_PUBLIC_TUNNEL_UUID", text)
            self.assertIn("/etc/cloudflared/CHAT_PUBLIC_TUNNEL_UUID.json", text)
            self.assertNotIn("token:", text)
            # A real UUID is 8-4-4-4-12 hex; placeholders must not look like one.
            self.assertIsNone(
                re.search(
                    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                    text,
                )
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
