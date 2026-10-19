"""Aggregate the incident-window telemetry evidence from the completed slice runs."""
import datetime as dt
import re
import subprocess

REPO = "skerishKang/ai-revenue-lab"
KST = dt.timezone(dt.timedelta(hours=9))
RUNS = {
    1791834544000: 38310136097, 1791834844000: 38310893256,
    1791835144000: 38311003502, 1791835444000: 38311127435,
    1791835744000: 38311277012, 1791836044000: 38311353534,
    1791836344000: 38311462875, 1791836644000: 38311651178,
    1791836944000: 38312048099, 1791837244000: 38311885617,
    1791837544000: 38311999082,
}
KEYS = (
    "B62_ANALYTICS_REQUESTS", "B62_ANALYTICS_ERRORS", "B62_ANALYTICS_SUBREQUESTS",
    "ENGINE_ANALYTICS_REQUESTS", "ENGINE_ANALYTICS_ERRORS",
    "B14_ANALYTICS_REQUESTS", "B14_ANALYTICS_ERRORS",
    "CP_ADMISSION_ANALYTICS_REQUESTS", "CP_IDENTITY_ANALYTICS_REQUESTS",
)
DIGITS = re.compile(r"=(\d+)")


def gh(rid, *args):
    return subprocess.run(["gh", *args], capture_output=True, text=True).stdout


def kst(ms):
    return dt.datetime.fromtimestamp(ms / 1000, tz=KST).strftime("%H:%M:%S")


rows = []
missing = []
for start, rid in sorted(RUNS.items()):
    log = gh(rid, "run", "view", str(rid), "--repo", REPO, "--log")
    vals = {}
    for k in KEYS:
        hits = re.findall(re.escape(k) + DIGITS.pattern, log)
        vals[k] = int(hits[-1]) if hits else 0
        if not hits:
            missing.append((start, k))
    rows.append({
        "start": start,
        "run": rid,
        "obs": (re.findall(r"OBSERVABILITY_QUERY_HTTP=(\d+)", log) or [None])[-1],
        "retained": (re.findall(r"RETAINED_LOG_EVIDENCE=(\w+)", log) or [None])[-1],
        "analytics": (re.findall(r"WORKERS_ANALYTICS=(\w+)", log) or [None])[-1],
        **vals,
    })

hdr = (
    f"{'slice':<17}{'KST window':<22}{'run':<12}{'B62req':>7}{'B62err':>7}{'B62sub':>7}"
    f"{'ENGreq':>7}{'B14req':>7}{'B14err':>7}{'CPa':>5}{'CPi':>5}  obs retained analytics"
)
print(hdr)
print("-" * len(hdr))
for r in rows:
    span = kst(r["start"]) + "-" + kst(r["start"] + 300000)
    print(
        f"{r['start']:<17}{span:<22}{r['run']:<12}"
        f"{r['B62_ANALYTICS_REQUESTS']:>7}{r['B62_ANALYTICS_ERRORS']:>7}"
        f"{r['B62_ANALYTICS_SUBREQUESTS']:>7}{r['ENGINE_ANALYTICS_REQUESTS']:>7}"
        f"{r['B14_ANALYTICS_REQUESTS']:>7}{r['B14_ANALYTICS_ERRORS']:>7}"
        f"{r['CP_ADMISSION_ANALYTICS_REQUESTS']:>5}{r['CP_IDENTITY_ANALYTICS_REQUESTS']:>5}"
        f"  {r['obs']} {r['retained']} {r['analytics']}"
    )
print("-" * len(hdr))
print("TOTALS " + " ".join(f"{k}={sum(r[k] for r in rows)}" for k in KEYS))
print("SLICES_COLLECTED=" + str(len(rows)))
print("MISSING_KEYS=" + ("NONE" if not missing else str(missing)))
print("OBSERVABILITY_HTTP_VALUES=" + str(sorted({str(r["obs"]) for r in rows})))
print("RETAINED_LOG_EVIDENCE_VALUES=" + str(sorted({str(r["retained"]) for r in rows})))
print("WORKERS_ANALYTICS_VALUES=" + str(sorted({str(r["analytics"]) for r in rows})))
print("B62_ERROR_NONZERO_SLICES=" + str([r["start"] for r in rows if r["B62_ANALYTICS_ERRORS"]]))
print("ENGINE_NONZERO_SLICES=" + str([r["start"] for r in rows if r["ENGINE_ANALYTICS_REQUESTS"]]))
