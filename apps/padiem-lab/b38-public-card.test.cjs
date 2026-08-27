const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B38 public card points only to the proven local static AI Exercise Coach route', () => {
  const b38 = businesses.find(item => item.number === 38);
  assert.ok(b38, 'missing B38 public card');
  assert.equal(b38.slug, 'ai-exercise-coach');
  assert.equal(b38.title, 'AI Exercise Coach');
  assert.equal(b38.koreanTitle, 'AI 운동 코치');
  assert.equal(b38.publicStatus, 'PREVIEW');
  assert.equal(b38.routeKind, 'LOCAL_STATIC');
  assert.equal(b38.targetPath, '/b38/');
  assert.equal(b38.sourcePath, 'reference/business-38-ai-exercise-coach-v1/');
  assert.match(b38.summary, /합성/);
  assert.match(b38.summary, /비진단/);
  assert.match(b38.summary, /사람 검토/);
  assert.match(b38.summary, /정적/);
  assert.match(b38.summary, /의료/);
  assert.match(b38.summary, /재활/);
  assert.match(b38.summary, /자동 자세 인증/);
  assert.match(b38.summary, /실시간 카메라/);
  assert.match(b38.summary, /생체정보/);
  assert.match(b38.summary, /건강데이터/);
  assert.equal(Object.hasOwn(b38, 'currentPublicUrl'), false);
});
