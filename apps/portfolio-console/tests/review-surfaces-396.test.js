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

const verified = webReviews.filter((entry) => entry.status === 'CLOUDFLARE_REVIEW_VERIFIED');
assert.equal(verified.length, 39, 'All 39 numbered web surfaces are byte-verified and live');
assert.equal(webReviews.some((entry) => entry.status === 'CLOUDFLARE_REVIEW_DEPLOY_PENDING'), false);

const finalReviewed = new Map([
  [6, ['ai-revenue-final-review-b06', '888e91e45c9d02d214cd8a7fef6b710586d09f4b02e07ae3f82e717ed02c634e']],
  [7, ['ai-revenue-final-review-b07', 'b4c055f23e1b9b488ed2d6dd2b31d8ef5c0451de71bcf4851ff5982766463d89']],
  [8, ['ai-revenue-final-review-b08', 'fce0b556f32ec27787cad9f1827e4daa7027ad538b7cebb75dcc967df5334919']],
  [9, ['ai-revenue-final-review-b09', '81ee4dfe890f04631b2ec3fffae6d4f450ce21d9913917baf2522aac0d4e49db']],
  [11, ['ai-revenue-final-review-b11', '416b8c8c85014195912554b5a327c3975d4c2844841bf95248eb5003bc83a358']],
]);

for (const entry of webReviews) {
  assert.match(entry.exactHead, /^[0-9a-f]{40}$/);
  // Numbered projects keep the historical NN-slug contract; independently
  // reviewed 2026-08-15 final surfaces use dedicated ai-revenue-final(-review)-bNN pages.
  const final = finalReviewed.get(entry.number);
  if (final) {
    assert.equal(entry.project, final[0]);
    assert.equal(entry.finalReviewDate, '2026-08-15');
    assert.equal(entry.finalReviewSha256, final[1]);
  } else {
    assert.match(entry.project, /^\d{2}-[a-z0-9-]+$/);
    assert.equal(entry.finalReviewDate, null);
    assert.equal(entry.finalReviewSha256, null);
  }
  assert.equal(entry.entry, 'index.html');
  assert.equal(entry.plannedUrl, `https://${entry.project}.pages.dev/`);
  assert.equal(entry.surfaceUrl, entry.plannedUrl);
  assert.doesNotMatch(entry.surfaceUrl, /arl-review/);
}

for (const business of businesses) {
  if (!business.reviewSurface || business.reviewSurface.kind !== 'web-review') continue;
  assert.equal(business.reviewSurface.status, 'CLOUDFLARE_REVIEW_VERIFIED');
  assert.equal(business.surfaceUrl, business.reviewSurface.surfaceUrl);
}

for (const number of [6, 32, 35, 59]) {
  assert.equal(review[number].entry, 'index.html');
}

assert.equal(review[6].surfaceUrl, 'https://ai-revenue-final-review-b06.pages.dev/');
assert.equal(review[7].surfaceUrl, 'https://ai-revenue-final-review-b07.pages.dev/');
assert.equal(review[8].surfaceUrl, 'https://ai-revenue-final-review-b08.pages.dev/');
assert.equal(review[9].surfaceUrl, 'https://ai-revenue-final-review-b09.pages.dev/');
assert.equal(review[11].surfaceUrl, 'https://ai-revenue-final-review-b11.pages.dev/');
assert.equal(review[32].surfaceUrl, 'https://32-ai-skill-studio.pages.dev/');
assert.equal(review[35].surfaceUrl, 'https://35-ai-media-education-dx.pages.dev/');
assert.equal(review[59].surfaceUrl, 'https://59-living-archive.pages.dev/');

const indexHtml = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const businessesPos = indexHtml.indexOf('./businesses.js');
const reviewPos = indexHtml.indexOf('./review-surfaces-396.js');
const appPos = indexHtml.indexOf('./app.js');
assert.ok(businessesPos >= 0, 'Portfolio index must load businesses.js');
assert.ok(reviewPos > businessesPos, 'review-surfaces-396.js must load after businesses.js so it can overlay surfaceUrl');
assert.ok(appPos > reviewPos, 'review-surfaces-396.js must load before app.js captures ARL_BUSINESSES');

console.log('PORTFOLIO_REVIEW_SURFACES_396_PASS');
