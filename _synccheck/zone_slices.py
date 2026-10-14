"""Run the CENTRAL-specified 11 contiguous read-only slices for #4549.

Reuses the read-only GraphQL probe in cfq.py. Aggregate counts only:
no paths, no IPs, no cookies, no queries, no bodies.
"""
import datetime as dt
import json
import sys

import cfq

ZONE = "f2197563fb53859673270dcdd9aef28b"
HOST = "chat.padiem.net"
START_MS = 1791834544000
END_MS = 1791837624000
SLICE_MS = 300000
UTC = dt.timezone.utc

QUERY = """
query Q($tag: String!, $lo: Time!, $hi: Time!, $host: String!) {
  viewer {
    zones(filter: {zoneTag: $tag}) {
      httpRequestsAdaptiveGroups(
        limit: 1000
        filter: {clientRequestHTTPHost: $host, datetime_geq: $lo, datetime_leq: $hi}
        orderBy: [count_DESC]
      ) {
        count
        confidence(level: 0.95) { count { estimate sampleSize isValid } }
        dimensions { edgeResponseStatus }
      }
    }
  }
}
"""

FIVE_XX = {500, 501, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530}


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    slices = []
    cur = START_MS
    while cur < END_MS:
        nxt = min(cur + SLICE_MS, END_MS)
        slices.append((cur, nxt))
        cur = nxt

    per_status_total = {}
    per_slice_5xx = {}
    grand = 0
    for idx, (lo, hi) in enumerate(slices, 1):
        status, body = cfq.graphql(QUERY, {"tag": ZONE, "lo": iso(lo), "hi": iso(hi), "host": HOST})
        if status != 200 or body.get("errors"):
            print("SLICE_%d ERROR http=%s %s" % (idx, status, json.dumps(body.get("errors"))[:300]))
            sys.exit(1)
        groups = ((((body.get("data") or {}).get("viewer") or {}).get("zones") or [{}])[0]
                  .get("httpRequestsAdaptiveGroups") or [])
        counts = {}
        conf = []
        for g in groups:
            counts[g["dimensions"]["edgeResponseStatus"]] = counts.get(
                g["dimensions"]["edgeResponseStatus"], 0) + g["count"]
            c = g.get("confidence") or {}
            cc = c.get("count") or {}
            conf.append((cc.get("sampleSize"), cc.get("estimate"), cc.get("isValid")))
        total = sum(counts.values())
        five = sum(c for s, c in counts.items() if s in FIVE_XX)
        grand += total
        per_slice_5xx[idx] = five
        for s, c in counts.items():
            per_status_total[s] = per_status_total.get(s, 0) + c
        print("SLICE_%02d %s..%s requests=%d fivexx=%d %s conf=%s"
              % (idx, iso(lo), iso(hi), total, five, dict(sorted(counts.items())), conf))

    print("---")
    print("SLICES=%d" % len(slices))
    print("WINDOW=%s..%s" % (iso(START_MS), iso(END_MS)))
    print("HOST_REQUESTS_TOTAL=%d" % grand)
    print("HOST_HTTP_STATUS_TOTALS=%s" % dict(sorted(per_status_total.items())))
    print("HOST_HTTP_5XX_TOTAL=%d" % sum(per_slice_5xx.values()))
    print("SLICES_WITH_5XX=%s" % [k for k, v in per_slice_5xx.items() if v])


if __name__ == "__main__":
    main()
