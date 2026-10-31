import assert from "node:assert/strict";
import a from "./owner-worker-a.mjs";
import b from "./owner-worker-b.mjs";

for (const [worker, expected] of [[a, "trial-a"], [b, "trial-b"]]) {
  const r = await worker.fetch(new Request("https://example.invalid/__cutover_trial"));
  assert.equal(r.status, 200);
  assert.equal(await r.text(), expected);
  assert.match(r.headers.get("cache-control"), /no-store/);
}
console.log("TRIAL_FIXTURES_PASS");
