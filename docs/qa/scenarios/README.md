# PADIEM 시나리오 대본

사람이 읽는 단계와 브라우저 실행, 캡처·영상·요약 JSON을 같은 시나리오 이름으로 맞춥니다. 문구는 Chat과 북AI 화면 소스에서 확인했습니다.

## 실행

저장소 루트에서 python -m pytest -c apps/padiem-chat/pyproject.toml apps/padiem-chat/tests/live_scenarios -m live -q 로 실행합니다. 대상은 PADIEM_LIVE_BASE_URL이며 기본 주소는 https://chat.padiem.net 입니다. 산출물은 PADIEM_LIVE_ARTIFACTS 또는 실행 폴더의 live-artifacts/에 저장하고 Git에서 제외합니다.

로그인 시나리오는 외부에서 준비한 PADIEM_LIVE_STORAGE_STATE 파일만 사용합니다. 변수가 비어 있거나 파일이 없으면 test_account_missing으로 건너뜁니다. 북AI는 파일이 있어도 북AI 세션이 없으면 같은 사유로 건너뜁니다. 자동 로그인·비밀번호 입력·세션 저장은 하지 않습니다. 이번 운영 확인은 GET만 허용하며, 세션 파일이 없어서 로그인 시나리오는 건너뜁니다.

| 파일 | 목적 | 사전 조건 |
|---|---|---|
| 01-first-visit.md | 첫 화면과 첫 질문 | 첫 화면 게스트, 질문은 로그인 세션 |
| 02-pc-connection.md | 설치 안내부터 PC 검색 | 로그인·기기 승인·연결된 PC |
| 03-document-work.md | 문서 첨부·요약·다운로드 | 로그인·합성 시험 문서 |
| 04-bookai.md | 읽기 기록과 다른 기기 이어 보기 | 기기 저장 게스트 가능, 계정 동기화는 로그인 |
| 05-account-deletion.md | 계정 탈퇴 안전 확인 | 기능 머지 뒤 실행 |
| 06-disaster-recovery.md | 임시 폴더 백업 복원 | 컴2 레인·로컬 백업·키 환경 변수 |

각 실행은 단계별 캡처, ms, HTTP 상태, 504 여부를 JSON에 기록합니다. 시나리오별 WebM 녹화와 튜토리얼 Markdown은 같은 산출 폴더에 생성합니다. 장애 복구 스크립트는 임시 데이터 폴더만 대상으로 하며 이 실행에서는 돌리지 않습니다.

화면 근거: apps/padiem-chat/static/index.html, help.html, install.html, app.js; 북AI apps/bookai/public/index.html 및 bookai-bootstrap.js. 문구가 바뀌면 대본과 시나리오 계약 시험을 함께 갱신합니다.

튜토리얼 생성: python apps/padiem-chat/scripts/build_live_tutorial.py <result.json> --output <tutorial.md>. 결과 JSON의 캡션으로 단계 캡처를 연결하며 영상 목록과 단계 시각표를 남깁니다. 편집·자막 합성은 하지 않습니다.

사용자 튜토리얼 생성: python tools/tutorial/build_tutorials.py 가 01~05 대본을 docs/help/tutorials/로 바꾸고, python tools/tutorial/capture_guest_scenes.py 가 게스트 장면만 촬영합니다. 계정이 필요한 단계는 자리 표시로 남습니다(도구 설명: tools/tutorial/README.md).

장애 복구: deploy/host-com2/offsite-backup/run_live_chat_restore.sh 는 백업을 임시 디렉터리에 복원하고 PADIEM_CHAT_LOCAL_DATA_DIR을 임시 데이터 폴더로 지정해 Chat을 띄운 뒤 GET /와 GET /health만 확인합니다. COM2_OFFSITE_KEY_FILE과 COM2_OFFSITE_KEY_ID는 환경 변수로만 읽습니다. 운영 호스트에서 실행하지 않습니다.
