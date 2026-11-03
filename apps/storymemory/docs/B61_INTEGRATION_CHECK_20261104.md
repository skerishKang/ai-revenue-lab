# B61 통합 점검 결과 — 2026-11-04

상태: 통합 확인 전용 브랜치. 이 브랜치는 머지 대상이 아니다.  
기준: `origin/main` `9dfb31e63`에서 생성했다.

## 통합 순서와 충돌

1. `fix/b61-6470-evidence-verses-261104` — `cae27ce3`
2. `fix/b61-6473-6472-261104` — `6037fb2`
3. `feat/b61-6474-verse-search-261104` — 처음 `6de9f2719`, 점검 중 추가된 최신 검색 인덱스 커밋 `8f9b7af10`도 후속 merge로 반영
4. `fix/b61-6475-translation-a11y-261104` — 통합 당시 `bf024ff`

Git 충돌 파일과 미해결 충돌 덩어리는 없었다. 네 브랜치가 함께 수정한 `apps/storymemory/public/index.html`은 서로 다른 구간을 Git이 자동 병합했다. 충돌 파일째 한쪽을 선택한 곳은 없다. 통합 뒤 6474 검색 브랜치가 갱신되어 검색 인덱스 추가 변경을 이어 합쳤으며, 관련 검색 시험을 최신 코드로 다시 실행했다.

## 390px 화면 흐름

Light와 Dark 각각에서 첫 화면 → 책 선택 → 사도행전 9장 → 읽기 → 본문 검색·결과 이동·읽던 위치 복귀 → 메모 입력·저장 → Memory 재열기 → AI 질문·응답까지 로컬 가짜 AI 응답으로 완료했다.

- 문서·본문 가로 넘침: 없음 (`document`와 `body` 너비 390px).
- 검색 결과, 본문, Memory/AI 패널에서 텍스트나 화면 요소가 서로 겹치는 문제: 재현하지 못했다.
- 390×520 축소 viewport를 키보드가 열린 상황의 대용으로 사용했다. 입력창은 y=440, 높이 44px로 viewport 안에 남았다. 네이티브 휴대폰 키보드 자체를 띄운 검증은 아니다.
- 터치 영역이 작은 컨트롤: 장 선택 점 버튼 약 20×5px, `새 메모` 36×16px, 메모 저장 81×29px. 장 선택 점은 장 이동에 사용되며 세 컨트롤 모두 44px 기준에 못 미친다. 책 열기·장 열기·하단 Memory/AI 탭·질문 입력은 높이 44px 이상이었다.
- Dark Memory 패널은 제목과 닫기 표시의 대비가 낮아 거의 읽히지 않는다. `storymemory-b61-overrides-v1.css`의 `.memory-rail .side-head strong`가 기본 `--ink`를 사용하고, Dark 배경에서 그 색이 밝게 바뀌지 않는 것으로 확인했다.
- Light 읽기 설정에서도 첫 라이브러리 화면은 어두운 고정 팔레트다. 책 목록과 읽기 화면에서는 Light 팔레트가 보인다. 첫 화면이 설정 범위 밖인 것이 의도인지 확인이 필요하다.

화면 캡처는 저장소 밖 `D:\PADIEM\b61-integration-evidence-261104\`에 있다. 대표 화면: `light-01-library.png`, `light-04-reader.png`, `light-05-search-results.png`, `light-07-memory.png`, `light-08-ai-keyboard.png`, `light-09-ai-answer.png`, Dark는 같은 이름 접두사의 파일이다. 검색 전용 시험 캡처는 `search-390.png`다. 이미지 파일은 저장소에 추가하지 않았다.

## 시험

| 대상 | 실행 | 결과 |
|---|---|---|
| 근거 표시 + 최신 검색 인덱스 | `node --test apps/storymemory/tests/evidence-verses.test.cjs apps/storymemory/tests/bible-search-index.test.cjs` | 8 passed. 인덱스가 원본 31,098절과 10개 표본 검색어에 일치 |
| 구절 참조 파서·본문 검증 | `node apps/storymemory/tests/bible-reference.test.cjs` | passed |
| 검색 브라우저 | `node apps/storymemory/tests/bible-search.browser.cjs` | 390px 직접 구절 검색, 전체 검색, 취소, 임시 shard 실패 재시도, 한 장 미리보기·복귀 모두 passed; 브라우저 콘솔/페이지 오류 0 |
| #6473/#6472 및 #6475 설정·접근성 | `python -m pytest -q --basetemp C:\pt\b61-integration apps/storymemory/tests/test_storymemory_6473_6472.py apps/storymemory/tests/test_reader_translation_a11y_6475.py` | 3 passed |
| Light/Dark 전체 모바일 흐름 | 로컬 Playwright, AI 응답은 가짜 응답으로 고정 | 두 테마 모두 전체 흐름 완료, 요청 실패·HTTP 오류·페이지 오류 0 |

운영 앱 접속, 계정 로그인, 배포는 하지 않았다.