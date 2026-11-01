import subprocess, json, sys, re
R="skerishKang/ai-revenue-lab"; pr=sys.argv[1]
def run(a): return subprocess.run(a,capture_output=True,text=True,encoding="utf-8",errors="replace").stdout
roll=json.loads(run(["gh","pr","view",pr,"--repo",R,"--json","statusCheckRollup"]))["statusCheckRollup"]
for c in roll:
    if c.get("conclusion")=="FAILURE":
        url=c.get("detailsUrl") or ""
        m=re.search(r"/job/(\d+)",url)
        print("FAILED:", c.get("name"), url)
        if m:
            log=run(["gh","run","view","--repo",R,"--job",m.group(1),"--log-failed"])
            hits=[l for l in log.splitlines() if re.search(r"FAILED|Error|assert|ERROR",l)]
            for l in hits[-20:]: print("   ", l[-260:])
