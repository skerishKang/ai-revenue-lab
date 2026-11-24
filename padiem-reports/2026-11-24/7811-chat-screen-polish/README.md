# #7811 C4 chat-screen-polish.css absorption verification

## Comparison
- Base 5be5e81d7; patch 00f95604e
- Glass computed: 5 widths x 4 states x 4 pseudo-states = 80 combinations, zero differences
- Previous light pixel comparison: 26 combinations, zero differences
- Four other themes x 2 widths x 13 screens: 104 comparisons, zero differences
- Same-code controls: 5 themes x 2 widths x 13 screens = 130, zero differences
- Answer actions and microphone-absent: 5 themes x 2 widths x 2 states = 20, zero differences
- Eight intentional CSS mutations all detected by nonzero pixel differences
- Background-image URL host/port normalization only, path and file name preserved

## Structure audit
| Metric | Base | Patch | Delta |
|---|---:|---:|---:|
| css_rules | 4385 | 4377 | -8 |
| css_themed_rules | 795 | 793 | -2 |
| css_important | 475 | 475 | +0 |
| css_themed_important | 104 | 104 | +0 |
| css_color_literals | 1027 | 1027 | +0 |
| css_color_literals_unthemed | 366 | 366 | +0 |

## Absorption
- Six existing CSS rules absorbed by attachments.css, interaction-polish.css, padiem-glass-portrait.css, voice-composer.css, claw-composer-connection-status.css, sidebar-unified.css
- Two visually inactive overrides removed; four intentionally retained for specificity/token constraints
- New !important: 0; new color literals: 0. No product source edits during verification

## Evidence
- Eight PNG screenshots (4 pixel, 2 answer, 2 intentional mutation), hashes and sizes in manifest.json
- computed_glass.json, pixel.json, control.json, special.json, tamper.json, pytest.log
- Local HTTP ERR_ADDRESS_IN_USE invalid trials excluded; replayed; original invalid logs retained outside repository
