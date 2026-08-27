const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B41 public card points only to the proven local static Foreign Emergency Assistant route', () => {
  const b41 = businesses.find(item => item.number === 41);
  assert.ok(b41, 'missing B41 public card');
  assert.equal(b41.slug, 'foreign-emergency-assistant');
  assert.equal(b41.title, 'Foreign Emergency Assistant');
  assert.equal(b41.koreanTitle, '외국인 긴급신고 도우미');
  assert.equal(b41.publicStatus, 'PREVIEW');
  assert.equal(b41.routeKind, 'LOCAL_STATIC');
  assert.equal(b41.targetPath, '/b41/');
  assert.equal(b41.sourcePath, 'reference/business-41-foreign-emergency-assistant-v1/');
  assert.match(b41.summary, /합성/);
  assert.match(b41.summary, /사람/);
  assert.match(b41.summary, /공식 긴급서비스/);
  assert.match(b41.summary, /정적/);
  assert.match(b41.summary, /긴급통화/);
  assert.match(b41.summary, /채팅/);
  assert.match(b41.summary, /배차/);
  assert.match(b41.summary, /위치전송/);
  assert.match(b41.summary, /공인 통역/);
  assert.match(b41.summary, /의료/);
  assert.match(b41.summary, /경찰/);
  assert.match(b41.summary, /소방/);
  assert.match(b41.summary, /법률/);
  assert.equal(Object.hasOwn(b41, 'currentPublicUrl'), false);
});
