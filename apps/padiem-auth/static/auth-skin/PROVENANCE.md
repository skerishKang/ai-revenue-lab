# Auth skin assets (provenance)

Byte-for-byte copies from `skerishKang/lovetree-4.0`
`docs/design/auth-skin/` at PR #208 (commit `e9e82e6`), the approved
night/garden login design for the common PADIEM login screen.

| Local file | Source | Use |
| --- | --- | --- |
| `assets/card-1.webp` | `assets/card-1.webp` | orbit card decoration |
| `assets/card-2.webp` | `assets/card-2.webp` | orbit card decoration |
| `assets/card-3.webp` | `assets/card-3.webp` | orbit card decoration |
| `assets/googleg-standard-color.svg` | `assets/googleg-standard-color.svg` | official standard-color Google `G` mark, unmodified |
| `assets/fonts/GowunBatang-Bold.latin.woff2` | same path | garden heading serif |
| `assets/fonts/Roboto-Medium.latin.woff2` | same path | Google button typeface |
| `assets/fonts/Roboto-Medium.latin-ext.woff2` | same path | Google button typeface, latin-ext |
| `LICENSE-GowunBatang-OFL.txt` | `assets/fonts/OFL.txt` | Gowun Batang licence |
| `LICENSE-Roboto-Apache-2.0.txt` | `assets/fonts/LICENSE-Roboto.txt` | Roboto licence |

`apps/padiem-auth/skin-assets.mjs` is generated from these files by
`node apps/padiem-auth/tools/build-auth-skin-assets.mjs`. Do not edit the
generated module by hand; change the raw file and regenerate.

The auth Worker has no static-asset binding, so the generated module embeds the
bytes and the Worker serves them at `/assets/auth-skin/<name>` on its own
origin. The login page therefore makes no external font or image request.
