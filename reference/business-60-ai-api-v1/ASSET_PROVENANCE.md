# Asset provenance — Business 60 cinematic anchor v1

All protagonist images in this review workspace are optimized derivatives of pre-existing LoveTree / owner design assets selected during the B60 design discussion. They are not newly generated for B60.

| Repository asset | Source asset used in review session | Transformation |
|---|---|---|
| `assets/woman-alone.webp` | `07-next-moment-female.png` | resized to max 1600px width, WebP quality 82 |
| `assets/woman-connection.webp` | `06-connection-female.png` | resized to max 1600px width, WebP quality 82 |
| `assets/woman-field.webp` | `08-memory-field-female.png` | resized to max 1600px width, WebP quality 82 |
| `assets/woman-close.webp` | `03-person-reveal-female.png` | resized to max 1600px width, WebP quality 82 |
| `assets/gesture-touch.webp` | existing LoveTree storyboard hand-only frame labelled `Touch the feeling` | cropped to the hand/forearm area, resized, WebP optimized |

## V13 editorial radar photo layer

The V13 opportunity-radar surface deliberately avoids new decorative SVG/AI illustration assets. It uses raster photography for editorial context while the actual benefit, verification state, provider, and source links remain text/data driven.

Remote image references live in `data/editorial-media.js` and are presentation-only; they are not evidence for pricing, limits, or promotion claims.

| Signal | Photo source | Photographer / credit | License/source page |
|---|---|---|---|
| `vercel-glm52` | Unsplash raster photo | Bayu Syaits | `https://unsplash.com/photos/laptop-and-phone-on-a-desk-with-coding-software-open-oYzjGQ7LCVE` |
| `google-gemini-free` | Unsplash raster photo | MJ Duford | `https://unsplash.com/photos/person-is-working-on-a-laptop-and-writing-in-a-notebook-45u1mboQtQE` |
| `cloudflare-workers-ai-free` | Unsplash raster photo | Data Servers collection | `https://unsplash.com/photos/server-racks-in-data-center-klWUhr-wPJ8` |
| `groq-free-plan` | Unsplash raster photo | Daniil Komov | `https://unsplash.com/photos/laptop-with-code-headphones-phone-and-mouse-on-desk-41cG8-U74lc` |
| `openrouter-free-router` | Unsplash raster photo | Ritupon Baishya | `https://unsplash.com/photos/modern-laptop-and-keyboard-on-a-home-office-desk-vR2kup7Uyds` |

The photo pages above were reviewed as free-use Unsplash photo pages during the V13 design pass. B60 does not claim that these photos depict the named providers; they are editorial context only.

## Reviewed but intentionally not copied into runtime

- `S10_gesture_B.png`: useful forward-hand / lens-gesture reference, but it is a different protagonist. Used only as motion-language reference.
- `F01-touched.webp`: inspected as a contact-reaction expression reference; not the same protagonist as the selected scene series.
- `F01-talk.webp`: inspected as a speaking-expression reference; not the same protagonist as the selected scene series.

These non-runtime references must not be silently inserted merely to simulate hand/speech continuity.

## Motion reference boundary

The existing LoveTree `Supernova` benchmark shot map describes S10 as a bright medium close with a graphic hand gesture toward camera lasting about 0.625 seconds. B60 translates only that camera/gesture grammar into CSS/JS contact, flash, depth, inertial spatial motion, and world transitions. It does not copy the benchmark source video or the different-person S10 image.

The voice-to-API morph in `cinematic-v5.css/js` is entirely programmatic (HTML/CSS/JS): waveform bars, intent chips, route nodes, code strips, and the constructed API object introduce no additional raster/generated imagery.

The derivatives exist only to make repository review lightweight enough for the anchor. Their presence does not imply final B60 art approval.

No font files, credentials, private Drive identifiers, or personal data are included.
