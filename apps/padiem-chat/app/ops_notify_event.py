"""Service-only ingress contract; site links and key names are server-owned."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re

from .bounded_request_body import read_bounded_request_body

SITE_LINKS = {
    "lovetree": "https://lovetree-4-0.pages.dev/admin.html",
    # #8140: the local PC agent posts here over loopback. The ops-center link
    # is server-owned, never taken from the request.
    "pc": "https://lovetree-4-0.pages.dev/admin.html#ops-inbox",
}
EVENT_KINDS = ("feedback_new", "feedback_append", "ai_round_score", "agent_stall")
KEY_HEADER = "X-Padiem-Ops-Notify-Key"
FIELDS = {"site", "kind", "audience", "title", "source_id"}
SOURCE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


async def read_event(request):
    """Bound the stream and refuse duplicate JSON keys."""
    raw = await read_bounded_request_body(request, max_bytes=4096)
    data = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or type(data.get("site")) is not str:
        raise ValueError("invalid event")
    return data


def authorized(site, presented):
    if site not in SITE_LINKS or not presented:
        return False
    expected = os.environ.get("PADIEM_OPS_NOTIFY_KEY_" + site.upper())
    if not expected:
        return False
    # Compare fixed-length digests, including for non-ASCII header input.
    return hmac.compare_digest(
        hashlib.sha256(presented.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


def valid_event(data):
    if set(data) != FIELDS or any(type(value) is not str for value in data.values()):
        return False
    title = data["title"]
    return (
        data["site"] in SITE_LINKS
        and data["kind"] in EVENT_KINDS
        and data["audience"] in ("real", "ai")
        and 0 < len(title) <= 80
        and bool(title.strip())
        and all(ch.isprintable() for ch in title)
        and SOURCE_ID.fullmatch(data["source_id"]) is not None
    )


def event_target(site, kind, source_id):
    identity = json.dumps([site, kind, source_id], separators=(",", ":"))
    return "notify_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
