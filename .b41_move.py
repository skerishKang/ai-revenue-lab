"""B4-1: move the account functions out of chat-auth-module.js into chat-account-module.js."""
import re
from pathlib import Path

STATIC = Path("apps/padiem-chat/static")
AUTH = STATIC / "chat-auth-module.js"
APP = STATIC / "app.js"
ACCOUNT = STATIC / "chat-account-module.js"

auth_src = AUTH.read_text(encoding="utf-8")

ACCOUNT_FNS = [
    # password reset (9)
    "passwordResetTokenFromLocation", "clearPasswordResetFragment", "showPasswordResetView",
    "hidePasswordResetViews", "openPasswordResetRequest", "openPasswordResetConfirm",
    "closePasswordResetViews", "submitPasswordResetRequest", "submitPasswordResetConfirm",
    # password change (3)
    "openPasswordChangeDialog", "closePasswordChangeDialog", "submitPasswordChange",
    # account delete (7)
    "resetAccountDeleteConfirm", "resetAccountSharedDeleteConfirm", "openAccountDeleteConfirm",
    "openAccountSharedDeleteConfirm", "syncAccountDeleteButton", "syncAccountSharedDeleteButton",
    "submitAccountDelete",
    # helper used only by the delete buttons
    "syncDeleteButton",
]

MOVED_DECLS = [
    "accountDeleteOpen", "accountSharedDeleteOpen", "accountDeleteConfirmEmail",
    "accountDeleteButton", "accountDeleteError", "accountSharedDeleteConfirm",
    "accountSharedDeleteConfirmEmail", "accountSharedDeleteButton", "accountSharedDeleteError",
    "passwordChangeOpen", "passwordChangeDialog", "passwordChangeDialogClose",
    "passwordChangeForm", "passwordChangeCurrent", "passwordChangeNew", "passwordChangeConfirm",
    "passwordChangeError", "passwordChangeSubmit",
    "passwordResetRequestForm", "passwordResetConfirmForm",
    "passwordResetBack", "passwordResetConfirmBack",
]


def block(name: str) -> str:
    pattern = re.compile(r"^  (?:async )?function " + re.escape(name) + r"\(", re.M)
    m = pattern.search(auth_src)
    assert m, name
    i = auth_src.index("{", m.end())
    depth = 0
    j = i
    while True:
        ch = auth_src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return auth_src[m.start():j + 1]
        j += 1


blocks = {name: block(name) for name in ACCOUNT_FNS}

# rewrite deps-own DOM refs and sibling account calls to create()-scoped locals
own = {}
for name, body in blocks.items():
    for local in MOVED_DECLS + ACCOUNT_FNS:
        body = re.sub(r"\bdeps\." + re.escape(local) + r"\b", local, body)
    own[name] = body

used = set()
for body in own.values():
    used.update(re.findall(r"\bdeps\.([A-Za-z_$][\w$]*)", body))
DEPS = [
    "accountDeleteConfirm", "authDialog", "authDialogView", "authMethodEnabled", "authState",
    "closeAuthDialog", "closeSettings", "loadAuthStatus", "openAuthDialog",
    "passwordResetConfirm", "passwordResetConfirmError", "passwordResetConfirmStatus",
    "passwordResetConfirmSubmit", "passwordResetConfirmView", "passwordResetEmail",
    "passwordResetNew", "passwordResetOpen", "passwordResetPanel", "passwordResetRequestError",
    "passwordResetRequestStatus", "passwordResetRequestSubmit", "passwordResetRequestView",
    "passwordLoginError", "passwordResetToken", "passwordAuthRequest", "setAuthFormError", "setAuthStatusMessage",
    "syncAuthDialogMethods", "uiT",
]
assert used == set(DEPS) - {"syncAuthDialogMethods"}, (sorted(used - set(DEPS)), sorted(set(DEPS) - used))

deflist = "".join(n + ",\n" for n in MOVED_DECLS)
lookups = "".join(f'      const {n} = document.getElementById("{n}");\n' for n in MOVED_DECLS)

wire = '''      function wire() {
        if (deps.passwordResetOpen) {
          deps.passwordResetOpen.addEventListener("click", openPasswordResetRequest);
        }
        if (passwordResetRequestForm) {
          passwordResetRequestForm.addEventListener("submit", submitPasswordResetRequest);
        }
        if (passwordResetConfirmForm) {
          passwordResetConfirmForm.addEventListener("submit", submitPasswordResetConfirm);
        }
        if (passwordResetBack) {
          passwordResetBack.addEventListener("click", () => {
            hidePasswordResetViews();
            deps.syncAuthDialogMethods();
          });
        }
        if (passwordResetConfirmBack) {
          passwordResetConfirmBack.addEventListener("click", () => {
            hidePasswordResetViews();
            deps.syncAuthDialogMethods();
          });
        }
        if (passwordChangeForm) passwordChangeForm.addEventListener("submit", submitPasswordChange);
        if (passwordChangeOpen) passwordChangeOpen.addEventListener("click", openPasswordChangeDialog);
        if (accountDeleteOpen) accountDeleteOpen.addEventListener("click", openAccountDeleteConfirm);
        if (accountSharedDeleteOpen) {
          accountSharedDeleteOpen.addEventListener("click", openAccountSharedDeleteConfirm);
        }
        if (accountDeleteConfirmEmail) {
          accountDeleteConfirmEmail.addEventListener("input", syncAccountDeleteButton);
        }
        if (accountDeleteButton) {
          accountDeleteButton.addEventListener("click", () => submitAccountDelete(false));
        }
        if (accountSharedDeleteConfirmEmail) {
          accountSharedDeleteConfirmEmail.addEventListener("input", syncAccountSharedDeleteButton);
        }
        if (accountSharedDeleteButton) {
          accountSharedDeleteButton.addEventListener("click", () => submitAccountDelete(true));
        }
        if (passwordChangeDialogClose) passwordChangeDialogClose.addEventListener("click", closePasswordChangeDialog);
        if (passwordChangeDialog) {
          passwordChangeDialog.addEventListener("cancel", (event) => {
            event.preventDefault();
            closePasswordChangeDialog();
          });
        }
      }
'''

body = "".join(own[n] + "\n" for n in ACCOUNT_FNS)
account_src = (
    "// #7812 R5 B4-1 - account section (password reset, password change, account delete).\n"
    "// Moved out of chat-auth-module.js. No behavior, copy, DOM id, request, body or\n"
    "// confirm-step change. Shared state and shared DOM stay app.js-owned and are read\n"
    "// through deps getters/setters; app.js keeps the same-named one-line forwarders.\n"
    "(() => {\n"
    '  "use strict";\n'
    "  window.PadiemChatAccountModule = {\n"
    "    create(deps) {\n"
    "      // #7812 R5 B4-1: account-only DOM lookups happen here, never at load.\n"
    + lookups +
    "\n" + body + "\n" + wire +
    "\n      return {\n" +
    "".join(f"        {n},\n" for n in ACCOUNT_FNS + ["wire"]) +
    "      };\n"
    "    },\n"
    "  };\n"
    "})();\n"
)
ACCOUNT.write_text(account_src, encoding="utf-8", newline="\n")

# remove the moved blocks and return entries from the auth module
for name in ACCOUNT_FNS:
    assert blocks[name] in auth_src
    auth_src = auth_src.replace(blocks[name] + "\n", "", 1)
for name in ACCOUNT_FNS:
    auth_src = re.sub(r"^        " + re.escape(name) + r",\n", "", auth_src, flags=re.M)

AUTH.write_text(auth_src, encoding="utf-8", newline="\n")

# ---- app.js ----
app = APP.read_text(encoding="utf-8")
# #7812 R5 B4-1: the auth module no longer reads these deps.
auth_used = set(re.findall(r"\bdeps\.([A-Za-z_$][\w$]*)", auth_src))
start = app.index("authModuleInstance = window.PadiemChatAuthModule.create({")
end = app.index("      });", start)
kept, dropped = [], 0
for line in app[start:end].splitlines(keepends=True):
    m = re.match(r"\s+(get|set) ([A-Za-z_$][\w$]*)\([^\n]*\n", line)
    if m and m.group(2) not in auth_used:
        dropped += 1
        continue
    kept.append(line)
app = app[:start] + "".join(kept) + app[end:]
print("auth deps dropped:", dropped)
for name in MOVED_DECLS:
    line = f'  const {name} = document.getElementById("{name}");\n'
    assert line in app, name
    app = app.replace(line, "", 1)
for name in ACCOUNT_FNS:
    if name == "syncDeleteButton":
        continue
    old = f"function {name}(...a) {{ return authModule().{name}(...a); }}"
    assert old in app, name
    app = app.replace(old, f"function {name}(...a) {{ return accountModule().{name}(...a); }}", 1)

getters = []
for name in DEPS:
    if name in ("authDialogView", "passwordResetToken"):
        getters.append(f"        get {name}() {{ return {name}; }},")
        getters.append(f"        set {name}(value) {{ {name} = value; }},")
    else:
        getters.append(f"        get {name}() {{ return {name}; }},")
factory = (
    "  // #7812 R5 B4-1: the account module owns password reset/change and account\n"
    "  // deletion. app.js keeps the same-named forwarders; account-only DOM is looked\n"
    "  // up inside create() and the listeners are registered by wire().\n"
    "  let accountModuleInstance = null;\n"
    "  function accountModule() {\n"
    "    if (!accountModuleInstance) {\n"
    "      accountModuleInstance = window.PadiemChatAccountModule.create({\n" +
    "\n".join(getters) + "\n"
    "      });\n"
    "    }\n"
    "    return accountModuleInstance;\n"
    "  }\n"
)
anchor = "    return authModuleInstance;\n  }\n"
assert anchor in app
app = app.replace(anchor, anchor + factory, 1)

start = app.index("  if (passwordResetOpen) {")
end = app.index('  document.querySelectorAll("[data-prompt]")')
app = app[:start] + (
    "  // #7812 R5 B4-1 (rule (b)): the module registers the reset/change/delete\n"
    "  // listeners at this original position, so their registration order is unchanged.\n"
    "  accountModule().wire();\n"
) + app[end:]
APP.write_text(app, encoding="utf-8", newline="\n")

# ---- index.html ----
index = (STATIC / "index.html").read_text(encoding="utf-8")
tag = '  <script src="./chat-auth-module.js"></script>'
assert tag in index
index = index.replace(tag, '  <script src="./chat-account-module.js"></script>\n' + tag, 1)
(STATIC / "index.html").write_text(index, encoding="utf-8", newline="\n")
print("account module created:", len(account_src.splitlines()), "lines; auth lines:", len(auth_src.splitlines()))
