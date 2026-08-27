const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B53 public card points only to the proven local static route', () => {
  const b53 = businesses.find(item => item.number === 53);
  assert.ok(b53, 'missing B53 public card');
  assert.equal(b53.slug, 'embedded-ai-sdk');
  assert.equal(b53.title, 'Embedded AI SDK');
  assert.equal(b53.koreanTitle, '임베드 AI SDK');
  assert.equal(b53.publicStatus, 'PREVIEW');
  assert.equal(b53.routeKind, 'LOCAL_STATIC');
  assert.equal(b53.targetPath, '/b53/');
  assert.equal(b53.sourcePath, 'reference/business-53-embedded-ai-sdk-v1/');
  assert.equal(Object.hasOwn(b53, 'currentPublicUrl'), false);
});
