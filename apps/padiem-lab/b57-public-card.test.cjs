const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B57 public card points only to the proven local static route', () => {
  const b57 = businesses.find(item => item.number === 57);
  assert.ok(b57, 'missing B57 public card');
  assert.equal(b57.slug, 'classic-literature-translation-studio');
  assert.equal(b57.title, 'Classic Literature Translation Studio');
  assert.equal(b57.koreanTitle, '고전문학 번역실');
  assert.equal(b57.publicStatus, 'PREVIEW');
  assert.equal(b57.routeKind, 'LOCAL_STATIC');
  assert.equal(b57.targetPath, '/b57/');
  assert.equal(b57.sourcePath, 'reference/business-57-classic-literature-translation-studio-v1/');
  assert.equal(Object.hasOwn(b57, 'currentPublicUrl'), false);
});
