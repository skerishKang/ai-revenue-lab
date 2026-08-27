const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');
const out = path.join(repoRoot, 'dist', 'padiem-lab', 'b57');

function build() {
  execFileSync(process.execPath, [path.join(__dirname, 'build-site.cjs')], {
    cwd: repoRoot,
    stdio: 'pipe'
  });
}

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
});

test('B57 aggregate artifact publishes runtime only and excludes rights/review repository material', () => {
  build();
  for (const relative of ['index.html', 'assets/rose-mark.svg', 'scripts/review.js', 'styles/main.css']) {
    assert.equal(fs.existsSync(path.join(out, relative)), true, `b57 missing ${relative}`);
  }
  for (const forbidden of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'RIGHTS_AND_SOURCES.md', 'evidence', 'ux.html'
  ]) {
    assert.equal(fs.existsSync(path.join(out, forbidden)), false, `b57 leaked ${forbidden}`);
  }
});
