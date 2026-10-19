"""Read-only Cloudflare analytics probe for the #4549 incident window.

Uses the local wrangler OAuth credential. Never prints the token or any
per-request identifier: only aggregate counts leave this process.

Usage:
  python cfq.py zones
  python cfq.py introspect <account|zone>
  python cfq.py httpstatus <zone_tag> <host> <from_iso> <to_iso>
  python cfq.py workers <account_tag> <script> <from_iso> <to_iso>
"""
import json
import os
import re
import sys
import urllib.request

CFG = os.path.expanduser("~/.wrangler/config/default.toml")
API = "https://api.cloudflare.com/client/v4"
ACCOUNT = "9be14bb7b8974e65d0afba647ab16932"


def token():
    text = open(CFG, encoding="utf-8").read()
    m = re.search(r'oauth_token\s*=\s*"([^"]+)"', text)
    if not m:
        sys.exit("NO_LOCAL_OAUTH_TOKEN")
    return m.group(1)


def call(path, payload=None):
    url = API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", "Bearer " + token())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body[:400]}


def graphql(query, variables):
    status, body = call("/graphql", {"query": query, "variables": variables})
    return status, body


def main():
    cmd = sys.argv[1]
    if cmd == "zones":
        status, body = call("/zones?per_page=50")
        print("HTTP", status, "success", body.get("success"), "errors", body.get("errors"))
        for z in body.get("result") or []:
            print(z["id"], z["name"], z.get("plan", {}).get("name") if isinstance(z.get("plan"), dict) else "")
        res = body.get("result_info")
        print("result_info", res)
    elif cmd == "introspect":
        scope = sys.argv[2]
        q = """
        { __type(name: "%s") { fields { name } } }
        """ % scope
        status, body = graphql(q, {})
        print("HTTP", status, json.dumps(body)[:600])
        fields = ((body.get("data") or {}).get("__type") or {}).get("fields") or []
        for f in fields:
            n = f["name"]
            if "Adaptive" in n or "Requests" in n or "Invocation" in n:
                print("  CANDIDATE", n)
    elif cmd == "httpstatus":
        tag, host, lo, hi = sys.argv[2:6]
        q = """
        query Q($tag: String!, $lo: Time!, $hi: Time!, $host: String!) {
          viewer {
            zones(filter: {zoneTag: $tag}) {
              httpRequestsAdaptiveGroups(
                limit: 1000
                filter: {clientRequestHTTPHost: $host, datetime_geq: $lo, datetime_leq: $hi}
                orderBy: [count_DESC]
              ) {
                count
                dimensions { datetimeMinute edgeResponseStatus }
              }
            }
          }
        }
        """
        status, body = graphql(q, {"tag": tag, "lo": lo, "hi": hi, "host": host})
        print("HTTP", status)
        print(json.dumps(body)[:3000])
    elif cmd == "statuses":
        tag, host, lo, hi = sys.argv[2:6]
        q = """
        query Q($tag: String!, $lo: Time!, $hi: Time!, $host: String!) {
          viewer {
            zones(filter: {zoneTag: $tag}) {
              httpRequestsAdaptiveGroups(
                limit: 200
                filter: {clientRequestHTTPHost: $host, datetime_geq: $lo, datetime_leq: $hi}
                orderBy: [count_DESC]
              ) {
                count
                dimensions { edgeResponseStatus }
              }
            }
          }
        }
        """
        status, body = graphql(q, {"tag": tag, "lo": lo, "hi": hi, "host": host})
        print("HTTP", status)
        print(json.dumps(body)[:2000])
    elif cmd == "hoststatus":
        tag, lo, hi = sys.argv[2:5]
        q = """
        query Q($tag: String!, $lo: Time!, $hi: Time!) {
          viewer {
            zones(filter: {zoneTag: $tag}) {
              httpRequestsAdaptiveGroups(
                limit: 1000
                filter: {datetime_geq: $lo, datetime_leq: $hi}
                orderBy: [count_DESC]
              ) {
                count
                dimensions { clientRequestHTTPHost edgeResponseStatus }
              }
            }
          }
        }
        """
        status, body = graphql(q, {"tag": tag, "lo": lo, "hi": hi})
        print("HTTP", status)
        print(json.dumps(body)[:4000])
    elif cmd == "fieldtype":
        want = sys.argv[2]
        q = '{ __type(name: "zone") { fields { name type { name } } } }'
        status, body = graphql(q, {})
        print("HTTP", status)
        for f in ((body.get("data") or {}).get("__type") or {}).get("fields") or []:
            if f["name"] == want:
                print("TYPE", f["type"]["name"])
    elif cmd == "ftype":
        tname, fname = sys.argv[2], sys.argv[3]
        q = ('{ __type(name: "%s") { fields { name type { kind name ofType { name } } } } }' % tname)
        status, body = graphql(q, {})
        print("HTTP", status)
        for f in ((body.get("data") or {}).get("__type") or {}).get("fields") or []:
            if f["name"] == fname:
                print("  FIELD", f["name"], f["type"])
    elif cmd == "types":
        needle = sys.argv[2].lower()
        status, body = graphql("{ __schema { types { name } } }", {})
        print("HTTP", status)
        for t in ((body.get("data") or {}).get("__schema") or {}).get("types") or []:
            if needle in t["name"].lower():
                print("  TYPE", t["name"])
    elif cmd == "dims":
        tname = sys.argv[2]
        q = ('{ __type(name: "%s") { fields { name } inputFields { name } } }' % tname)
        status, body = graphql(q, {})
        print("HTTP", status)
        t = (body.get("data") or {}).get("__type") or {}
        for f in (t.get("fields") or []) + (t.get("inputFields") or []):
            print("  FIELD", f["name"])
    elif cmd == "fivexx":
        tag, lo, hi = sys.argv[2:5]
        q = """
        query Q($tag: String!, $lo: Time!, $hi: Time!) {
          viewer {
            zones(filter: {zoneTag: $tag}) {
              httpRequestsAdaptiveGroups(
                limit: 1000
                filter: {
                  datetime_geq: $lo
                  datetime_leq: $hi
                  edgeResponseStatus_in: [500, 501, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530]
                }
                orderBy: [count_DESC]
              ) {
                count
                dimensions { datetimeMinute clientRequestHTTPHost edgeResponseStatus }
              }
            }
          }
        }
        """
        status, body = graphql(q, {"tag": tag, "lo": lo, "hi": hi})
        print("HTTP", status)
        print(json.dumps(body))
    elif cmd == "hours":
        tag, lo, hi = sys.argv[2:5]
        q = """
        query Q($tag: String!, $lo: Time!, $hi: Time!) {
          viewer {
            zones(filter: {zoneTag: $tag}) {
              httpRequestsAdaptiveGroups(
                limit: 1000
                filter: {datetime_geq: $lo, datetime_leq: $hi}
                orderBy: [count_DESC]
              ) {
                count
                dimensions { datetimeHour edgeResponseStatus }
              }
            }
          }
        }
        """
        status, body = graphql(q, {"tag": tag, "lo": lo, "hi": hi})
        print("HTTP", status)
        print(json.dumps(body))
    elif cmd == "zonestatuses":
        tag, lo, hi = sys.argv[2:5]
        q = """
        query Q($tag: String!, $lo: Time!, $hi: Time!) {
          viewer {
            zones(filter: {zoneTag: $tag}) {
              httpRequestsAdaptiveGroups(
                limit: 200
                filter: {datetime_geq: $lo, datetime_leq: $hi}
                orderBy: [count_DESC]
              ) {
                count
                dimensions { edgeResponseStatus }
              }
            }
          }
        }
        """
        status, body = graphql(q, {"tag": tag, "lo": lo, "hi": hi})
        print("HTTP", status)
        print(json.dumps(body)[:2000])
    elif cmd == "burst":
        tag, host, lo, hi = sys.argv[2:6]
        q = """
        query Q($tag: String!, $lo: Time!, $hi: Time!, $host: String!) {
          viewer {
            zones(filter: {zoneTag: $tag}) {
              methods: httpRequestsAdaptiveGroups(
                limit: 100
                filter: {clientRequestHTTPHost: $host, datetime_geq: $lo, datetime_leq: $hi}
                orderBy: [count_DESC]
              ) {
                count
                dimensions { clientRequestHTTPMethodName edgeResponseStatus }
              }
              paths: httpRequestsAdaptiveGroups(
                limit: 100
                filter: {clientRequestHTTPHost: $host, datetime_geq: $lo, datetime_leq: $hi}
                orderBy: [count_DESC]
              ) {
                count
                dimensions { clientRequestPath }
              }
            }
          }
        }
        """
        status, body = graphql(q, {"tag": tag, "lo": lo, "hi": hi, "host": host})
        print("HTTP", status)
        print(json.dumps(body))
    elif cmd == "workers":
        acc, script, lo, hi = sys.argv[2:6]
        q = """
        query Q($acc: String!, $lo: Time!, $hi: Time!, $script: String!) {
          viewer {
            accounts(filter: {accountTag: $acc}) {
              workersInvocationsAdaptive(
                limit: 1000
                filter: {scriptName: $script, datetime_geq: $lo, datetime_leq: $hi}
                orderBy: [count_DESC]
              ) {
                count
                dimensions { datetimeMinute status }
                sum { requests errors subrequests }
              }
            }
          }
        }
        """
        status, body = graphql(q, {"acc": acc, "lo": lo, "hi": hi, "script": script})
        print("HTTP", status)
        print(json.dumps(body)[:3000])
    else:
        sys.exit("unknown command")


if __name__ == "__main__":
    main()
