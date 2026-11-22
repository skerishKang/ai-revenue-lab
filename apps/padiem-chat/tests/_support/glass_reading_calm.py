"""#8060 52차: raw reads for the Glass reading-calm contracts.

theme.js, padiem-glass-reading.css, padiem-glass-portrait.css, app.js and
chat-conversation-module.js are read here, so the contract tests receive the
shipped sources as the same-named texts they always used — without opening
static files themselves.
"""
from __future__ import annotations

from _support.claw_static import sheet

THEME = sheet("theme.js")
READING = sheet("padiem-glass-reading.css")
PORTRAIT = sheet("padiem-glass-portrait.css")
APP = sheet("app.js")
# #7216 R5 step 5a: showConversation moved into chat-conversation-module.js.
CONV = sheet("chat-conversation-module.js")
