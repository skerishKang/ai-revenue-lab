"""Fail-closed onboarding lane plan; all tests offline, no provider/Secrets requests."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / ".github" / "scripts" / "b14_model_registration_ci_plan.py"
spec = importlib.util.spec_from_file_location("b14_model_registry_lane", MODULE)
lane = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lane)

BASE = json.loads((ROOT / lane.REGISTRY).read_text(encoding="utf8"))

def appended():
    old = copy.deepcopy(BASE)
    new = copy.deepcopy(old)
    new["providers"]["example-provider"] = {
      "base_origin":"https://example.invalid/api/v1",
      "allowed_hosts":["example.invalid"],
      "credential_source":"platform_secret",
      "credential_binding_name":"PADIEM_EXAMPLE_API_KEY",
      "enabled": True,
    }
    model=copy.deepcopy(new["models"][-1])
    model.update({
        "id":"example-provider/model12",
        "provider_id":"example-provider",
        "upstream_model":"model12",
        "enabled":True
    })
    new["models"].append(model)
    return old,new

def files(*names):
    return [{"filename":n,"status":"modified","patch":"@@ -1,1 +1,2 @@\n keep\n+addition"} for n in names]

class TestRegistryChangeSet(unittest.TestCase):
    def test_only_exact_append_is_allowed(self):
        a,b=appended()
        self.assertTrue(lane.exact_append_only(a,b))
        bad=copy.deepcopy(b)
        bad["models"][0]["upstream_model"]="evil"
        self.assertFalse(lane.exact_append_only(a,bad))
        bad=copy.deepcopy(b)
        bad["models"].insert(0,bad["models"].pop())
        self.assertFalse(lane.exact_append_only(a,bad))
        bad=copy.deepcopy(b)
        bad["groups"]["plus"]=["example-provider/model12"]
        self.assertFalse(lane.exact_append_only(a,bad))
        bad=copy.deepcopy(b)
        bad["models"].append(copy.deepcopy(bad["models"][0]))
        self.assertFalse(lane.exact_append_only(a,bad))
        bad=copy.deepcopy(b)
        bad["providers"]["google"]["base_origin"]="https://evil.invalid"
        self.assertFalse(lane.exact_append_only(a,bad))
        bad=copy.deepcopy(b)
        bad["providers"]["example-provider"]["enabled"]=False
        self.assertFalse(lane.exact_append_only(a,bad))

    def test_paths_only_and_credential_patch_safety(self):
        old,new=appended()
        changed=files(lane.REGISTRY,"apps/korean-ai-platform/tests/test_future_onboarding.py",
                      lane.WRANGLER,lane.WORKER)
        changed[-2]["patch"]='@@ -1,0 +1,4 @@\n+[[secrets_store_secrets]]\n+binding = "PADIEM_EXAMPLE_API_KEY"\n+store_id = "f0b09ca04a7b43248154c773704a5616"\n+secret_name = "PADIEM_EXAMPLE_API_KEY"'
        changed[-1]["patch"]='@@ -1,0 +1,1 @@\n+    "PADIEM_EXAMPLE_API_KEY",'
        self.assertTrue(lane.model_registration_only(changed,old,new))
        self.assertFalse(lane.model_registration_only(changed+[files("apps/padiem-chat/app/router.py")[0]],old,new))
        self.assertFalse(lane.model_registration_only(changed+[files(".github/workflows/validate-b14-alpha.yml")[0]],old,new))
        self.assertFalse(lane.model_registration_only(changed+[files("packages/padiem-ai-core/padiem_ai_core/a.py")[0]],old,new))
        self.assertFalse(lane.model_registration_only([x for x in changed if x["filename"]!=lane.WRANGLER],old,new))
        self.assertFalse(lane.model_registration_only([x for x in changed if x["filename"]!=lane.WORKER],old,new))
        changed[-1]["patch"]='@@ -1 +1 @@\n-    "OLD_MODEL",\n+    "PADIEM_EXAMPLE_API_KEY",'
        self.assertFalse(lane.model_registration_only(changed,old,new))

    def test_wrong_secret_alias_refuses_fast_lane(self):
        old,new=appended()
        changed=files(lane.REGISTRY,lane.WRANGLER,lane.WORKER)
        changed[1]["patch"]='@@ -1,0 +1,4 @@\n+[[secrets_store_secrets]]\n+binding = "PADIEM_OTHER_API_KEY"\n+store_id = "f0b09ca04a7b43248154c773704a5616"\n+secret_name = "PADIEM_OTHER_API_KEY"'
        changed[2]["patch"]='@@ -1,0 +1,1 @@\n+    "PADIEM_EXAMPLE_API_KEY",'
        self.assertFalse(lane.model_registration_only(changed,old,new))

    def test_runtime_and_secrets_patch_cannot_fast_path(self):
        self.assertFalse(lane.additions_only(
            '@@ -1 +1 @@\n-foo\n+    "PADIEM_EXAMPLE_API_KEY",',lane.WORKER))
        self.assertFalse(lane.additions_only(
            '@@ -1,0 +1 @@\n+    key = await env.PADIEM_EXAMPLE_API_KEY.get()',lane.WORKER))
        self.assertFalse(lane.additions_only(
            '@@ -1,0 +1 @@\n+route = "unapproved"',lane.WRANGLER))
        self.assertFalse(lane.additions_only(None,lane.WRANGLER))
        self.assertFalse(lane.allowed_file("apps/korean-ai-platform/app/pilot/platform.py"))
        self.assertFalse(lane.allowed_file("apps/padiem-chat/worker.py"))

    def test_fast_path_requires_registry_append_and_exact_changed_set(self):
        a,b=appended()
        self.assertFalse(lane.model_registration_only(files("docs/models/final-evaluation/B14_FOO.md"),a,b))
        self.assertFalse(lane.model_registration_only(files(lane.REGISTRY,lane.REGISTRY),a,b))
        self.assertFalse(lane.model_registration_only([{"filename":lane.REGISTRY,"status":"removed"}],a,b))
        self.assertFalse(lane.model_registration_only(files(lane.REGISTRY),a,b))
        self.assertFalse(lane.model_registration_only(files(lane.REGISTRY),a,a))
        self.assertFalse(lane.model_registration_only(files(lane.REGISTRY)*101,a,b))

    def test_existing_provider_can_append_without_new_secret(self):
        a,b=appended()
        b["providers"].pop("example-provider")
        b["models"][-1]["provider_id"]="google"
        b["models"][-1]["id"]="google/test-new-manual-model"
        self.assertTrue(lane.model_registration_only(files(lane.REGISTRY),a,b))

if __name__ == "__main__":
    unittest.main()
