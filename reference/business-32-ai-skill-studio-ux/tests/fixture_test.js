/* Fixture contract test: data/fixture.json is canonical and matches the
 * embedded scripts/fixture.js mirror; content is synthetic-only.
 */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

let failures = 0;

function check(name, fn) {
  try {
    fn();
    console.log('PASS ' + name);
  } catch (error) {
    failures += 1;
    console.error('FAIL ' + name + ': ' + error.message);
  }
}

const root = path.join(__dirname, '..');
const jsonPath = path.join(root, 'data', 'fixture.json');
const raw = fs.readFileSync(jsonPath, 'utf8');
const json = JSON.parse(raw);
const embedded = require('../scripts/fixture.js');

check('fixture.json parses as JSON', function () {
  assert.ok(json && typeof json === 'object');
});

check('embedded fixture matches canonical JSON exactly', function () {
  assert.deepStrictEqual(embedded, json);
});

check('fixture is synthetic only', function () {
  const text = raw;
  assert.ok(!/@[a-z0-9._-]+\.[a-z]{2,}/i.test(text), 'email-like pattern present');
  assert.ok(!/tel:|phone:|주민|resident registration|사업자등록|010-[\d-]+/.test(text), 'personal-identifier pattern present');
  assert.ok(!/https?:\/\/(?!.*pages\.dev)/.test(text), 'unexpected external URL present');
  assert.strictEqual(json.organization.fictional, true);
  assert.strictEqual(json.task.reviewer.fictional, true);
});

check('supplier B has missing warranty and return policy (fixture gap)', function () {
  const b = json.suppliers.find(function (s) {
    return s.id === 'B';
  });
  assert.ok(b, 'supplier B missing');
  assert.strictEqual(b.warrantyMonths, null);
  assert.strictEqual(b.returnPolicy, null);
});

check('no lowest-price-as-best logic exists in the machine', function () {
  const machineSrc = fs.readFileSync(path.join(root, 'scripts', 'machine.js'), 'utf8');
  assert.ok(!/Math\.min|lowestPrice|autoBest|bestPrice/i.test(machineSrc), 'auto best-price logic present');
});

check('assetVersion is a low-entropy descriptive value', function () {
  assert.strictEqual(typeof json.assetVersion, 'string');
  assert.ok(/^b32-ux-static-v1$/.test(json.assetVersion), 'token must be the low-entropy descriptive value');
  assert.ok(/^[a-z0-9-]+$/.test(json.assetVersion), 'token must be lowercase alphanumeric + hyphens only');
  assert.ok(json.assetVersion.length <= 32, 'token must be short');
});

check('fixture.json and fixture.js assetVersion match', function () {
  assert.strictEqual(embedded.assetVersion, json.assetVersion);
  assert.strictEqual(json.assetVersion, 'b32-ux-static-v1');
});

if (failures > 0) {
  console.error(failures + ' fixture failure(s)');
  process.exit(1);
}
console.log('fixture ok');
