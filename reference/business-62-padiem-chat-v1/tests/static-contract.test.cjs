const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'styles.css'), 'utf8');
const js = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');

test('first screen is a simple Padiem Chat entry point', () => {
  assert.match(html, /Padiem Chat/);
  assert.match(html, /무엇을 도와드릴까요/);
  assert.match(html, /무엇이든 물어보세요/);
  assert.match(html, /자동 추천/);
  assert.match(html, />파일</);
  assert.match(html, />웹 검색</);
});

test('required deterministic Phase 1 states are reviewable', () => {
  for (const state of ['home', 'chat', 'search', 'attachment', 'error']) {
    const statePattern = new RegExp(`(?:state ===|dataset\\.state =|targetState ===) "${state}"`);
    assert.match(js, statePattern);
  }
  assert.match(readme, /mobile uses the same states through responsive CSS/);
});

test('truth boundary does not fake a live AI or live search', () => {
  assert.match(html, /실제 AI 연결 전 UX 검토용 미리보기/);
  assert.match(html, /데모 응답은 실제 모델 호출이 아닙니다/);
  assert.match(js, /실제 검색 결과 아님/);
  assert.match(readme, /No model, provider, search engine, file service, account, database or API is connected/);
});

test('reference has no live fetch or external runtime asset dependency', () => {
  assert.doesNotMatch(js, /\bfetch\s*\(/);
  assert.doesNotMatch(html, /https?:\/\//);
  assert.doesNotMatch(css, /https?:\/\//);
  assert.doesNotMatch(html, /<script[^>]+src=["']https?:/i);
  assert.doesNotMatch(html, /<link[^>]+href=["']https?:/i);
});

test('parent-generation accessibility basics are explicit', () => {
  assert.match(css, /font-size:\s*16px/);
  assert.match(css, /focus-visible/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /min-height:\s*4[0248]px/);
  assert.match(html, /aria-label="메시지 입력"/);
  assert.match(html, /aria-label="메시지 보내기"/);
});

test('hidden review states remain visually hidden until activated', () => {
  assert.match(html, /id="messageList" hidden/);
  assert.match(html, /id="attachmentChip" hidden/);
  assert.match(html, /\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}/);
});

test('Projects are visible only as a future capability', () => {
  assert.match(html, /프로젝트/);
  assert.match(html, /준비 중/);
  assert.match(html, /disabled aria-disabled="true"/);
  assert.match(readme, /Projects/);
});
