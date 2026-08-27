const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B55 public card points only to the proven local static route', () => {
  const b55 = businesses.find(item => item.number === 55);
  assert.ok(b55, 'missing B55 public card');
  assert.equal(b55.slug, 'local-ai-fleet');
  assert.equal(b55.title, 'Local AI Fleet');
  assert.equal(b55.koreanTitle, '로컬 AI 플릿');
  assert.equal(b55.publicStatus, 'PREVIEW');
  assert.equal(b55.routeKind, 'LOCAL_STATIC');
  assert.equal(b55.targetPath, '/b55/');
  assert.equal(b55.sourcePath, 'reference/business-55-local-ai-fleet-v1/');
  assert.equal(Object.hasOwn(b55, 'currentPublicUrl'), false);
});
