const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B40 public card points only to the proven local static Emergency Urgency AI route', () => {
  const b40 = businesses.find(item => item.number === 40);
  assert.ok(b40, 'missing B40 public card');
  assert.equal(b40.slug, 'emergency-urgency-ai');
  assert.equal(b40.title, 'Emergency Urgency AI');
  assert.equal(b40.koreanTitle, '긴급도 판단 AI');
  assert.equal(b40.publicStatus, 'PREVIEW');
  assert.equal(b40.routeKind, 'LOCAL_STATIC');
  assert.equal(b40.targetPath, '/b40/');
  assert.equal(b40.sourcePath, 'reference/business-40-emergency-urgency-ai-v1/');
  assert.match(b40.summary, /합성/);
  assert.match(b40.summary, /사람/);
  assert.match(b40.summary, /정적/);
  assert.match(b40.summary, /자동 긴급도 판단/);
  assert.match(b40.summary, /배차/);
  assert.match(b40.summary, /자원배분/);
  assert.match(b40.summary, /의료진단/);
  assert.match(b40.summary, /위협예측/);
  assert.match(b40.summary, /실시간 신고/);
  assert.match(b40.summary, /위치/);
  assert.match(b40.summary, /센서/);
  assert.match(b40.summary, /건강데이터/);
  assert.equal(Object.hasOwn(b40, 'currentPublicUrl'), false);
});
