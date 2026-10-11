const assert = require('node:assert/strict');
const test = require('node:test');
const businesses = require('./public-businesses.js');

test('B25 public card points only to the proven external Love Matchmaking production URL', () => {
  const b25 = businesses.find(item => item.number === 25);
  assert.ok(b25, 'missing B25 public card');
  assert.equal(b25.slug, 'love-matchmaking-resonance');
  assert.equal(b25.title, 'Love Matchmaking · Resonance');
  assert.equal(b25.koreanTitle, '공명 · Resonance');
  assert.equal(b25.publicStatus, 'LIVE');
  assert.equal(b25.routeKind, 'EXTERNAL_RUNTIME');
  assert.equal(b25.targetPath, '/b25/');
  assert.equal(b25.currentPublicUrl, 'https://3287293c.401-love-match-making.pages.dev/');
  assert.equal(Object.hasOwn(b25, 'sourcePath'), false);
});
