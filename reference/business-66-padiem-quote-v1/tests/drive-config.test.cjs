/* #3871 — Drive 런타임 설정 주입 지점 계약.
   실제 Google Drive 연결 검증은 승인된 클라이언트 ID 가 배포 시점에 주입되어야 시작할 수 있다.
   이 테스트는 (1) 저장소에 값이 커밋되지 않고 (2) 기본값이 안전하며
   (3) index.html 이 Drive 모듈보다 먼저 설정을 로드하는지 확인한다. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const read = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const configSource = read("drive-config.js");
const html = read("index.html");

/* drive-config.js 를 주어진 전역 위에서 실행한다. */
function runConfig(globals) {
  const sandbox = Object.assign({}, globals || {});
  vm.createContext(sandbox);
  vm.runInContext(configSource, sandbox);
  return sandbox;
}

/* ── 1. 값이 없는 저장소 기본값 ── */
{
  const sandbox = runConfig({});
  assert.equal(sandbox.B66_DRIVE_CLIENT_ID, "", "DEFAULT_CLIENT_ID_EMPTY");
  assert.equal(sandbox.B66_DRIVE_PICKER_APP_ID, "", "DEFAULT_PICKER_APP_ID_EMPTY");
  assert.equal(sandbox.B66_DRIVE_PICKER_DEVELOPER_KEY, "", "DEFAULT_PICKER_KEY_EMPTY");
}

/* ── 2. 배포 시 주입된 값을 덮어쓰지 않는다 ── */
{
  const sandbox = runConfig({
    B66_DRIVE_CLIENT_ID: "1234567890-abcdef.apps.googleusercontent.com",
    B66_DRIVE_PICKER_APP_ID: "1234567890",
    B66_DRIVE_PICKER_DEVELOPER_KEY: "browser-key"
  });
  assert.equal(sandbox.B66_DRIVE_CLIENT_ID, "1234567890-abcdef.apps.googleusercontent.com",
    "INJECTED_CLIENT_ID_PRESERVED");
  assert.equal(sandbox.B66_DRIVE_PICKER_APP_ID, "1234567890", "INJECTED_PICKER_APP_ID_PRESERVED");
  assert.equal(sandbox.B66_DRIVE_PICKER_DEVELOPER_KEY, "browser-key", "INJECTED_PICKER_KEY_PRESERVED");
}

/* ── 3. 비문자열 값은 빈 문자열로 정규화한다 ── */
{
  const sandbox = runConfig({ B66_DRIVE_CLIENT_ID: 42 });
  assert.equal(sandbox.B66_DRIVE_CLIENT_ID, "", "NON_STRING_CONFIG_NORMALIZED");
}

/* ── 4. 저장소에 실제 클라이언트 ID/키 값이 커밋되어 있지 않다 ──
   주석(운영 안내)에는 형식 예시가 있을 수 있지만, 코드에는 어떤 값도 없어야 한다. */
{
  const codeOnly = configSource
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  assert.equal(codeOnly.indexOf("apps.googleusercontent.com"), -1, "NO_CLIENT_ID_VALUE_IN_CODE");
  assert.equal(/AIza[0-9A-Za-z_-]{10,}/.test(codeOnly), false, "NO_BROWSER_API_KEY_IN_CODE");
  /* 코드에 남는 문자열 대입은 빈 문자열뿐이다. */
  const stringAssignments = codeOnly.match(/(?<![!=<>])=\s*"[^"]*"/g) || [];
  assert.deepEqual(stringAssignments, ['= ""'], "ONLY_EMPTY_STRING_ASSIGNMENTS");
}

/* ── 5. index.html 로드 순서: 설정 → Drive 모듈 ── */
{
  const configIndex = html.indexOf('src="drive-config.js"');
  const atomicIndex = html.indexOf('src="quote-import-atomic.js"');
  const contractIndex = html.indexOf('src="quote-drive-contract.js"');
  const clientIndex = html.indexOf('src="quote-drive-client.js"');
  const uiIndex = html.indexOf('src="quote-drive-ui.js"');
  assert.ok(configIndex !== -1, "CONFIG_SCRIPT_PRESENT");
  assert.ok(configIndex < atomicIndex, "CONFIG_BEFORE_ATOMIC");
  assert.ok(configIndex < contractIndex, "CONFIG_BEFORE_CONTRACT");
  assert.ok(configIndex < clientIndex, "CONFIG_BEFORE_CLIENT");
  assert.ok(configIndex < uiIndex, "CONFIG_BEFORE_UI");
  assert.ok(html.indexOf('id="driveStoragePanel"') !== -1, "PANEL_PRESENT");
}

/* ── 6. 설정이 없어도 기존 기능은 그대로다 ── */
{
  assert.ok(html.indexOf('id="printPdf"') !== -1, "PDF_BUTTON_UNCHANGED");
  assert.ok(html.indexOf('id="saveHistory"') !== -1, "HISTORY_BUTTON_UNCHANGED");
  assert.ok(html.indexOf('id="easyComposer"') !== -1, "COMPOSER_UNCHANGED");
}

console.log("B66_DRIVE_CONFIG=PASS");
console.log("DEFAULT_CONFIG_EMPTY=PASS");
console.log("INJECTED_CONFIG_PRESERVED=PASS");
console.log("NO_CONFIG_VALUE_COMMITTED=PASS");
console.log("CONFIG_LOADED_BEFORE_DRIVE_MODULES=PASS");
console.log("EXISTING_FEATURES_UNCHANGED_WITHOUT_CONFIG=PASS");
