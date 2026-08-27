const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B29 public card points only to the proven local static route', () => {
  const b29 = businesses.find(item => item.number === 29);
  assert.ok(b29, 'missing B29 public card');
  assert.equal(b29.slug, 'apartment-governance');
  assert.equal(b29.title, 'Apartment Governance');
  assert.equal(b29.koreanTitle, '우리단지 운영실');
  assert.equal(b29.publicStatus, 'PREVIEW');
  assert.equal(b29.routeKind, 'LOCAL_STATIC');
  assert.equal(b29.targetPath, '/b29/');
  assert.equal(b29.sourcePath, 'reference/business-29-apartment-governance-v1/');
  assert.match(b29.summary, /정적/);
  assert.match(b29.summary, /법률/);
  assert.match(b29.summary, /전자투표/);
  assert.match(b29.summary, /계약/);
  assert.equal(Object.hasOwn(b29, 'currentPublicUrl'), false);
});
