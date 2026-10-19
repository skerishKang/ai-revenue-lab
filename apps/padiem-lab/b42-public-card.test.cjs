const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B42 public card points only to the proven local static AI Development Control Tower route', () => {
  const b42 = businesses.find(item => item.number === 42);
  assert.ok(b42, 'missing B42 public card');
  assert.equal(b42.slug, 'ai-development-control-tower');
  assert.equal(b42.title, 'AI Development Control Tower');
  assert.equal(b42.koreanTitle, 'AI 개발 관제탑');
  assert.equal(b42.publicStatus, 'PREVIEW');
  assert.equal(b42.routeKind, 'LOCAL_STATIC');
  assert.equal(b42.targetPath, '/b42/');
  assert.equal(b42.sourcePath, 'reference/business-42-ai-development-control-tower-v1/');
  assert.match(b42.summary, /합성/);
  assert.match(b42.summary, /정적/);
  assert.match(b42.summary, /Git/);
  assert.match(b42.summary, /CI/);
  assert.match(b42.summary, /merge/);
  assert.match(b42.summary, /배포/);
  assert.match(b42.summary, /worker/);
  assert.match(b42.summary, /서버/);
  assert.equal(Object.hasOwn(b42, 'currentPublicUrl'), false);
});
