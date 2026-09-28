import pathlib, subprocess

for name in ["_cleanup.py", "_fix.py", "_lsf.txt"]:
    p = pathlib.Path(name)
    if p.exists():
        p.unlink()
        print("removed", name)

subprocess.run(["git", "add", "-A"], check=True)
r = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, encoding="utf-8")
print("STATUS:", r.stdout.strip())
r = subprocess.run(["git", "commit", "-m",
    "chore(#3199): remove temporary build/cleanup scripts from the repository",
    "-m", "The S0-B gate YAML and source-contract tests were composed through throwaway scripts; none of them are part of the gate or the source contract."],
    capture_output=True, text=True, encoding="utf-8")
print("COMMIT:", r.stdout.strip() or r.stderr.strip())
r = subprocess.run(["git", "push"], capture_output=True, text=True, encoding="utf-8")
print("PUSH:", (r.stdout + r.stderr).strip())
r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8")
print("HEAD:", r.stdout.strip())
r = subprocess.run(["git", "ls-files"], capture_output=True, text=True, encoding="utf-8")
print("TEMP_STILL_TRACKED:", [f for f in r.stdout.splitlines() if f.startswith("_")])