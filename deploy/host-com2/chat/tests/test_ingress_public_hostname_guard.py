"""chat.padiem.net must never be bound by a COM2 tunnel example.

#6400 moves the ``chat.padiem.net`` Custom Domain from the ``padiem-chat``
Python Worker to ``padiem-chat-front``, which signs the request and forwards it
to ``FRONT_ORIGIN`` (``https://chat-com2.padiem.net``, tunnel → 8798). A tunnel
that binds ``chat.padiem.net`` itself would deliver unsigned traffic straight to
COM2 and skip the signer, so no example under ``deploy/host-com2`` may do it.

The second half of the file pins the hop the front actually calls: the tunnel
hostname and port must be the ones the production unit binds, and -- once #6400
is in main -- must equal the front's own ``FRONT_ORIGIN``.

No file here is installed by this repository and nothing contacts Cloudflare.
"""
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parents[1]
DEPLOY_ROOT = HERE.parent
PUBLIC_HOSTNAME = "chat.padiem.net"
ORIGIN_HOSTNAME = "chat-com2.padiem.net"
CHAT_UNIT = HERE / "padiem-chat-com2.service"
STAGING_UNIT = HERE / "padiem-chat-staging.service"
TUNNEL_EXAMPLE = HERE / "cloudflared-chat-com2.example.yml"
TUNNEL_PORT = "8798"
FRONT_WRANGLER = Path(__file__).resolve().parents[4] / "apps" / "padiem-chat-front" / "wrangler.toml"
FRONT_RUNBOOK = (
    Path(__file__).resolve().parents[4] / "docs" / "operations" / "CHAT_COM2_FRONT_RUNBOOK.md"
)


def ingress_entries(path):
    """Parse the flat ``ingress:`` list cloudflared accepts for our examples."""

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
    return entries


def hostname_values(path):
    """Every ``hostname:`` value in a YAML file, comments ignored."""

    values = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        body = raw.split("#", 1)[0].strip()
        if body.startswith("- hostname:") or body.startswith("hostname:"):
            values.append(body.split(":", 1)[1].strip().strip("'\""))
    return values


class NoPublicHostnameInTunnelExamples(unittest.TestCase):
    def test_there_is_at_least_one_tunnel_example(self):
        # Guards the guard: an empty glob would make the next test vacuous.
        examples = [
            path
            for path in DEPLOY_ROOT.rglob("*.y*ml")
            if "cloudflared" in path.name or "hostname:" in path.read_text("utf-8")
        ]
        self.assertTrue(examples)

    def test_no_example_binds_the_public_hostname(self):
        offenders = []
        for path in DEPLOY_ROOT.rglob("*.y*ml"):
            for hostname in hostname_values(path):
                if hostname == PUBLIC_HOSTNAME:
                    offenders.append(str(path.relative_to(DEPLOY_ROOT)))
        self.assertEqual(
            offenders,
            [],
            "a tunnel that binds chat.padiem.net bypasses padiem-chat-front",
        )

    def test_the_runbook_and_front_own_the_public_hostname(self):
        # The only place the public hostname may appear is the front's own
        # files: its route is declared there, not in a tunnel config.
        if FRONT_RUNBOOK.is_file():
            self.assertIn(PUBLIC_HOSTNAME, FRONT_RUNBOOK.read_text("utf-8"))


class TunnelOriginHop(unittest.TestCase):
    def test_the_tunnel_binds_the_origin_hostname_and_production_port(self):
        entries = ingress_entries(TUNNEL_EXAMPLE)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["hostname"], ORIGIN_HOSTNAME)
        self.assertEqual(entries[0]["service"], f"http://127.0.0.1:{TUNNEL_PORT}")
        self.assertEqual(entries[-1].get("service"), "http_status:404")
        self.assertNotIn("hostname", entries[-1])

    def test_the_origin_port_is_the_production_unit_not_the_staging_one(self):
        production = CHAT_UNIT.read_text("utf-8")
        self.assertIn(f"--host 127.0.0.1 --port {TUNNEL_PORT}", production)
        self.assertIn("/mnt/d/padiem/chat-com2", production)
        # 8801 belongs to the staging unit; a tunnel that carried it while
        # calling itself the parallel host would point production at staging.
        staging = STAGING_UNIT.read_text("utf-8")
        self.assertIn("--port 8801", staging)
        self.assertNotIn(TUNNEL_PORT, staging)

    def test_the_front_origin_matches_the_tunnel_hop(self):
        if not FRONT_WRANGLER.is_file():
            raise unittest.SkipTest(
                "#6400 (feat/chat-com2-edge-gate-261031) is not in main yet; "
                "enable this comparison once apps/padiem-chat-front lands"
            )
        match = re.search(
            r'^FRONT_ORIGIN\s*=\s*"([^"]+)"', FRONT_WRANGLER.read_text("utf-8"), re.M
        )
        self.assertIsNotNone(match, "the front declares no FRONT_ORIGIN")
        parsed = urlsplit(match.group(1))

        entries = ingress_entries(TUNNEL_EXAMPLE)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, entries[0]["hostname"])
        self.assertEqual(parsed.query, "")
        service = urlsplit(entries[0]["service"])
        self.assertEqual(service.port, int(TUNNEL_PORT))
        # FRONT_ORIGIN is an https hostname with no explicit port (443); if it
        # ever names a port, that port must be the tunnel's.
        self.assertIn(parsed.port, (None, int(TUNNEL_PORT)))


    def test_the_front_signer_is_present_before_the_hop_is_trusted(self):
        # The guard exists because a signer sits in front of the tunnel. main
        # already carries the front proxy and its FRONT_ORIGIN (#6168); the
        # signer itself is #6400 work, so this half waits for it.
        signer = FRONT_WRANGLER.parent / "edge-proof.mjs"
        if not signer.is_file():
            raise unittest.SkipTest(
                "#6400 signer (apps/padiem-chat-front/edge-proof.mjs) is not in "
                "main yet; enable this once it lands"
            )
        self.assertIn("x-padiem-edge", signer.read_text("utf-8"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
