const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B41 route is bounded to the owner-approved current-main Foreign Emergency Assistant Phase 1 visual reference', () => {
  const route = routes.find(candidate => candidate.number === 41);
  assert.ok(route, 'missing B41 route');
  assert.equal(route.route, 'b41');
  assert.equal(route.sourcePath, 'reference/business-41-foreign-emergency-assistant-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, '외국인 긴급신고 도우미');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /BUSINESS 41 · UI_ONLY · MULTILINGUAL PUBLIC-SERVICE REFERENCE/);
  assert.match(index, /SYNTHETIC EMERGENCY-REPORTING SCENARIO/);
  assert.match(index, /FOREIGN-LANGUAGE USER — FICTIONAL/);
  assert.match(index, /REPORTING PREPARATION ONLY/);
  assert.match(index, /VISUAL REFERENCE ONLY/);
  assert.match(index, /LANGUAGE ASSISTANCE — NOT CERTIFIED INTERPRETATION/);
  assert.match(index, /USER STATEMENT — UNVERIFIED/);
  assert.match(index, /OBSERVABLE FACT — SYNTHETIC/);
  assert.match(index, /UNKNOWN \/ UNCONFIRMED/);
  assert.match(index, /LOCATION — PARTIALLY KNOWN/);
  assert.match(index, /LOCATION — NOT LIVE OR VERIFIED/);
  assert.match(index, /IMMEDIATE NEED — USER REPORTED/);
  assert.match(index, /NO URGENCY OR THREAT CLASSIFICATION/);
  assert.match(index, /NO MEDICAL, POLICE, FIRE, OR LEGAL ADVICE/);
  assert.match(index, /NO LIVE CALL, CHAT, LOCATION, OR DISPATCH/);
  assert.match(index, /OFFICIAL EMERGENCY-SERVICE HANDOFF REQUIRED/);
  assert.match(index, /HUMAN-READY EMERGENCY REPORTING BRIEF/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B41 source missing runtime ${runtime}`);
  }

  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B41 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B41 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B41 route includes directory ${repositoryOnly}`);
  }

  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B41 approved Phase 1 source unexpectedly contains the separately stacked UX surface');
});
