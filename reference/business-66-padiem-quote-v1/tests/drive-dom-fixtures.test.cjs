"use strict";
const assert = require("node:assert/strict");
const { createStubDocument } = require("./drive-dom-fixtures.cjs");

assert.throws(() => createStubDocument(), /B66_TEST_CONTAINER_ID_REQUIRED/);
assert.throws(() => createStubDocument(""), /B66_TEST_CONTAINER_ID_REQUIRED/);
const one = createStubDocument("drive-one");
const two = createStubDocument("drive-two");
assert.notEqual(one.container, two.container);
assert.equal(one.container.id, "drive-one");
assert.equal(two.container.id, "drive-two");
assert.equal(one.getElementById("drive-one"), one.container);
assert.equal(two.getElementById("drive-one"), null);
let firstCalls = 0, secondCalls = 0;
one.addEventListener("b66:auth-changed", (event) => {
  assert.deepEqual(event.detail, { authenticated: false });
  firstCalls++;
});
two.addEventListener("b66:auth-changed", () => secondCalls++);
one.dispatch("b66:auth-changed", { authenticated: false });
assert.equal(firstCalls, 1);
assert.equal(secondCalls, 0);

const button = one.createElement("button");
let clicks = 0;
button.addEventListener("click", () => clicks++);
button.click();
assert.equal(clicks, 1);
assert.equal(two.container.children.length, 0);
one.container.appendChild(button);
assert.equal(one.container.children.length, 1);
assert.equal(two.container.children.length, 0);
one.container.replaceChildren(one.createElement("span"));
assert.equal(one.container.children.length, 1);

const negative = createStubDocument("drive-one");
assert.notEqual(negative.container, one.container);
assert.equal(negative.container.children.length, 0);
assert.equal(negative.getElementById("unknown"), null);
console.log("B66_DRIVE_DOM_ISOLATION=PASS");
