# Image Sources and Ownership

Acquisition / creation date: **2026-07-29**

All visual assets are original repository-local work created for this Phase 1 reference. No third-party image, logo, icon, screenshot, brand asset, font file or external runtime request is used.

The three focal assets use an original raster-paper composite generated with Pillow and embedded as a local PNG data layer inside an SVG wrapper, then combined with original vector cut-lines and labels. This provides mixed-media raster/vector treatment while keeping every asset self-contained and repository-local.

| Asset | Type | Source and ownership | Intended use |
|---|---|---|---|
| `assets/images/owner-authority-composite.svg` | Original mixed-media raster composite + SVG overlay | Created in-repository by OpenAI for Haneul Works synthetic fixture; project-owned | Focal owner/requester/operator authority dossier |
| `assets/images/scope-cutline-composite.svg` | Original mixed-media raster composite + SVG overlay | Created in-repository; project-owned | Focal requested/approved/prohibited scope cut-line |
| `assets/images/revocation-record-composite.svg` | Original mixed-media raster composite + SVG overlay | Created in-repository; project-owned | Focal revocable-access and residual-condition record |
| `assets/images/mail-system-dossier.svg` | Original SVG | Created in-repository; project-owned | Synthetic Haneul Mail Archive source dossier |
| `assets/images/drive-system-dossier.svg` | Original SVG | Created in-repository; project-owned | Synthetic Haneul Team Drive source dossier |
| `assets/images/ledger-system-dossier.svg` | Original SVG | Created in-repository; project-owned | Synthetic Haneul Contract Ledger source dossier |
| `assets/images/field-mapping-sheet.svg` | Original SVG | Created in-repository; project-owned | Source-to-normalized field mapping and exclusion diagram |
| `assets/images/not-connected-seal.svg` | Original SVG | Created in-repository; project-owned | Connector-readiness / not-connected seal |
| `assets/images/credential-boundary.svg` | Original SVG | Created in-repository; project-owned | Credential reference versus secret-value boundary |
| `assets/images/retention-band.svg` | Original SVG | Created in-repository; project-owned | Thirty-day retention and deletion band |
| `assets/images/audit-evidence.svg` | Original SVG | Created in-repository; project-owned | Audit-evidence / no-employee-monitoring distinction |
| `assets/images/incident-handoff.svg` | Original SVG | Created in-repository; project-owned | Pause, notify owner and preserve evidence handoff |

## Runtime rule

All `<img>` references resolve beneath `assets/images/`. The HTML, CSS and JavaScript contain no `http://`, `https://`, protocol-relative, remote font, analytics, image CDN or API request.
