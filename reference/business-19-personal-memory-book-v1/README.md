# Proposed Business 19 — Personal Memory Book Phase 1 UI

Status: `UI_REVIEW_READY`

This directory contains a static, synthetic Phase 1 visual reference for **Personal Memory Book / 나의 기억책** under the concept **Evidence Album / 기억의 증거 앨범**.

## Scope

- seven representative visual states;
- local original SVG assets only;
- Korean-first copy;
- deterministic state switching for visual review;
- Provenance Reveal signature motion;
- responsive desktop, tablet and 390px mobile composition;
- synthetic fixture labels and date-confidence treatment.

## Run

Serve this directory as static files, for example:

```bash
python -m http.server 4179 --directory reference/business-19-personal-memory-book-v1
```

Then open:

```text
http://127.0.0.1:4179/?state=cover
```

States: `cover`, `chapter`, `sources`, `recollections`, `timeline`, `review`, `mobile`.

## Non-implementation

No upload, OCR, transcription, facial recognition, real family data, comments, collaboration, printing, login, persistence, genealogy search, real AI, accepted UX or backend is implemented.

## Synthetic fixture

All people, photographs, dates, quotations and evidence objects in the interface are synthetic. The scenario uses fictional `김서연 가족` records around `1998년 늦여름, 솔빛역 앞 작은 사진관`.
