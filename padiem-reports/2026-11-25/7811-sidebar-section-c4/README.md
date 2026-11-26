# #7811 C4 sidebar-section-polish.css absorption

## Scope
- Moved the sidebar section toggle base rule to its component owner sidebar-unified.css.
- Removed two unreachable rules: collapsed chevron transform shadowed by a stronger selector, and duplicate project heading margins already defined in sidebar-section-polish.css.
- Original sheet 32 to 30, owner sheet remains 24, total rules reduced by two.
- No new !important, color literals, or raw static-text assertions.

## Verification
- COM2: 5 themes x 2 viewports, 10/10 identical computed CSS declarations.
- COM2: 10/10 identical rendered pixel images and valid application states.
- COM2: 10/10 identical same-code control pixels.
- 2/2 intentional CSS mutations visibly detected.
- COM1 worktree: 42 focused pytest and structure-ratchet cases passed (20 + 22).
- Screenshot count 7, each checksummed in manifest.json.
- Background-image origin normalization replaces host and port only; image path preserved.

## Structure audit
| Metric | main | patch | delta |
|---|---:|---:|---:|
| css_rules | 4356 | 4354 | -2 |
| css_important | 327 | 327 | +0 |
| css_themed_rules | 767 | 767 | +0 |
| css_themed_important | 83 | 83 | +0 |
| css_color_literals | 880 | 880 | +0 |
| css_color_literals_unthemed | 244 | 244 | +0 |
| raw_static_text_assertions | None | None | +0 |

## Remaining rules retained and why
| Rule group | Reason retained |
|---|---|
| Project/history shared row surfaces and hover/selected states | Section, theme and :has-specific cascade differs from generic sidebar surface. Moving unverified selectors changes contrast and focus behavior. |
| Row children, edit and delete controls, contextual menu | Focus, menu and 44px hit target geometry are interdependent; preserve current visual and click contracts. |
| Section headings, chevron geometries and reduced motion | Expanded/collapsed and keyboard focus behavior need cascade-wide transfer; original transition must survive reduced-motion media. |
| Home starter cards fixed 145px height | Viewport-dependent card contract must not change in responsive layouts. |
| Glass background processing on row action buttons | Glass-only paint ownership cannot be moved into global sidebar selectors without changing compositing. |

## Evidence
- PNG files: 4 before/after + 2 CSS mutation + 1 diff, 7 total.
- computed.json, pixel.json, control.json, tamper.json, audit.json, pytest.log and manifest.json.
