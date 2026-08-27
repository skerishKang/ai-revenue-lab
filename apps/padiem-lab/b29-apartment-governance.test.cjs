const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B29 route is bounded to the approved current-main Apartment Governance visual reference', () => {
  const route = routes.find(candidate => candidate.number === 29);
  assert.ok(route, 'missing B29 route');
  assert.equal(route.route, 'b29');
  assert.equal(route.sourcePath, 'reference/business-29-apartment-governance-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, '방림명지로드힐 우리단지 운영실');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /방림명지로드힐 우리단지 운영실/);
  assert.match(index, /VISUAL REFERENCE ONLY/);
  assert.match(index, /NOT LEGAL ADVICE/);
  assert.match(index, /전자투표·계약·결제 기능은 현재 데모 범위 아님/);
  assert.match(index, /NO REAL VOTING/);
  assert.match(index, /NO IDENTITY VERIFICATION/);
  assert.match(index, /NO TALLYING/);
  assert.match(index, /UI_ONLY/);
  assert.match(index, /UX_NOT_STARTED/);
  assert.match(index, /BACKEND_FROZEN/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B29 source missing runtime ${runtime}`);
  }

  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B29 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B29 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B29 route includes directory ${repositoryOnly}`);
  }

  assert.notEqual(route.sourcePath, 'reference/business-29-apartment-governance-tutorial-v1');
  assert.notEqual(route.sourcePath, 'reference/business-29-apartment-governance-ux');
});
