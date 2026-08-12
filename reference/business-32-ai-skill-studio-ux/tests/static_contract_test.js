/* Static contract test: required trust labels, keyboard contract wiring,
 * external runtime dependency 0, and JavaScript syntax across the workspace.
 */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { spawnSync } = require('child_process');

let failures = 0;

function check(name, fn) {
  try {
    fn();
    console.log('PASS ' + name);
  } catch (error) {
    failures += 1;
    console.error('FAIL ' + name + ': ' + error.message);
  }
}

const root = path.join(__dirname, '..');
const read = function (rel) {
  return fs.readFileSync(path.join(root, rel), 'utf8');
};

const indexHtml = read('index.html');
const templatesSrc = read('scripts/templates.js');
const appSrc = read('scripts/app.js');

const REQUIRED_LABELS = [
  'AI-ASSISTED STEP',
  'HUMAN ACTION',
  'SOURCE EVIDENCE',
  'MISSING EVIDENCE',
  'CONFLICTING EVIDENCE',
  'DRAFT RESULT',
  'REVIEW CORRECTION',
  'NOT YET APPROVED',
  'HUMAN-APPROVED',
  'VERIFIED ORGANIZATIONAL AI SKILL'
];

const RUNTIME_FILES = [
  'index.html',
  'scripts/fixture.js',
  'scripts/machine.js',
  'scripts/navigation.js',
  'scripts/templates.js',
  'scripts/app.js',
  'styles/tokens.css',
  'styles/base.css',
  'styles/layout.css',
  'styles/components.css',
  'styles/states.css'
];

function listSvg() {
  return fs
    .readdirSync(path.join(root, 'assets', 'images'))
    .filter(function (name) {
      return name.endsWith('.svg');
    });
}

check('every required authority label appears in runtime source', function () {
  const haystack = indexHtml + templatesSrc;
  REQUIRED_LABELS.forEach(function (label) {
    assert.ok(haystack.indexOf(label) !== -1, 'label missing: ' + label);
  });
});

check('index.html loads all five local scripts with deterministic tokens', function () {
  ['scripts/fixture.js', 'scripts/machine.js', 'scripts/navigation.js', 'scripts/templates.js', 'scripts/app.js'].forEach(function (src) {
    assert.ok(indexHtml.indexOf(src + '?v=b32-ux-static-v1') !== -1, 'missing or untokened script: ' + src);
  });
});

check('external runtime dependency is 0', function () {
  RUNTIME_FILES.concat(listSvg().map(function (name) {
    return path.join('assets', 'images', name);
  })).forEach(function (rel) {
    const content = read(rel);
    const withoutNamespace = content.replace(/xmlns="http:\/\/www\.w3\.org\/2000\/svg"/g, '');
    const matches = withoutNamespace.match(/https?:\/\//g);
    assert.ok(!matches, 'external URL found in ' + rel + ': ' + (matches || []).join(','));
  });
});

check('no fetch/XHR/WebSocket/storage in runtime scripts', function () {
  ['scripts/fixture.js', 'scripts/machine.js', 'scripts/navigation.js', 'scripts/templates.js', 'scripts/app.js'].forEach(function (rel) {
    const src = read(rel);
    assert.ok(!/\bfetch\(/.test(src), 'fetch used in ' + rel);
    assert.ok(!/XMLHttpRequest|WebSocket|localStorage|sessionStorage|indexedDB/.test(src), 'network/persistence API in ' + rel);
  });
});

check('keyboard contract is wired (navigation.js + app.js keydown)', function () {
  const navSrc = read('scripts/navigation.js');
  assert.ok(/nextIndex/.test(navSrc), 'nextIndex missing');
  assert.ok(/shouldActivate/.test(navSrc), 'shouldActivate missing');
  assert.ok(/ArrowRight|ArrowDown|ArrowLeft|ArrowUp|Home|End|Enter/.test(navSrc), 'key classes missing');
  assert.ok(/addEventListener\('keydown'/.test(appSrc), 'app keydown listener missing');
  assert.ok(/tabIndex/.test(appSrc), 'roving tabIndex missing');
});

check('every interactive action has an accessible label', function () {
  assert.ok(indexHtml.indexOf('<button type="button" class="scenario-btn" data-scenario="standard" aria-pressed="true">기본 업무</button>') !== -1, 'scenario button label missing');
  assert.ok(/<button[^>]*data-action="[^"]+"[^>]*>[^<]/.test(templatesSrc), 'template action buttons missing visible text');
});

check('evidence open control and aria-live regions exist', function () {
  assert.ok(indexHtml.indexOf('aria-live="polite"') !== -1, 'aria-live region missing');
  assert.ok(templatesSrc.indexOf('toggle-evidence') !== -1, 'evidence open action missing');
  assert.ok(templatesSrc.indexOf('SOURCE EVIDENCE') !== -1, 'evidence label missing');
});

check('mobile core journey actions exist in templates', function () {
  ['업무 시작', '필수 입력자료 확인', '단계 완료', '증거 열기', '보완 요청 기록', '사람 검토 요청', '사람 최종 승인', '스킬 카드 저장'].forEach(function (label) {
    assert.ok(templatesSrc.indexOf(label) !== -1, 'mobile journey action missing: ' + label);
  });
});

check('all JavaScript files parse (node --check)', function () {
  ['scripts/fixture.js', 'scripts/machine.js', 'scripts/navigation.js', 'scripts/templates.js', 'scripts/app.js', 'tests/machine_test.js', 'tests/journey_test.js', 'tests/fixture_test.js'].forEach(function (rel) {
    const res = spawnSync(process.execPath, ['--check', path.join(root, rel)], { encoding: 'utf8' });
    assert.strictEqual(res.status, 0, 'syntax error in ' + rel + ': ' + res.stderr);
  });
});

check('fixture.json assetVersion matches version in HTML', function () {
  const json = JSON.parse(read('data/fixture.json'));
  assert.ok(indexHtml.indexOf(json.assetVersion) !== -1, 'asset token not referenced in HTML');
});

check('asset token is low-entropy and identical across runtime files', function () {
  const json = JSON.parse(read('data/fixture.json'));
  const embedded = read('scripts/fixture.js');
  assert.strictEqual(json.assetVersion, 'b32-ux-static-v1');
  assert.ok(embedded.indexOf('"assetVersion": "b32-ux-static-v1"') !== -1, 'fixture.js token mismatch');
  assert.ok(indexHtml.indexOf('b32-ux-static-v1') !== -1, 'index.html token mismatch');
  assert.ok(read('scripts/templates.js').indexOf("const V = 'b32-ux-static-v1'") !== -1, 'templates.js token mismatch');
  assert.ok(!/2026\d{4}-[a-z0-9]+/i.test(indexHtml), 'high-entropy date token still present in HTML');
});

check('no unconditional focusFirst policy exists in app.js', function () {
  assert.ok(appSrc.indexOf('focusFirst') === -1, 'app.js must not contain focusFirst');
});

check('focus restoration is marker-based and deterministic', function () {
  assert.ok(appSrc.indexOf('data-focus-key') !== -1, 'app.js must use data-focus-key markers');
  assert.ok(appSrc.indexOf('applyFocus') !== -1, 'app.js must implement applyFocus');
  assert.ok(appSrc.indexOf('meta.validationError') !== -1, 'validation-error focus branch missing');
  assert.ok(appSrc.indexOf('meta.roleChanged') !== -1, 'role handoff focus branch missing');
  assert.ok(appSrc.indexOf('meta.drawerOpened') !== -1, 'drawer open focus branch missing');
  assert.ok(appSrc.indexOf('meta.drawerClosed') !== -1, 'drawer close focus branch missing');
  assert.ok(appSrc.indexOf('meta.recovery') !== -1, 'retry/return focus branch missing');
  assert.ok(appSrc.indexOf('error-summary') !== -1, 'error summary focus target missing');
  assert.ok(appSrc.indexOf('role-banner') !== -1, 'role banner focus target missing');
  assert.ok(appSrc.indexOf('drawer-heading') !== -1, 'drawer heading focus target missing');
  assert.ok(appSrc.indexOf('[data-action="toggle-evidence"]') !== -1, 'drawer close must return focus to opener');
});

check('focus target markers exist in templates', function () {
  ['view-heading', 'error-summary', 'drawer-heading', 'role-banner'].forEach(function (key) {
    assert.ok(templatesSrc.indexOf('data-focus-key="' + key + '"') !== -1, 'template missing data-focus-key=' + key);
  });
});

check('no data-actor attribute anywhere in runtime source', function () {
  const haystack = indexHtml + templatesSrc + appSrc;
  assert.ok(haystack.indexOf('data-actor') === -1, 'data-actor must be removed');
  assert.ok(haystack.indexOf('actor:') === -1, 'actor payload must be removed');
});

if (failures > 0) {
  console.error(failures + ' static contract failure(s)');
  process.exit(1);
}
console.log('static contract ok');
