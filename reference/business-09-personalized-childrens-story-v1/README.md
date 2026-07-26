# Business 9 · 우리 아이 이야기 — Phase 1 Visual UI Reference

## Status

- Phase: `Phase 1 — UI only`
- Portfolio mode: `UI_ONLY`
- Current verdict: `UI_NOT_READY`
- Product status: candidate / proposed-number
- Stable slug: `personalized-childrens-story`
- Runtime: static HTML, CSS, and minimal JavaScript
- Data: deterministic synthetic Korean copy only

## Product promise

> 아이의 실제 경험·관심·선택과 보호자의 교육 목표를 바탕으로, 다음 장이 계속 달라지는 개인화 이야기책을 만든다.

This workspace is a visual reference showing the intended finished-result direction. It does not implement a real story generator, account system, child-data intake, editor, approval flow, persistence, sharing, printing, payment, AI provider, API, database, or deployment.

## Visual direction

`Living Picture Book / 살아 움직이는 그림책`

The interface uses asymmetric book spreads, paper-cut layers, gouache-like color fields, pencil marks, print-style texture, chapter and page notation, quiet provenance, and restrained parent marginalia. The recurring proxy character is fictional and contains no identifying child data.

## Seven review states

1. 오늘의 이야기 표지
2. 이야기 펼침면
3. 아이의 하루가 바뀐 장면
4. 선택 뒤의 다음 장
5. 보호자 메모
6. 모바일 390px
7. Story Bloom / 이야기 피어남

The review rail and keyboard controls exist only to inspect these visual states. They are not accepted UX navigation.

## Review controls

- Click a numbered state in the desktop review rail.
- Use `ArrowLeft` / `ArrowRight` to move between states.
- Use `Home` / `End` to jump to the first or last state.
- Use the replay control in state 7 to replay Story Bloom.
- On narrow screens, use the previous/next review controls at the bottom.

## Run locally

```bash
cd reference/business-09-personalized-childrens-story-v1
python -m http.server 4179
```

Open `http://127.0.0.1:4179/`.

## Boundaries

- No real child name, face, school, address, schedule, message, or photo.
- No runtime network request.
- No external font, image, library, API, localStorage, or cookie.
- All illustration assets are repository-local originals and `reference-only`.
- Business 3 · Living Fiction remains a general-reader shared branching narrative platform. This workspace is a child-and-caregiver picture-book result reference centered on one fictional proxy child's everyday motifs.
