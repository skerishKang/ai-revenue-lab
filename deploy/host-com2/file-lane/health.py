#!/usr/bin/env python3
"""One read-only HTTP health request. Never print URL/headers/body/errors."""
import argparse
import json
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check(url):
    status = 0
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path != "/health" or not parsed.hostname
                or (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}))):
            return False, status
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(url, timeout=5) as response:
            status = response.status
            raw = response.read(4097)
        return status == 200 and len(raw) <= 4096 and json.loads(raw) == {"ok": True}, status
    except urllib.error.HTTPError as exc:
        return False, exc.code
    except Exception:
        return False, status


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "FILE_LANE_HEALTH=INVALID_ARGUMENT\n")


def main():
    parser = SafeParser()
    parser.add_argument("--url", default="http://127.0.0.1:8788/health")
    args = parser.parse_args()
    ok, status = check(args.url)
    print(json.dumps({"health_ok": ok, "status_code": status}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
