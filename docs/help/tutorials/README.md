# 사용자 튜토리얼

`docs/qa/scenarios`의 시나리오 대본에서 자동으로 만든 사용자 안내입니다. 대본을 고치고 `python tools/tutorial/build_tutorials.py`를 다시 실행하면 이 폴더가 바뀝니다. 손으로 고친 내용은 다음 생성에서 사라집니다.

## 문서

| 번호 | 문서 | 대상 | 게스트 단계 | 계정 단계 |
|---|---|---|---|---|
| 01 | [① 처음 온 사람](01-first-visit.md) | 첫 화면에서 로그인 경로를 찾고 첫 질문과 답변까지 확인합니다 | 1–3 | 4–6 |
| 02 | [② PC 연결](02-pc-connection.md) | 설치 안내에서 PC 연결 승인 뒤 자연어 파일 검색까지 확인합니다 | 1–2 | 3–5 |
| 03 | [③ 문서 작업](03-document-work.md) | 민감정보가 없는 합성 문서를 올리고 요약한 뒤 내려받습니다 | 없음 | 1–3 |
| 04 | [④ 북AI](04-bookai.md) | 게스트 기기 저장과 로그인 뒤 다른 기기에서 이어 보기를 확인합니다 | 1, 3 | 2, 4 |
| 05 | [⑤ 계정 탈퇴](05-account-deletion.md) | 탈퇴 기능이 병합된 뒤 확인 단계와 안내 범위를 대본화합니다 | 없음 | 1–3 |
| 07 | [⑦ 외부 AI 연결](07-external-ai-connect.md) | ChatGPT·Claude 같은 외부 AI 앱의 커넥터에 이 채팅의 MCP 주소를 넣고 로그인·승인해 PC 작업을 맡기는 흐름을 확인합니다 | 없음 | 1–4 |

06 장애 복구는 운영 문서라 여기서 만들지 않습니다.
⑦ 외부 AI 연결은 대본만 있고, ``help.html``에 [실제 연결 확인 전] 표시가 남아 있는 동안은 화면을 촬영하지 않습니다.

## 이미지·영상 키

튜토리얼은 상대 경로 대신 키로 미디어를 가리킵니다. 파일이 R2나 정적 자산으로 옮겨져도 문서를 고칠 필요가 없습니다.

| 종류 | 키 형식 | 예 |
|---|---|---|
| 단계 화면 | `asset://chat-tutorial/<문서>/step-NN.png` | `asset://chat-tutorial/01-first-visit/step-01.png` |
| 영상 | `asset://chat-tutorial/<문서>/video.webm` | `asset://chat-tutorial/01-first-visit/video.webm` |
| 자막 | `asset://chat-tutorial/<문서>/captions.vtt` | `asset://chat-tutorial/01-first-visit/captions.vtt` |

촬영 원본은 저장소에 넣지 않습니다(`tools/tutorial/capture_guest_scenes.py --out <폴더>`).
공개 영상은 `tutorials/<문서>/video.v20261103.webm`, `captions.v20261103.vtt`로 R2에 올립니다.

## 도움말 화면과의 관계

기존 도움말(`apps/padiem-chat/static/help.html`)과 겹치거나 다른 표현입니다. 이번 단계에서는 화면 문구를 고치지 않았습니다.

| 튜토리얼 문구 | 도움말 화면 문구 | 판정 |
|---|---|---|
| 컴퓨터 연결 설치 안내 | “컴퓨터 연결 설치 안내” | 같음 — 도움말의 같은 링크로 이어집니다. |
| 이 PC 연결하기 | “이 PC 연결하기” | 같음 — 버튼 이름이 같습니다. 튜토리얼은 누르는 순서를 설명합니다. |
| 북AI에서 읽기 기록을 남겨요. | “로그인하지 않아도 읽기 기록과 Memory가 이 기기에 저장돼요.” | 같음 — 기기에 저장되는 범위가 같습니다. |
| 로그인하면 다른 기기에서도 이어서 볼 수 있어요. | “파디엠 계정으로 로그인하면 계정에도 저장되어 다른 기기에서 이어져요.” | 표현만 다름 — 도움말은 저장 위치까지, 튜토리얼은 결과만 적습니다. |
| 로그인이 필요한 항목은 로그인 안내로 안전하게 막아요. | “로그인이 필요한 화면은 열기 전에 로그인 안내로 막습니다.” | 같음 — 도움말이 로그인 차단과 실행 전 확인을 함께 말합니다. |
| 계정 탈퇴 | “입력이 계정 이메일과 다르면 아무것도 지워지지 않습니다.” | 같음 — 도움말 #account 절이 이메일 재입력 확인과 같은 범위를 적습니다. |

## 화면 페이지

``apps/padiem-chat/static/help-tutorials``에 같은 대본으로 6장(목차 1장 + 튜토리얼 5장)을 만듭니다. 도움말 화면과 같은 ``styles.css``·``help.css``를 쓰고, 단계 화면은 ``assets/<문서>/step-NN.webp``로 저장소에 넣었습니다(장당 150KB 이하). 사용 안내(``help.html``) 목차에서 ``./help-tutorials/index.html``로 이어집니다.

영상과 자막은 저장소에 넣지 않습니다. 게스트로 촬영한 01·02·04 페이지에는 ``PADIEM_TUTORIAL_MEDIA_BASE_URL``로 지정한 ``https://tutorial-media.padiem.net``의 버전 주소를 붙이고, 촬영되지 않은 튜토리얼은 "영상 준비 중"으로 남깁니다.

영상은 익명 CORS 모드로 자막을 불러옵니다. R2 CORS는 ``https://chat.padiem.net`` 출처와 GET/HEAD, Range 헤더만 허용합니다.

## 도움말 문안 대조(반영됨)

``apps/padiem-chat/static/help.html``에 아래 두 문안을 반영했습니다. 다음에 문구를 바꿀 때 근거를 볼 수 있게 표로 남깁니다.

| 위치 | 이전 문구 | 지금 문구 | 근거 |
|---|---|---|---|
| help.html · 권한 안내(#policyTitle) 둘째 문단 | “되돌리기 어려운 동작으로 보일 때는 실행하기 전에 묻고,” | 로그인이 필요한 화면은 열기 전에 로그인 안내로 막습니다. 로그인·결제·게시·발송처럼 되돌리기 어려운 동작은 실행하기 전에 묻습니다. | 반영됨 — 비로그인 요청은 401 로그인 안내(시나리오 01 3단계), 되돌리기 어려운 동작은 실행 전 확인. |
| help.html · 목차와 새 절(#account) | “(항목 없음)” | 설정 > 계정 > 계정 탈퇴 → 이메일을 다시 입력해 영구 탈퇴 버튼이 켜질 때만 실행. 지워지는 것: 대화·프로젝트 파일·첨부·일정·PC 연결 설정. 남는 것: 공통 로그인 계정·외부 백업·PC 백업 폴더. | 반영됨 — POST /api/account/delete의 정확한 이메일 대조, locale.js account-delete-*, ACCOUNT_DELETION_20261103.md 표. |

## 다시 만들기

```bash
python tools/tutorial/build_tutorials.py           # 문서 생성
python tools/tutorial/build_tutorials.py --check   # 문서가 최신인지 확인
python -m unittest discover -s tools/tutorial/tests -t tools/tutorial
python tools/tutorial/capture_guest_scenes.py --dry-run
```
