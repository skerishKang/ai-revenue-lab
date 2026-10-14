"""B66 protected D1 release: source-only tests, never contact Cloudflare."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
target = HERE / "scripts" / "b62_b66_d1_041_042_044_release.py"
spec = importlib.util.spec_from_file_location("b66_release", target)
import sys
sys.path.insert(0, str(HERE / "scripts"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def check_plan():
    assert release.plan("pre_041", "pre_044") == ["041", "042", "044"]
    assert release.plan("pre_042", "pre_044") == ["042", "044"]
    assert release.plan("exact", "pre_044") == ["044"]
    assert release.plan("exact", "exact") == []
    for a, b in (("missing", "pre_044"), ("drift", "pre_044"),
                 ("pre_041", "exact"), ("pre_042", "exact"),
                 ("exact", "missing"), ("exact", "drift")):
        try:
            release.plan(a, b)
        except release.ReleaseRefusal:
            pass
        else:
            raise AssertionError("unsafe release state accepted: " + a + " " + b)


def check_readonly_behavior():
    class Stub:
        def __init__(self):
            self.calls = []
        def db_id(self):
            self.calls.append("binding")
            return "synthetic"
        def query(self, db, sql):
            self.calls.append("read_schema")
            return {"success": True, "result": []}
        def recovery(self, db):
            self.calls.append("read_bookmark")
    original = release.states
    try:
        release.states = lambda _a, _b: ("pre_041", "pre_044")
        stub = Stub()
        release.execute("readonly", "", stub)
        assert stub.calls == ["binding", "read_bookmark"]
        try:
            release.execute("apply", "wrong phrase", stub)
        except release.ReleaseRefusal:
            pass
        else:
            raise AssertionError("unauthorized apply accepted")
        assert stub.calls == ["binding", "read_bookmark"]
    finally:
        release.states = original


def check_static_gates():
    wf = (HERE / "workflows" / "b62-b66-d1-041-042-044-release.yml").read_text(encoding="utf-8")
    source = target.read_text(encoding="utf-8")
    assert "environment: production" in wf
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in wf
    assert "APPLY_B66_D1_041_042_044_FROM_EXACT_MAIN" in wf
    assert "persist-credentials: false" in wf
    assert "b62_b66_d1_041_042_044_release.py readonly" in wf
    assert "b62_b66_d1_041_042_044_release.py apply" in wf
    assert 'if mode == "readonly":' in source
    assert 'client.query(db, sql)' in source
    assert 'client.recovery(db)' in source
    assert 'if client.db_id() != db:' in source
    assert "FROM USERS" not in source.upper() and "FROM MESSAGES" not in source.upper()
    for name in ("041", "042", "044"):
        assert release.FIXED_SQL[name].exists()
    for path in (target, HERE / "scripts" / "b62_d1_migration_044_schema.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


if __name__ == "__main__":
    check_plan()
    check_readonly_behavior()
    check_static_gates()
    print("B66_D1_RELEASE_SOURCE_TESTS=PASS")
    print("PRODUCTION_MUTATION=0")
