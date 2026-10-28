# Beta UX 점검 — SNS 화면 PC 마운트 실측 (2026-10-29)

관련: #5895(견적서·Util PC 참조 글), feat/beta-ux-pass-261029 세션 이어받기.
대상: apps/padiem-chat static/util-menu.js · static/index.html
방법: mock 서버(PADIEM_CHAT_RUNTIME_MODE=mock, 127.0.0.1:8795) + Playwright Chromium 1440×1000 실측.

## 결론

**SNS 화면의 PC 가져오기·저장은 모두 실제로 존재하고 보인다.** 이전 세션에서 우려했던
"index.html에 SNS용 PC 마운트 div가 없다"는 결함이 아니다 — SNS 패널은 첫 탭 활성화 때
`buildSns()`가 폼 전체를 지연 생성하고, 그 안에 `createPcReferenceSection()` 박스를
직접 붙이는 구조라 정적 마운트 div가 필요 없다(축사만 정적 마크업이라 `#utilSpeechPcRef`
마운트가 있는 것).

## 실측 결과 (mock, 미로그인 — /api/pc/pairings 401)

| 요소 | 셀렉터 | DOM | 노출 |
| --- | --- | --- | --- |
| 내 PC에서 예전 글 가져오기 | `#utilSnsForm .util-pc-ref-pick` | 있음 | **보임** (display:block) |
| PC 미연결 안내 note | `#utilSnsForm .util-pc-ref-note` | 있음 | 숨김(기본값) |
| 내 PC에 저장 | `#utilSnsPcSave` | 있음 | 생성 전 결과 영째(#utilSnsResult)가 display:none → **생성 후 보임**(114×44px 실측) |

- 미연결 판정은 `check()`가 `linked === false`(확정 미연결)일 때만 pick을 숨기고 note로
  대체한다. 401(판정 불가)에서는 pick을 유지한다 — "연결 안 됐다고 거짓 표시하지 않는"
  #5895 원칙과 일치.
- 캡처: 워크스페이스 beta-ux-captures/sns-pc-mount-261029.png,
  sns-pc-save-after-gen-261029.png (repo 외부).

## 베타 UX 후보(이번 스코프에서 손대지 않음)

1. SNS 폼 그리드 정렬: PC 참조 박스가 라벨·필드 그리드 한 칸에 끼어 플랫폼 탭 행과
   나란히 배치된다. 가져오기 버튼이 폼 중간에 뜬 칩처럼 보여 시선 동선이 어긋난다 —
   필드 아래 한 줄 배치가 자연스럽다.
2. 생성 전 "내 PC에 저장"이 결과 영째에 숨어 있는 것은 의도대로지만, 결과가 나오기 전에는
   PC 저장 경로가 화면에 존재하지 않는다(런처/요약에도 없음).
3. SNS 생성 실패 문구가 `생성 실패: <원문>`(예: "생성 실패: HTTP 502")로 그대로 노출된다
   (util-menu.js buildSns gen() catch). 한국어 사용자 문구로 바꿀 때 이 문구를 고정한
   테스트를 함께 고쳐야 한다(이전 세션 메모와 일치).

## 기타 확인

- utilSnsPanel은 index.html에서 `hidden` + "SNS 홍보 화면을 열 수 없습니다." 자리표시자로
  시작하고, 첫 활성화에서 buildSns()가 채운다(placeholder p는 그대로 남아 있음 —
  util-menu.css가 panel 내용을 덮어쓸 때 placeholder가 함께 남아 있는지 후속 확인 여지).
