import test from "node:test";
import assert from "node:assert/strict";
import worker from "./worker.mjs";

for (const identity of ["A", "B"]) {
  test(`fixture ${identity} exposes only its no-store identity`, async () => {
    const response = worker.fetch(new Request("https://test.invalid/__cutover_trial"), { TRIAL_WORKER: identity });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.deepEqual(await response.json(), { trial: "chat-domain-move", worker: identity });
  });
}

for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
  test(`${method} has no fixture mutation handler`, () => {
    assert.equal(worker.fetch(new Request("https://test.invalid/__cutover_trial", { method }), { TRIAL_WORKER: "A" }).status, 404);
  });
}

test("other paths are absent", () => {
  assert.equal(worker.fetch(new Request("https://test.invalid/"), { TRIAL_WORKER: "A" }).status, 404);
});

test("unknown fixture identity fails closed", () => {
  assert.equal(worker.fetch(new Request("https://test.invalid/__cutover_trial"), { TRIAL_WORKER: "production" }).status, 503);
});
