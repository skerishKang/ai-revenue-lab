"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const src = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const html = src("index.html"), shell = src("shell-layout.js"),
  app = src("app.js"), account = src("padiem-account.js"),
  settings = src("company-profile-settings.js"), polish = src("b66-surface-refresh.css"),
  easy = src("easy-mode.js");
const unique = (id) => {
  const count = (html.match(new RegExp('id="' + id + '"', "g")) || []).length;
  assert.equal(count, 1, id + " must appear exactly once");
};
for (const id of ["easyComposer", "easyAttach", "easyVoiceMic", "easySend",
 "easyModelToolbar", "padiemQuoteModelSelect", "padiemQuoteReasoningSelect",
 "settingsPrivacyChoice", "settingsCompanyChoice", "settingsDriveChoice",
 "privacySettingsView", "companySettingsView", "driveSettingsView",
 "driveStoragePanel", "companyProfileHost", "importCompanyProfile"]) unique(id);
assert.match(shell, /toolbar\.appendChild\(modelControl\)/, "model control must move to composer");
assert.match(shell, /modelHost\.appendChild\(modelSelect\)/, "same model selector reused");
assert.match(shell, /reasoningControl\.appendChild\(reasoningSelect\)/);
assert.doesNotMatch(shell, /shellFileImport/, "no sidebar duplicate file import");
assert.match(shell, /b66:open-file-intake/, "composer attachment reuses intake");
assert.match(account, /const menu = byId\("b66AccountMenu"\)/);
assert.doesNotMatch(account, /if \(settings\) settings\.click\(\)/, "account not directly settings");
assert.match(app, /chooseSettings\(null\)/, "settings opens to a menu");
assert.match(app, /"importCompanyProfile"\)\.addEventListener/);
assert.match(app, /Object\.keys\(fields\)\.forEach\(\(key\) => \{ draft\.sender\[key\] = fields\[key\]; \}\)/);
assert.match(app, /if \(different && !window\.confirm/);
assert.doesNotMatch(app, /document\.addEventListener\("b66:runtime-changed", \(event\) => \{/, "profile must never auto-replace restored sender");
assert.doesNotMatch(settings, /if \(authenticatedHint !== false\) maybeAutoOpenPanel\(\)/);
assert.match(html, /id="easyVoiceMic"[^>]*disabled/, "mic is visibly staged, not fake STT");
assert.match(shell, /"b66AccountMenuDrive"/, "existing profile exposes Drive directly");
assert.match(shell, /clickExisting\("settingsDriveChoice"\)/, "Drive shortcut reuses settings authority");
assert.match(html, /id="driveSettingsView"/, "Drive is a dedicated settings page");
assert.match(app, /driveChoice\.addEventListener\("click"/, "Drive settings is functional");
assert.match(shell, /newSection\.appendChild\(manual\)/, "file-based template creation is immediately below New Quote");
assert.match(app, /skillUiApi\.actions\.openWizard\(\$\("shellManualQuote"\)\)/, "file wizard reused without approval bypass");
assert.match(polish, /#directStarter \{ display: none !important; \}/, "duplicate edit card hidden; edit tab remains");
assert.match(shell, /senderNote\.hidden = !\(quotePaper\.getAttribute/, "CGI fixed sender disclosure is scoped");
assert.match(shell, /readinessStatus\.textContent = ready \? "출력 준비" : "작성 중"/);
assert.match(shell, /reopen\.textContent = "견적서 보기"/);
assert.doesNotMatch(app, /select\.value = state\.quoteModels\[0\]/, "model must not be silently chosen");
assert.match(account, /const configured = result\.data\.default_tier/, "owner-selected B66 grade default is server-provided");
assert.match(account, /state\.quoteModels\.includes\(configured\)/, "never inject an unregistered grade");
assert.match(shell, /modelControl\.hidden = false/, "signed-out mobile keeps disabled model affordance visible");
assert.match(html, /id="resumeDraftStarter" type="button">/, "resume is displayed even before sign-in");
assert.match(easy, /App\.toast\("지난 견적을 이어서 사용하려면 먼저 로그인해 주세요\."\)/, "resume guests get sign-in prompt");
assert.match(easy, /\$\("recentQuoteStarter"\)\.hidden = true/, "home has exactly four primary starters");
assert.match(easy, /\$\("easyComposerNote"\)\.textContent = ""/, "CGI subtitle removed");
console.log("B66_COMPOSER_SETTINGS_CONTRACT=PASS");
