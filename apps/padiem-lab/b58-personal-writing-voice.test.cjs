const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B58 route is bounded to the approved current-main Personal Writing Voice Studio runtime', () => {
  const route = routes.find(candidate => candidate.number === 58);
  assert.ok(route, 'missing B58 route');
  assert.equal(route.route, 'b58');
  assert.equal(route.sourcePath, 'reference/business-58-personal-writing-voice-studio-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, '나의 문체 스튜디오');
  assert.deepEqual(route.includeFiles, ['index.html', 'styles.css', 'app.js']);
  assert.deepEqual(route.includeDirs, []);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const app = fs.readFileSync(path.join(source, 'app.js'), 'utf8');

  assert.match(index, /나의 문체 스튜디오/);
  assert.match(index, /합성 데모/);
  assert.match(index, /업로드는 권리 증명이 아닙니다/);
  assert.match(index, /공유 모델 학습 OFF/);
  assert.match(index, /NOT AUTHOR-APPROVED/);
  assert.match(index, /REJECTED BY AUTHOR/);
  assert.doesNotMatch(app, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'styles.css', 'app.js']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B58 source missing runtime ${runtime}`);
  }
  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'RIGHTS_AND_CONSENT_SPEC.md', 'VOICE_PROFILE_SPEC.md', 'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B58 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B58 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B58 route includes directory ${repositoryOnly}`);
  }
  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B58 current-main source unexpectedly includes UX #431');
});
