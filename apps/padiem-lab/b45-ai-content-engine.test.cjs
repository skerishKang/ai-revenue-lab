const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B45 route is bounded to the approved current-main AI Content Engine runtime', () => {
  const route = routes.find(candidate => candidate.number === 45);
  assert.ok(route, 'missing B45 route');
  assert.equal(route.route, 'b45');
  assert.equal(route.sourcePath, 'reference/business-45-ai-content-engine-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, 'AI 콘텐츠 엔진');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /AI 콘텐츠 엔진/);
  assert.match(index, /HUMAN-APPROVED CONTENT PRODUCTION KIT/);
  assert.match(index, /SOURCE RIGHTS VERIFIED — SYNTHETIC/);
  assert.match(index, /FACT CHECK NOT PERFORMED/);
  assert.match(index, /UNSUPPORTED CLAIM — HOLD/);
  assert.match(index, /STYLE IMITATION PROHIBITED/);
  assert.match(index, /NOT PUBLISHED/);
  assert.match(index, /NO LIVE GENERATION, CMS, OR PUBLICATION CONNECTION/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B45 source missing runtime ${runtime}`);
  }
  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md', 'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B45 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B45 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B45 route includes directory ${repositoryOnly}`);
  }
  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B45 current-main source unexpectedly includes UX #421');
});
