const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');

function runFile(context, name) {
  const source = fs.readFileSync(path.join(root, name), 'utf8');
  new vm.Script(source, { filename: name }).runInContext(context);
}

const windowObject = {};
const context = vm.createContext({
  window: windowObject,
  globalThis: windowObject,
  console,
  Array,
  Object,
  String,
  Number,
  Boolean,
  Math,
  JSON,
  Map,
  Set,
  RegExp,
  Date,
  Error,
  Symbol,
});

runFile(context, 'business-identity-core.js');
runFile(context, 'business-manifest.js');
runFile(context, 'businesses.js');
runFile(context, 'review-surfaces-396.js');

const businesses = windowObject.ARL_BUSINESSES;
const review = windowObject.ARL_REVIEW_SURFACES;

assert.equal(businesses.length, 58, 'B1-55 plus B57-59 should produce 58 Business rows');
assert.equal(new Set(businesses.map((b) => b.number)).size, 58, 'Business numbers must be unique');
assert.equal(businesses.some((b) => b.number === 56), false, 'B56 is an intentional gap');
assert.equal(Math.max(...businesses.map((b) => b.number)), 59, 'B59 must be represented');

const b38 = businesses.find((b) => b.number === 38);
assert.equal(b38.title, 'AI Exercise Coach');
assert.equal(b38.koreanTitle, 'AI 운동 코치');
assert.equal(b38.workspace, 'reference/business-38-ai-exercise-coach-v1/');

const b54 = businesses.find((b) => b.number === 54);
assert.equal(b54.title, 'Korean AI Code Agent');
assert.equal(b54.koreanTitle, '한국형 AI 코드 에이전트');
assert.equal(b54.workspace, 'apps/korean-ai-code-agent/');
assert.equal(b54.reviewSurface.kind, 'cli-tui');
assert.equal(b54.reviewSurface.status, 'AVAILABLE_NON_WEB');
assert.equal(b54.reviewSurface.pr, 432);
assert.equal(b54.surfaceUrl, 'https://github.com/skerishKang/ai-revenue-lab/pull/432');

for (const number of [57, 58, 59]) {
  assert.ok(businesses.find((b) => b.number === number), `B${number} must exist`);
}

const entries = Object.values(review);
const webReviews = entries.filter((entry) => entry.kind === 'web-review');
assert.equal(webReviews.length, 39, 'Exactly 39 web review surfaces are prepared');
assert.equal(entries.length, 40, '39 web review targets plus the B54 CLI/TUI surface');

for (const entry of webReviews) {
  assert.equal(entry.status, 'CLOUDFLARE_REVIEW_DEPLOY_PENDING');
  assert.match(entry.exactHead, /^[0-9a-f]{40}$/);
  assert.match(entry.plannedUrl, /^https:\/\/arl-review-b\d{2}-[a-z0-9-]+\.pages\.dev\/(ux|index)\.html$/);
}

for (const business of businesses) {
  if (!business.reviewSurface || business.reviewSurface.kind !== 'web-review') continue;
  assert.notEqual(
    business.surfaceUrl,
    business.reviewSurface.plannedUrl,
    `B${business.number} must not expose an unverified review URL as a live service`,
  );
}

assert.equal(review[6].entry, 'index.html');
assert.equal(review[32].entry, 'index.html');
assert.equal(review[35].entry, 'index.html');
assert.equal(review[59].entry, 'index.html');

console.log('PORTFOLIO_REVIEW_SURFACES_396_PASS');
