# Business 11 · Language Learning Magazine — Phase 1 Visual UI Reference

## Status

- Product: **나의 언어학습 매거진 / Language Learning Magazine**
- Phase: **UI_ONLY / Phase 1 visual reference**
- Current verdict: **UI_NOT_READY**
- Issue: `#172`
- Parent queue: `#154`
- Exact starting base: `48807067a261d8f1ca3814b4b26758dd6947788a`
- Target branch: `feat/business-11-language-learning-magazine-ui`
- Allowed scope: `reference/business-11-language-learning-magazine-v1/**`
- Asset version token: `language-learning-magazine-20260726-1`
- Status marker: `reference-only`

This directory is a static visual reference. It does not implement accepted UX, live language assessment, AI tutoring, current-news ingestion, authentication, persistence, APIs, databases, notifications, subscriptions, payments, or deployment.

> 모든 기사·학습 문장·피드백은 시각 검토를 위해 만든 합성 콘텐츠입니다.

## Product promise

> 학습자의 수준과 관심사에 맞춰 매일 읽을거리·어휘·질문·피드백을 한 호의 개인 언어 매거진으로 편집한다.

## Visual direction

**Bilingual Field Journal / 나의 언어 탐사 매거진**

The reference uses a warm paper field, black editorial ink, one vivid language accent, a restrained annotation blue, large English feature typography, Korean-first interface labels, and close-reading marks. It should read as a premium independent magazine annotated for one learner rather than as a language-learning dashboard.

## Synthetic issue

- Target language: English
- Korean support: concise interface labels and editorial notes
- Learner marker: `Intermediate · B1 참고 수준`
- Issue: `No. 011 · Evening Edition`
- Date: `2026.07.26`
- Theme: **How a Small Bookshop Changes a Neighborhood After Dark**

## Seven review states

1. `cover` — 오늘의 언어 매거진
2. `reading` — 오늘의 읽기
3. `vocabulary` — 문맥 속 어휘
4. `revision` — 한 문장 다시 보기
5. `feedback` — 이번 호 피드백
6. `mobile` — 모바일 390px composition
7. `motion` — Margin Echo / 여백 메아리

The controls exist only to inspect the seven visual states. They are not an accepted navigation model.

## Run

```bash
python3 -m http.server 4173 --directory reference/business-11-language-learning-magazine-v1
```

Open `http://127.0.0.1:4173/index.html#cover`.

## Explicit boundaries

- No progress ring, streak, XP, badge, score, grade, ranking, flashcard game, or test dashboard.
- No chat bubbles, AI avatar, model selector, AI sparkle, or generic purple gradient.
- No school worksheet grid or teacher-management surface.
- No actual learner record, copyrighted article, live news, or commercial publication branding.
- No final adaptive learning workflow.
- Business 4 remains the broad adaptive lesson product; Business 11 is a recurring editorial publication whose primary artifact is one finished issue.

## Evidence policy

Text validation evidence is committed under `evidence/**`. Binary screenshots and motion captures are produced separately and must not be claimed as committed unless they are present in the Git tree.
