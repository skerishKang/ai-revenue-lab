# Auth skin assets (provenance)

Byte-for-byte copies from `skerishKang/lovetree-4.0`
`docs/design/auth-skin/` at PR #208 (commit `e9e82e6`), the approved
night/garden login design for the common PADIEM login screen.
`assets/card-3.webp` and the new `assets/card-4.webp` follow the later
four-photo orbit revision (#347, commit `3346374`: two women, two men).

| Local file | Source | Use |
| --- | --- | --- |
| `assets/card-1.webp` | `assets/card-1.webp` | orbit card decoration |
| `assets/card-2.webp` | `assets/card-2.webp` | orbit card decoration |
| `assets/card-3.webp` | `assets/card-3.webp` (#347, `3346374`) | orbit card decoration |
| `assets/card-4.webp` | `assets/card-4.webp` (#347, `3346374`) | orbit card decoration |
| `assets/googleg-standard-color.svg` | `assets/googleg-standard-color.svg` | official standard-color Google `G` mark, unmodified |
| `assets/fonts/GowunBatang-Bold.latin.woff2` | same path | garden heading serif |
| `assets/fonts/Roboto-Medium.latin.woff2` | same path | Google button typeface |
| `assets/fonts/Roboto-Medium.latin-ext.woff2` | same path | Google button typeface, latin-ext |
| `LICENSE-GowunBatang-OFL.txt` | `assets/fonts/OFL.txt` | Gowun Batang licence |
| `LICENSE-Roboto-Apache-2.0.txt` | `assets/fonts/LICENSE-Roboto.txt` | Roboto licence |

The four portraits come from the design repository's own character photo set
(`src/views/orbit-samples.json`, `assetSource: "캐릭터-얼굴만"`,
`curationClass: "portrait"`); they are not real people and are not taken from
an external stock source. The design `README.md` records the per-file origin
(`card-1` = m01 첫인상, `card-2` = m02 푸른 시간, `card-3` = m11 의자에 앉은
모습, `card-4` = m15 트리의 빛) and that the 362×362 quality-92 originals under
`public/media/orbit/` were copied without conversion. No resize, re-encode or
format change is made here either.

`apps/padiem-auth/skin-assets.mjs` is generated from these files by
`node apps/padiem-auth/tools/build-auth-skin-assets.mjs`. Do not edit the
generated module by hand; change the raw file and regenerate.

The auth Worker has no static-asset binding, so the generated module embeds the
bytes and the Worker serves them at `/assets/auth-skin/<name>` on its own
origin. The login page therefore makes no external font or image request.
