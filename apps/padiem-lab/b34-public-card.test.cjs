const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B34 public card points only to the proven local static AI Dubbing Studio route', () => {
  const b34 = businesses.find(item => item.number === 34);
  assert.ok(b34, 'missing B34 public card');
  assert.equal(b34.slug, 'ai-dubbing-studio');
  assert.equal(b34.title, 'AI Dubbing Studio');
  assert.equal(b34.koreanTitle, 'AI 더빙 스튜디오');
  assert.equal(b34.publicStatus, 'PREVIEW');
  assert.equal(b34.routeKind, 'LOCAL_STATIC');
  assert.equal(b34.targetPath, '/b34/');
  assert.equal(b34.sourcePath, 'reference/business-34-ai-dubbing-studio-v1/');
  assert.match(b34.summary, /합성/);
  assert.match(b34.summary, /권리확인/);
  assert.match(b34.summary, /정적/);
  assert.match(b34.summary, /실인물 음성복제/);
  assert.match(b34.summary, /업로드/);
  assert.match(b34.summary, /음성 생성/);
  assert.match(b34.summary, /파일 출력/);
  assert.equal(Object.hasOwn(b34, 'currentPublicUrl'), false);
});
