import pathlib, subprocess, sys

for name in ["_inspect.py", "_s0b_build.py", "_run_tests.py"]:
    p = pathlib.Path(name)
    if p.exists():
        p.unlink()
        print("removed", name)

# Stage deletion
subprocess.run(["git", "add", "-A"], cwd=".")
# Amend the last commit to remove the temp files
r = subprocess.run(["git", "commit", "--amend", "--no-edit", "-m",
    "feat(#3199): S0-B P01 Engine service binding gate + source-contract regressions",
    "-m", "New b62-p01-engine-service-binding-gate.yml mirroring the proven binding-mutation safety contract of b62-control-plane-identity-gate with fixed authority B62_WORKER=padiem-chat / ENGINE_WORKER=padiem-ai-engine / ENGINE_BINDING=P01_ENGINE_SERVICE. Modes: repository_preflight, cloudflare_readonly (GET-only, canonical served-version resolver, 5 classification states), activate_p01_engine_binding (settings PATCH only), rollback_p01_engine_binding (exact single-binding removal). New source-contract tests: gate provenance markers, engine D1 0008 contract, binding classification absent/present_expected/wrong_target/wrong_type/duplicate, activation preserves unrelated, rollback removes only P01, source-etag + public-topology preservation, settings-only mutation + bounded error body, P01 not pre-declared. Hard locks preserved: SECOND_PRODUCTION_CONFIG_GENERATOR=0, no new binding name, no second deploy path, no D1 DB, no production mutation. Refs #3199 Related PR #3200"],
    cwd=".")
print("amend rc", r.returncode)
# force-push the amended commit
r = subprocess.run(["git", "push", "--force-with-lease"], cwd=".")
print("push rc", r.returncode)
subprocess.run(["git", "rev-parse", "HEAD"], cwd=".")
