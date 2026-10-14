"""Summarize the zone HTTP-status evidence for the #4549 incident window.

Reads the raw GraphQL responses captured by cfq.py and prints only counts.
No client identifiers, no query strings, no bodies are read or reported.
"""
import json
import re
from collections import Counter

INCIDENT_LO = "2026-10-12T19:49:04Z"
INCIDENT_HI = "2026-10-12T20:40:24Z"
FIVE_XX = {500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530}


def load(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    text = text.split("\n", 1)[1] if text.startswith("HTTP") else text
    return json.loads(text)


def groups(body, alias):
    zones = (body.get("data") or {}).get("viewer", {}).get("zones") or [{}]
    return zones[0].get(alias) or []


hours = groups(load("_synccheck/out/hours.json"), "httpRequestsAdaptiveGroups")
per_hour = Counter()
status_by_hour = {}
for g in hours:
    h = g["dimensions"]["datetimeHour"]
    st = g["dimensions"]["edgeResponseStatus"]
    per_hour[h] += g["count"]
    status_by_hour.setdefault(h, Counter())[st] += g["count"]

print("HOUR_BUCKETS_RETURNED=%d  TOTAL_REQUESTS=%d" % (len(per_hour), sum(per_hour.values())))
print("HOUR_RANGE=%s..%s" % (min(per_hour), max(per_hour)))
five = {h: sum(c for s, c in v.items() if s in FIVE_XX) for h, v in status_by_hour.items()}
five = {h: c for h, c in five.items() if c}
print("HOURS_WITH_5XX_COUNT=%d" % len(five))
if five:
    print("5XX_HOUR_RANGE=%s..%s" % (min(five), max(five)))
    print("5XX_TOTAL=%d" % sum(five.values()))
    for h in sorted(five):
        print("  5xx_hour %s %s" % (h, dict(sorted(status_by_hour[h].items()))))
print("--- incident-window hour buckets (19:00Z..21:00Z 2026-10-12) ---")
first5 = None
for h in sorted(status_by_hour):
    if "2026-10-12T19" <= h < "2026-10-12T21":
        assert h in ("2026-10-12T19:00:00Z", "2026-10-12T20:00:00Z"), h
        print("  %s %s" % (h, dict(sorted(status_by_hour[h].items()))))
        assert all(s not in FIVE_XX for s in status_by_hour[h]), "5XX in incident hour!"

burst = load("_synccheck/out/burst.json")
print("--- burst minute 2026-10-12T20:12Z (KST 05:12) ---")
mt = Counter()
for g in groups(burst, "methods"):
    d = g["dimensions"]
    mt["%s->%s" % (d["clientRequestHTTPMethodName"], d["edgeResponseStatus"])] += g["count"]
print("METHOD_X_STATUS", dict(sorted(mt.items(), key=lambda kv: -kv[1])))
paths = groups(burst, "paths")
print("DISTINCT_PATHS=%d  PATH_REQUESTS=%d" % (len(paths), sum(p["count"] for p in paths)))

# Classify paths by scan signature only; no raw path is printed.
SIG = {
    "secret_file_probe": (".env", ".git", "server.key", ".ssh", "id_rsa", ".aws", "credentials"),
    "path_traversal": ("%2e%2e", "../", "..\\"),
    "php_or_cms_probe": (".php", "wp-", "xmlrpc", "cgi-bin"),
    "admin_or_actuator_probe": ("actuator", "admin", "console", "swagger", "graphql"),
}
shape = Counter()
unmatched = 0
for p in paths:
    path = p["dimensions"]["clientRequestPath"].lower()
    hit = next((k for k, keys in SIG.items() if any(x in path for x in keys)), None)
    if hit is None:
        unmatched += p["count"]
        shape["other"] += p["count"]
    else:
        shape[hit] += p["count"]
print("PATH_SIGNATURES", dict(sorted(shape.items(), key=lambda kv: -kv[1])))
print("PATH_OTHER_SHARE=%d/%d" % (unmatched, sum(p["count"] for p in paths)))
