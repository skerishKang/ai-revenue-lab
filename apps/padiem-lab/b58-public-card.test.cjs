const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B58 public card points only to the proven local static route', () => {
  const b58 = businesses.find(item => item.number === 58);
  assert.ok(b58, 'missing B58 public card');
  assert.equal(b58.slug, 'personal-writing-voice-studio');
  assert.equal(b58.title, 'Personal Writing Voice Studio');
  assert.equal(b58.koreanTitle, '개인 문체 스튜디오');
  assert.equal(b58.publicStatus, 'PREVIEW');
  assert.equal(b58.routeKind, 'LOCAL_STATIC');
  assert.equal(b58.targetPath, '/b58/');
  assert.equal(b58.sourcePath, 'reference/business-58-personal-writing-voice-studio-v1/');
  assert.equal(Object.hasOwn(b58, 'currentPublicUrl'), false);
});
