const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');
const out = path.join(repoRoot, 'dist', 'padiem-lab');

function build() {
  execFileSync(process.execPath, [path.join(__dirname, 'build-site.cjs')], {
    cwd: repoRoot,
    stdio: 'pipe'
  });
}

test('B42 publishes only the approved Phase 1 development-control visual reference', () => {
  const route = routes.find(candidate => candidate.number === 42);
  assert.ok(route, 'missing B42 route');
  assert.equal(route.route, 'b42');
  assert.equal(route.sourcePath, 'reference/business-42-ai-development-control-tower-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, 'AI 개발 관제실');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'approved Phase 1 source unexpectedly contains ux.html');
  for (const repositoryOnly of ['README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md', 'evidence', 'tests']) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `missing approved repository-only source ${repositoryOnly}`);
  }

  build();
  const b42 = path.join(out, 'b42');
  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(b42, runtime)), true, `b42 missing ${runtime}`);
  }
  for (const forbidden of ['README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md', 'evidence', 'tests', 'ux.html']) {
    assert.equal(fs.existsSync(path.join(b42, forbidden)), false, `b42 leaked ${forbidden}`);
  }

  const index = fs.readFileSync(path.join(b42, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(b42, 'scripts', 'review.js'), 'utf8');
  assert.match(index, /AI 개발 관제실/);
  assert.match(index, /VISUAL REFERENCE ONLY/);
  assert.match(index, /SYNTHETIC SOFTWARE PROJECT/);
  assert.match(index, /NO LIVE REPOSITORY, CI, MERGE, OR DEPLOYMENT CONNECTION/);
  assert.match(index, /IMPLEMENTATION REPORT — UNVERIFIED/);
  assert.match(index, /INDEPENDENT EVIDENCE/);
  assert.match(index, /STALE EVIDENCE — DO NOT USE/);
  assert.match(index, /HUMAN REVIEWER/);
  assert.match(index, /UX NOT AUTHORIZED/);
  assert.match(index, /BACKEND FROZEN/);
  assert.match(index, /MERGEABLE ≠ MERGE AUTHORIZED/);
  assert.match(index, /DEPLOYMENT AUTHORIZED — NOT EXECUTED/);
  assert.match(index, /HUMAN-APPROVED DEVELOPMENT CONTROL RECORD/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);
});
