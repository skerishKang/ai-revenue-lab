const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B49 route is bounded to the approved current-main Public Data Connector Hub runtime', () => {
  const route = routes.find(candidate => candidate.number === 49);
  assert.ok(route, 'missing B49 route');
  assert.equal(route.route, 'b49');
  assert.equal(route.sourcePath, 'reference/business-49-public-data-connector-hub-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, '공공데이터 커넥터 허브');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /공공데이터 커넥터 허브/);
  assert.match(index, /VISUAL REFERENCE ONLY/);
  assert.match(index, /NO LIVE API, SCRAPING, CREDENTIAL, OR DATA INGESTION/);
  assert.match(index, /CONNECTOR READINESS — NOT CONNECTED/);
  assert.match(index, /MISSING ≠ ZERO/);
  assert.match(index, /NO OFFICIAL ENDORSEMENT/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B49 source missing runtime ${runtime}`);
  }
  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md', 'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B49 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B49 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B49 route includes directory ${repositoryOnly}`);
  }
  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B49 current-main source unexpectedly includes UX #425');
});
