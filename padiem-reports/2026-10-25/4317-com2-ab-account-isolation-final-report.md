## #4317 COM2 — A/B 계정 격리·계정 전환 잔재·첨부 문서 E2E 완료 (2026-10-25 KST)

**환경:** COM2 `K_LIPVOICE`, 기존 Chrome 로그인 세션을 BSK로 재사용, `https://chat.padiem.net`. CGI 로그인 환경 미사용. `/health` 200(runtime b14, image/text document attachment ready). 기준 main `7bc271a6e70` — 이번 작업에서 코드 변경 없음.

**계정:** A = 기존 owner Google 정식 로그인(서버 상태 signed_in, member_grade=max). B = 정식 회원가입 폼으로 생성한 합성 password 계정(서버 상태 signed_in, member_grade=free). 비밀번호·토큰·이메일·고객정보는 기록하지 않음.

| 항목 | 판정 | 근거 |
|---|---|---|
| DISTINCT_ACCOUNTS | PASS | 서버 `/api/auth/status`: A signed_in/max/Google, B signed_in/free/password — 별도 세션 |
| PROJECT_ISOLATION | PASS | B 프로젝트 목록 0건, A 프로젝트 직접 GET 404, A 프로젝트 files 404. A는 기존 프로젝트만 표시 |
| FILE_ISOLATION | PASS | B에서 A 파일 detail/original 404, B 프로젝트 경로에 A file ID 404; B 본인 file detail 200 |
| CONVERSATION_ISOLATION | PASS | B에서 A 대화 GET 404, 검색 A marker 0건/B marker 1건. A에서 B 대화 GET 404, 검색 B marker 0건/본인 제목 1건 |
| DIRECT_API_DENY | PASS | guest의 A 리소스 전부 401; B의 A 프로젝트 PATCH/DELETE 404. SPA에 대화·프로젝트 deep-link 경로가 없어 URL 접근은 API 권한 경계로 검증 |
| ACCOUNT_SWITCH_RESIDUE | PASS | A 로그아웃 후·B 로그아웃 후 DOM/localStorage/sessionStorage/cookie에서 A/B marker 0건, 뒤로가기 about:blank 잔재 0건. B 로그인 화면에서 A 데이터 0건 |
| A_RESTORE_INTEGRITY | PASS | Google 정식 로그인 복귀 후 기존 프로젝트(B67)·기존 대화 목록 유지, A/B 합성 데이터 0건 |
| ATTACHMENT_DOCUMENT_E2E | PASS | TXT 1건 첨부 후 모델 답변이 문서 값(ORCHID-4317, BLUE-LANTERN-9182, 2026-11-03 14:30, room B-217)을 그대로 재현, user/assistant 2메시지 저장 |
| BINARY_PDF_ATTACHMENT | NOT_VERIFIED | 운영 Worker는 격리 parser authority 부재로 PDF/DOCX/PPTX/XLSX를 의도적으로 fail-closed(#2824 S3-B)하고 명시적 오류를 반환. 첨부 선택기는 해당 형식을 계속 안내하는 UX 불일치가 있으나 이번 범위에서 코드 변경 없음 |
| SSE | 기존 PASS 재사용 | PR #5722/#5723, 배포 run 40060652141. 재검증 반복하지 않음 |

**정리:** 합성 A 프로젝트/파일/대화, B 프로젝트/파일/대화 삭제(삭제 후 404 확인). 기존 사용자 데이터 수정 0건. BSK 세션 종료. B 합성 계정은 데이터 없이 테스트 전용으로 잔존.

```text
STATUS=COMPLETE
PR=NONE (코드 변경 없음)
SHA=7bc271a6e708ae41872f89e9d6e0e08d3db47012 (main, 변경 없음)
TESTS=NONE (코드 변경 없음); 라이브 검증은 상기 표
MERGED=N/A
DEPLOYED=N/A (기존 배포 유지)
LIVE_VERIFIED=YES (A/B 격리·계정 전환 잔재·TXT 문서 E2E)
REMAINING=PDF/DOCX/PPTX/XLSX 운영 parser 미제공(by design), 첨부 선택기 안내 불일치
NEXT=격리 parser 도입 또는 첨부 선택기에서 미지원 형식 숨김 여부 owner 결정
```
