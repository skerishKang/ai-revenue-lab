# #7811 C4 dark-contrast CSS absorption

## Summary
- Main c2d6b87031ee000fb21d5152f545533df09e6961
- Moved dark body background into the existing same-selector rule in padiem-themes.css.
- Removed duplicate rule; CSS rules 4356 to 4355, themed rules 767 to 766, important 327 to 327, color literals 880 to 880, new raw-text assertions 0.

## COM2 validation
- Computed CSS: 5 themes x 2 viewports: 10/10 exact across sampled DOM and pseudo-elements
- Pixel: 10/10 identical
- Same-code control: 10/10 identical
- Intentional CSS mutation: 2/2 detected
- Local focused pytest: 33 passed, including structure ratchet
- Background-image URL host and port ignored only; path and filename retained

## Remaining rules and reasons
| Group | Reason for keeping |
|---|---|
| Sidebar items, hover, badges, topbar and headings | Dark-specific colors and high-specificity state rules; migrating to shared components risks overriding other themes |
| Composer fields, model chooser, tool and send buttons | Chat/claw state and focus specificity require cascade checks before moving |
| Messages, rich results, source cards and alert banners | Mixed components with dark-only borders, backgrounds and text colors |
| Settings modal and advanced settings forms | Dialog-specific state controls, selection, danger and hover |
| Focus-visible global control boundaries | Dark-theme scope differs from the shared accessibility owner |

## Evidence
- PNG 7 total: light/cinematic before-after 4, mutation before-after 2, diff 1
- computed.json, pixel.json, control.json, tamper.json, manifest.json
