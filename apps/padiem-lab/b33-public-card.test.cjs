const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B33 public card points only to the proven local static Research Memory route', () => {
  const b33 = businesses.find(item => item.number === 33);
  assert.ok(b33, 'missing B33 public card');
  assert.equal(b33.slug, 'research-memory');
  assert.equal(b33.title, 'Research Memory');
  assert.equal(b33.koreanTitle, '연구 기억실');
  assert.equal(b33.publicStatus, 'PREVIEW');
  assert.equal(b33.routeKind, 'LOCAL_STATIC');
  assert.equal(b33.targetPath, '/b33/');
  assert.equal(b33.sourcePath, 'reference/business-33-research-memory-v1/');
  assert.match(b33.summary, /합성/);
  assert.match(b33.summary, /정적/);
  assert.match(b33.summary, /문헌 검색/);
  assert.match(b33.summary, /PDF/);
  assert.match(b33.summary, /인용 권위/);
  assert.match(b33.summary, /출판/);
  assert.equal(Object.hasOwn(b33, 'currentPublicUrl'), false);
});
