import json, subprocess, sys, time
R = "skerishKang/ai-revenue-lab"; PR = sys.argv[1]; IGN = set(sys.argv[2:])
def run(a): return subprocess.run(a, capture_output=True, text=True)
for i in range(60):
    st = json.loads(run(["gh","pr","view",PR,"-R",R,"--json","state"]).stdout)["state"]
    if st != "OPEN": print("STATE", st); sys.exit(0)
    d = json.loads(run(["gh","pr","checks",PR,"-R",R,"--json","name,bucket"]).stdout or "[]")
    pend = [c for c in d if c["bucket"] == "pending"]; fail = [c["name"] for c in d if c["bucket"] == "fail" and c["name"] not in IGN]
    if pend: time.sleep(40); continue
    if fail: print("REAL FAIL", fail); sys.exit(1)
    m = run(["gh","pr","merge",PR,"-R",R,"--squash","--delete-branch"]); print("MERGE", m.returncode, m.stderr.strip()); sys.exit(m.returncode)
print("TIMEOUT")
