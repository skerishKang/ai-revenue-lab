const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B57 route is bounded to the approved current-main Classic Literature Translation runtime', () => {
  const route = routes.find(candidate => candidate.number === 57);
  assert.ok(route, 'missing B57 route');
  assert.equal(route.route, 'b57');
  assert.equal(route.sourcePath, 'reference/business-57-classic-literature-translation-studio-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, '고전문학 번역실');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /Classic Literature Translation Studio/);
  assert.match(index, /PUBLIC-DOMAIN FIXTURES ONLY/);
  assert.match(index, /원문: 퍼블릭도메인 확인/);
  assert.match(index, /한국어: 신규 작성 데모/);
  assert.match(index, /현대 독해판은 원전 보존판을 대체하지 않습니다/);
  assert.match(index, /Human review pending/);
  assert.match(index, /공유 모델 학습/);
  assert.match(index, /기본값 금지/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['assets/rose-mark.svg', 'scripts/review.js', 'styles/main.css']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B57 source missing runtime ${runtime}`);
  }
  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'RIGHTS_AND_SOURCES.md', 'evidence'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B57 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B57 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B57 route includes directory ${repositoryOnly}`);
  }
  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B57 current-main source unexpectedly includes UX #430');
});
