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

test('B53 publishes only the current-main Embedded AI SDK static review runtime', () => {
  build();
  const b53 = path.join(out, 'b53');

  for (const relative of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(b53, relative)), true, `b53 missing ${relative}`);
  }

  for (const forbidden of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'evidence', 'screenshots', 'tests', 'ux.html'
  ]) {
    assert.equal(fs.existsSync(path.join(b53, forbidden)), false, `b53 leaked ${forbidden}`);
  }

  const index = fs.readFileSync(path.join(b53, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(b53, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /임베드 AI SDK/);
  assert.match(index, /HUMAN-APPROVED EMBEDDED AI INTEGRATION SPEC/);
  assert.match(index, /HOST AUTHORITY/);
  assert.match(index, /SDK INTEGRATION BOUNDARY/);
  assert.match(index, /ACCEPTED INPUT/);
  assert.match(index, /REJECTED INPUT/);
  assert.match(index, /PERMISSION REQUIRED — NOT GRANTED/);
  assert.match(index, /MODEL\/PROVIDER — NOT CONNECTED/);
  assert.match(index, /INSTALLATION NOT PERFORMED/);
  assert.match(index, /EXECUTION NOT PERFORMED/);
  assert.match(index, /FAIL-CLOSED FALLBACK/);
  assert.match(index, /NO HOST MUTATION/);
  assert.match(index, /HUMAN RELEASE AUTHORITY/);
  assert.match(index, /RELEASE WITHHELD/);
  assert.match(index, /NO LIVE HOST, SDK, MODEL, ACCOUNT, OR CREDENTIAL CONNECTION/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);
});
