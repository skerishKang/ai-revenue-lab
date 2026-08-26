const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const test = require('node:test');

const repoRoot = path.resolve(__dirname, '..', '..');
const out = path.join(repoRoot, 'dist', 'padiem-lab');

function build() {
  execFileSync(process.execPath, [path.join(__dirname, 'build-site.cjs')], {
    cwd: repoRoot,
    stdio: 'pipe'
  });
}

test('B52 publishes only the current-main human-governed scheduled-operations runtime', () => {
  build();
  const b52 = path.join(out, 'b52');
  for (const relative of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(b52, relative)), true, `b52 missing ${relative}`);
  }
  for (const forbidden of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'evidence', 'screenshots', 'tests', 'ux.html'
  ]) {
    assert.equal(fs.existsSync(path.join(b52, forbidden)), false, `b52 leaked ${forbidden}`);
  }

  const index = fs.readFileSync(path.join(b52, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(b52, 'scripts', 'review.js'), 'utf8');
  assert.match(index, /예약형 AI 운영/);
  assert.match(index, /NOT SCHEDULED/);
  assert.match(index, /NOT EXECUTED/);
  assert.match(index, /CONDITION NOT MET/);
  assert.match(index, /SKIPPED — NOT PASSED/);
  assert.match(index, /NOTIFICATION SUPPRESSED/);
  assert.match(index, /DUPLICATE RUN PROHIBITED/);
  assert.match(index, /PAUSE AUTHORITY — HUMAN ONLY/);
  assert.match(index, /EXECUTION WITHHELD/);
  assert.match(index, /HUMAN-APPROVED SCHEDULED OPERATION RUNBOOK/);
  assert.match(index, /NO LIVE SCHEDULING, BACKGROUND EXECUTION, ACCOUNT ACCESS, OR NOTIFICATION/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);
});
