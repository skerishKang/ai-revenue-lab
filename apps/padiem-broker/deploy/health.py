#!/usr/bin/env python3
"""One read-only loopback health request. Never print URL/headers/body errors."""
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
                or not (parsed.scheme == "http"
                        and parsed.hostname in {"127.0.0.1", "localhost"})):
            return False, status
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(url, timeout=5) as response:
            status = response.status
            raw = response.read(4097)
        body = json.loads(raw)
        return status == 200 and len(raw) <= 4096 and body.get("status") == "ok", status
    except urllib.error.HTTPError as exc:
        return False, exc.code
    except Exception:
        return False, status


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "BROKER_HEALTH=INVALID_ARGUMENT\n")


def main():
    parser = SafeParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    ok, status = check(args.url)
    print("BROKER_HEALTH=" + ("PASS" if ok else "FAIL") + f" STATUS={status}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
