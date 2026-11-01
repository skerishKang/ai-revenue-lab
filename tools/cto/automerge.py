import json, subprocess, time, sys
REPO = "skerishKang/ai-revenue-lab"
PR = sys.argv[1]
def run(a): return subprocess.run(a, capture_output=True, text=True)
v = json.loads(run(["gh","pr","view",PR,"--repo",REPO,"--json","isDraft,files,state"]).stdout)
print("state", v["state"], "draft", v["isDraft"], flush=True)
for f in v["files"]: print(" ", f["path"], f"+{f['additions']}/-{f['deletions']}", flush=True)
if v["isDraft"]: run(["gh","pr","ready",PR,"--repo",REPO])
rerun = False
for i in range(70):
    try: data = json.loads(run(["gh","pr","checks",PR,"--repo",REPO,"--json","name,bucket"]).stdout)
    except Exception: time.sleep(30); continue
    pend=[c for c in data if c["bucket"]=="pending"]; fail=[c for c in data if c["bucket"]=="fail"]
    if pend: print(f"[{i}] pending={len(pend)} fail={len(fail)}", flush=True); time.sleep(40); continue
    if fail:
        print("FAILED:", [c["name"] for c in fail], flush=True)
        if not rerun:
            roll = json.loads(run(["gh","pr","view",PR,"--repo",REPO,"--json","statusCheckRollup"]).stdout)["statusCheckRollup"]
            ids = {c["detailsUrl"].split("/actions/runs/")[1].split("/")[0] for c in roll if c.get("conclusion")=="FAILURE" and "/actions/runs/" in (c.get("detailsUrl") or "")}
            for r in ids: print("rerun", r, run(["gh","run","rerun",r,"--repo",REPO,"--failed"]).returncode, flush=True)
            rerun = True; time.sleep(60); continue
        print("RESULT: FAIL", flush=True); sys.exit(1)
    m = run(["gh","pr","merge",PR,"--repo",REPO,"--squash","--delete-branch"])
    print("RESULT:", "MERGED" if m.returncode==0 else "MERGE_ERROR "+m.stderr.strip(), flush=True); sys.exit(m.returncode)
print("RESULT: TIMEOUT"); sys.exit(3)
