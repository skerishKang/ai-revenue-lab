const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {pathToFileURL} = require('node:url');

const publicDir = path.join(__dirname, '../public');
const visibleParagraphs = [
  '첫 문단 ' + '가'.repeat(430) + ' 여기서 문장을 끝냅니다.',
  '둘째 문단 ' + '나'.repeat(430) + ' 마지막 문장입니다.'
];
const completeText = visibleParagraphs.join('\n\n');
assert.ok(completeText.length >= 800);

function loadDisplayHelpers() {
  const body = {classList: {contains: () => false, add() {}, remove() {}, toggle() {}}};
  const document = {
    body,
    getElementById: () => null,
    querySelectorAll: () => [],
    addEventListener() {}
  };
  const window = {};
  class MutationObserver { observe() {} }
  const context = {window, document, MutationObserver, addEventListener() {}, innerWidth: 1024};
  vm.runInNewContext(fs.readFileSync(path.join(publicDir, 'storymemory-b61-ui-polish-v1.js'), 'utf8'), context);
  vm.runInNewContext(fs.readFileSync(path.join(publicDir, 'storymemory-answer-normalize-v1.js'), 'utf8'), context);
  return window;
}

function makeRequest() {
  const packet = {
    version: '1', mode: 'storymemory_bounded_companion', source_scope: 'ceiling_filtered',
    diagnostics: {boundary_available: true, spoiler_policy: 'hard_no_future'},
    co_reader_decision: {decision: 'ALLOW', reason: 'WITHIN_CEILING'},
    reader_context: {authoritative_reader: true, current_work_key: 'bible-web'},
    reading_progress: {furthest_read_locator: 'bible:web:ACT:9:5', knowledge_ceiling_locator: 'bible:web:ACT:9:5'},
    source_passages: [{canonical_locator: 'bible:web:ACT:9:3', text: 'A bounded source passage.'}]
  };
  return new Request('https://reader.invalid/api/storymemory-ai', {
    method: 'POST',
    headers: {'content-type': 'application/json', origin: 'https://reader.invalid'},
    body: JSON.stringify({question: '현재 내용을 설명해 주세요.', packet})
  });
}

(async () => {
  const worker = (await import(pathToFileURL(path.join(publicDir, '_worker.js')).href)).default;
  const display = loadDisplayHelpers();
  const env = {BOOKAI_COM2_AI_SECRET: 'x'.repeat(40)};
  const originalFetch = global.fetch;
  const cases = [
    ['800자 이상 다중 문단 답', completeText, completeText],
    ['thought 태그가 포함된 답', `<thought>숨길 내부 내용</thought>${completeText}`, completeText],
    ['문단 JSON 답', JSON.stringify({paragraphs: visibleParagraphs.map(text => ({text, citations: []}))}), completeText]
  ];

  try {
    for (const [name, upstreamAnswer, expectedText] of cases) {
      let requestedTokens;
      global.fetch = async request => {
        const sent = JSON.parse(await request.text());
        requestedTokens = sent.agent.max_tokens;
        return Response.json({ok: true, answer: upstreamAnswer, context_permission: {
          boundary_disposition: 'permitted', context_filtered_count: 0, context_allowed_count: 1
        }});
      };
      const response = await worker.fetch(makeRequest(), env);
      const data = await response.json();
      assert.equal(requestedTokens, 4096, `${name}: generation budget is raised`);
      assert.equal(response.status, 200, name);
      const renderedText = data.answer.trim().startsWith('{')
        ? display.storyMemoryNormalizeCompanionAnswerV1(data.answer)
        : data.answer;
      assert.equal(renderedText, expectedText, `${name}: complete response reaches the display adapter`);
      const html = display.storyMemoryRenderCompanionMarkdownV1(renderedText);
      for (const paragraph of visibleParagraphs) assert.ok(html.includes(paragraph), `${name}: full paragraph is rendered`);
      assert.ok(html.endsWith('마지막 문장입니다.</p>'), `${name}: final sentence reaches the display end`);
    }
    console.log('PASS: long multi-paragraph, JSON, and thought-filtered answers render through their final sentence');
  } finally {
    global.fetch = originalFetch;
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
