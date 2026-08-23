# Asset provenance — Business 60 cinematic anchor v1

All protagonist images in this review workspace are optimized derivatives of pre-existing LoveTree / owner design assets selected during the B60 design discussion. They are not newly generated for B60.

| Repository asset | Source asset used in review session | Transformation |
|---|---|---|
| `assets/woman-alone.webp` | `07-next-moment-female.png` | resized to max 1600px width, WebP quality 82 |
| `assets/woman-connection.webp` | `06-connection-female.png` | resized to max 1600px width, WebP quality 82 |
| `assets/woman-field.webp` | `08-memory-field-female.png` | resized to max 1600px width, WebP quality 82 |
| `assets/woman-close.webp` | `03-person-reveal-female.png` | resized to max 1600px width, WebP quality 82 |
| `assets/gesture-touch.webp` | existing LoveTree storyboard hand-only shot labelled `Touch the feeling` inside `ChatGPT Image 2026년 8월 9일 오전 08_16_54 (4).png` | hand-only interior crop; enlarged with Lanczos; WebP quality 88; no new visual content generated |

## Gesture continuity rule

`gesture-touch.webp` contains no face and is used only as a brief foreground hand/contact layer. This avoids replacing the selected protagonist with a visibly different person while still allowing the `CONNECT` event to read as a physical touch rather than a floating cursor click.

The hand layer is masked and screen-blended in CSS, approaches from the protagonist side, reaches the API core only inside the contact window, and exits immediately after activation.

## Reviewed but intentionally not copied into runtime

- `S10_gesture_B.png`: useful forward-hand / lens-gesture reference, but it is a different protagonist. Used only as motion-language reference.
- `F01-touched.webp`: inspected as a contact-reaction expression reference; not the same protagonist as the selected scene series.
- `F01-talk.webp`: inspected as a speaking-expression reference; not the same protagonist as the selected scene series.

These non-runtime references must not be silently inserted merely to simulate hand/speech continuity.

## Motion reference boundary

The existing LoveTree `Supernova` benchmark shot map describes S10 as a bright medium close with a graphic hand gesture toward camera lasting about 0.625 seconds. B60 translates that camera/gesture grammar into contact timing, flash, depth, and inertial spatial motion. It does not copy the benchmark source video or the different-person S10 image.

The derivatives exist only to make repository review lightweight enough for the anchor. Their presence does not imply final B60 art approval.

No font files, credentials, private Drive identifiers, or personal data are included.
