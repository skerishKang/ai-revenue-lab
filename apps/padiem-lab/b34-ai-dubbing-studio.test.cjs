const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B34 route is bounded to the owner-approved current-main AI Dubbing Studio Phase 1 visual reference', () => {
  const route = routes.find(candidate => candidate.number === 34);
  assert.ok(route, 'missing B34 route');
  assert.equal(route.route, 'b34');
  assert.equal(route.sourcePath, 'reference/business-34-ai-dubbing-studio-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, 'AI 더빙 스튜디오');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /BUSINESS 34 · MULTILINGUAL PERFORMANCE DESK/);
  assert.match(index, /AI 더빙 스튜디오/);
  assert.match(index, /SYNTHETIC AUDIOVISUAL SOURCE/);
  assert.match(index, /VISUAL REFERENCE ONLY/);
  assert.match(index, /NO LIVE UPLOAD, GENERATION, OR VOICE CLONING/);
  assert.match(index, /NO REAL-PERSON VOICE CLONING/);
  assert.match(index, /SYNTHETIC VOICE — AUTHORIZED/);
  assert.match(index, /HUMAN-APPROVED LOCALIZED MASTER/);
  assert.match(index, /NOT APPROVED FOR RELEASE/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B34 source missing runtime ${runtime}`);
  }

  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B34 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B34 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B34 route includes directory ${repositoryOnly}`);
  }

  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B34 approved Phase 1 source unexpectedly contains unapproved UX surface');
});
