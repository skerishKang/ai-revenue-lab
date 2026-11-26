#7811 C4: padiem-chat-ui-polish.css — obsolete sidebar legal rail

- Base: `origin/main` 4511eb8f1; change: 3 unused `.sidebar-legal-links` selectors removed (19 lines). `index.html` uses `.sidebar-legal`; `test_privacy_terms_pages_6659.py` explicitly rejects `.sidebar-legal-links` markup. Live sidebar styling in `sidebar-utility.css` remains untouched.
- Structural audit main -> head: CSS rules 4355 -> 4352; `!important` 319 -> 319; theme `!important` 75 -> 75; non-token color literals 244 -> 244. No JS or static string contract change.
- COM1 focused pytest: 43 PASS (`test_structure_ratchet`, `test_privacy_terms_pages_6659`, `test_7961_sidebar_glass_cell_and_legal`, `test_7365_sidebar_groups`).
- COM2 computed style: 5 themes x 2 widths = 10/10 exact equality for live `.sidebar-legal` and `.sidebar-legal a` (see computed.json). The removed selector has no element in either revision.
- COM2 headless pixel compare: home-logout, 5 themes x 2 widths, 10/10 raw pixel difference 0, see pixel.json; self/self control 10/10 zero, see control.json. Positive tamper control `--radius-pill` changed ~1,510 pixels, see tamper.json.
- Only two representative post-change images retained: light-mobile.png and glass-desktop.png. Full 10-case metrics are in JSON. No screenshots committed outside this evidence folder.
- No user-facing behavior, text, or layout changes. No merge or deployment performed.
