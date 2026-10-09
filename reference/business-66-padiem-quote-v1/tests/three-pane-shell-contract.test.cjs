const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "styles.css"), "utf8");
const shell = fs.readFileSync(path.join(ROOT, "shell-layout.js"), "utf8");
const check = (condition, label) => assert.ok(condition, "contract failed: " + label);

check(html.includes('<script src="shell-layout.js" defer></script>'),
  "canonical page loads three-pane shell after account/runtime scripts");
check(html.includes('id="easyComposer"') && html.includes('id="easySend"'),
  "single chat composer remains primary conversational input");
check(!html.includes('id="padiemQuoteRequest"') && !html.includes('id="padiemQuoteGenerate"'),
  "duplicate legacy quote input and send action are removed");
check(shell.includes('skillHost.appendChild(skillSelect)'),
  "rail moves actual Saved Quote Skill selector");
check(shell.includes('templateHost.appendChild(templateSelect)'),
  "rail moves actual Quote Template selector");
check(shell.includes('modelHost.appendChild(modelSelect)'),
  "rail moves the one authoritative selected-model control, no hidden fallback");
check(shell.includes('b66:open-recent-quotes') && shell.includes('b66:open-file-intake'),
  "rail secondary navigation activates the canonical Easy view actions");
check(shell.includes('id="shellNewQuote"') && shell.includes('clickExisting("newQuote")'),
  "rail exposes an explicit new-quote action");
check(shell.includes('account.appendChild(accountButton)'),
  "rail moves actual account button");
check(shell.includes('host.appendChild(preview)'),
  "right pane moves canonical preview node");
check(!shell.includes('createElement("iframe")') && !shell.includes("b66-cgi-form.html"),
  "production shell never embeds CGI prototype iframe");
check(css.includes(".shell-legacy-account-panel") && css.includes("display: none !important"),
  "large legacy account panel is removed from presentation");
check(css.includes("max-width: 820px"), "conversation reading width is capped at 820px");
check(css.includes("--b66-preview-width") && shell.includes("PREVIEW_MIN = 300") &&
      shell.includes("PREVIEW_MAX = 1000"), "preview resize is bounded");
check(shell.includes('classList.add("preview-collapsed")') &&
      shell.includes('classList.remove("preview-collapsed")'), "preview collapse/reopen exists");
check(shell.includes('classList.toggle("rail-collapsed")'), "rail collapse/reopen exists");
check(css.includes("@media (max-width: 900px)"), "mobile shell has explicit bounded layout");
check(html.match(/id="quotePaper"/g)?.length === 1, "exactly one canonical quote paper exists");
check(html.match(/id="easyComposer"/g)?.length === 1, "exactly one chat composer exists");

console.log("B66_THREE_PANE_SHELL=PASS");
console.log("B66_PRIMARY_INPUT_AUTHORITY=EASY_COMPOSER");
console.log("B66_CANONICAL_PREVIEW_COUNT=1");
console.log("B66_CGI_IFRAME_COUNT=0");
