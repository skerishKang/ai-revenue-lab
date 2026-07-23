# Preview Video Sources — Issue #76

All videos below are real, public YouTube videos. Every entry was verified via the
YouTube oEmbed endpoint (`https://www.youtube.com/oembed?url=...&format=json`) and the
watch page (`ytInitialPlayerResponse`) on 2026-07-23. Titles and channel names are
verbatim from YouTube. No YouTube Data API calls are made by the app or the build.

Totals: 11 videos · 9 distinct channels · 4 Korean + 7 English.

## English videos

| # | Video ID | Title (verbatim) | Channel | Duration | Views | Published | Topic | State |
|---|---|---|---|---|---|---|---|---|
| 1 | `aircAruvnKk` | But what is a neural network? \| Deep learning chapter 1 | 3Blue1Brown | 18:40 | 23,733,305 | 2017-10-05 | AI fundamentals | in_progress |
| 2 | `eMlx5fFNoYc` | Attention in transformers, step-by-step \| Deep Learning Chapter 6 | 3Blue1Brown | 26:09 | 4,324,680 | 2024-04-07 | AI fundamentals | saved |
| 3 | `rfscVS0vtbw` | Learn Python - Full Course for Beginners [Tutorial] | freeCodeCamp.org | 4:26:52 | 49,019,598 | 2018-07-11 | Software development | in_progress |
| 4 | `arj7oStGLkU` | Inside the Mind of a Master Procrastinator \| Tim Urban \| TED | TED | 14:04 | 61,610,385 | 2016-04-06 | Productivity | completed |
| 5 | `lkIFF4maKMU` | 100+ JavaScript Concepts you Need to Know | Fireship | 12:23 | 2,989,358 | 2022-11-22 | Software development | opened |
| 6 | `5C_HPTJg5ek` | Rust in 100 Seconds | Fireship | 2:29 | 2,457,399 | 2021-10-12 | Software development | revisit |
| 7 | `SzJ46YA_RaA` | Map of Computer Science | Domain of Science | 10:58 | 6,806,910 | 2017-09-06 | Learning maps | unseen |

## Korean videos

| # | Video ID | Title (verbatim) | Channel | Duration | Views | Published | Topic | State |
|---|---|---|---|---|---|---|---|---|
| 8 | `OIY2tWT3HHI` | 전공생이 알려주는 AI(인공지능) 필수지식, 누구든 10분이면 이해 끝 \| [허성범의 AI학개론]  -1강 | 허성범 Horang | 20:10 | 644,686 | 2025-02-23 | AI fundamentals | saved |
| 9 | `kWiCuklohdY` | 파이썬 코딩 무료 강의 (기본편) - 6시간 뒤면 여러분도 개발자가 될 수 있어요 [나도코딩] | 나도코딩 | 6:01:27 | 5,878,254 | 2020-02-20 | Software development | in_progress |
| 10 | `3GRt5XUKCPQ` | [EN] [이지영 Official] 성공한 사람들의 시간 관리 비법 | 이지영 [Leejiyoung Official] | 12:46 | 2,835,789 | 2020-07-20 | Productivity | completed |
| 11 | `ZT1UZQCTj_U` | 나만 모르고 있는 UI 디자인을 위한 10가지 원칙 | Madia Designer | 9:51 | 151,507 | 2022-06-16 | Design | opened |

## URLs (derived, deterministic)

For each video ID `{id}`:
- Watch URL: `https://www.youtube.com/watch?v={id}`
- Thumbnail: `https://i.ytimg.com/vi/{id}/hqdefault.jpg` (480×360; displayed in a 16:9
  container with `object-fit: cover`)
- Channel pages: `https://www.youtube.com/@3blue1brown`, `@freecodecamp`, `@TED`,
  `@Fireship`, `@ScienceMaps`, `@horangwave`, `@nadocoding`, `@leejiyoung_official`,
  and Madia Designer (`https://www.youtube.com/@UXUIDesign`).

## Fixture mapping

- Topics: "AI 기초 / AI fundamentals" (videos 1, 2, 8), "소프트웨어 개발 / Software
  development" (3, 5, 6, 9), "생산성 / Productivity" (4, 10), "학습 지도 / Learning maps"
  (7), "디자인 / Design" (11).
- All eight viewing states (`all unseen opened saved in_progress completed revisit
  irrelevant`) are exercised across the fixture set; `irrelevant` is represented by a
  topic-level filtered-out entry, not by mislabeling a real video.
- Provenance mix: `youtube` (found by search), `application` (recommended by the app's
  rule), `user` (added from a private record).
- Views/dates shown in the UI are the values above, formatted per locale
  (`조회수 23,733,305회` / `23,733,305 views`); they are static fixture metadata captured
  on the verification date, not live API data.

## Policy compliance

- Original titles, channels, and thumbnails are preserved (no fake pairing).
- Outbound links open in a new tab with `rel="noopener noreferrer"`; no autoplay, no
  iframes, no trackers, no YouTube API calls.
- CSP `img-src` allowlist for thumbnails: `https://i.ytimg.com` only.
