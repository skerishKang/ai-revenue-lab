const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B52 public card points only to the staged local static route', () => {
  const b52 = businesses.find(item => item.number === 52);
  assert.ok(b52, 'missing B52 public card');
  assert.equal(b52.slug, 'scheduled-agent-operations');
  assert.equal(b52.title, 'Scheduled Agent Operations');
  assert.equal(b52.koreanTitle, '예약형 AI 운영');
  assert.equal(b52.publicStatus, 'PREVIEW');
  assert.equal(b52.routeKind, 'LOCAL_STATIC');
  assert.equal(b52.targetPath, '/b52/');
  assert.equal(b52.sourcePath, 'reference/business-52-scheduled-agent-operations-v1/');
  assert.equal(Object.hasOwn(b52, 'currentPublicUrl'), false);
});
