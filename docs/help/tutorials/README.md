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

06 장애 복구는 운영 문서라 여기서 만들지 않습니다.

## 이미지·영상 키

튜토리얼은 상대 경로 대신 키로 미디어를 가리킵니다. 파일이 R2나 정적 자산으로 옮겨져도 문서를 고칠 필요가 없습니다.

| 종류 | 키 형식 | 예 |
|---|---|---|
| 단계 화면 | `asset://chat-tutorial/<문서>/step-NN.png` | `asset://chat-tutorial/01-first-visit/step-01.png` |
| 영상 | `asset://chat-tutorial/<문서>/video.webm` | `asset://chat-tutorial/01-first-visit/video.webm` |
| 자막 | `asset://chat-tutorial/<문서>/captions.vtt` | `asset://chat-tutorial/01-first-visit/captions.vtt` |

촬영 원본은 저장소에 넣지 않습니다(`tools/tutorial/capture_guest_scenes.py --out <폴더>`).

## 도움말 화면과의 관계

기존 도움말(`apps/padiem-chat/static/help.html`)과 겹치거나 다른 표현입니다. 이번 단계에서는 화면 문구를 고치지 않았습니다.

| 튜토리얼 문구 | 도움말 화면 문구 | 판정 |
|---|---|---|
| 컴퓨터 연결 설치 안내 | “컴퓨터 연결 설치 안내” | 같음 — 도움말의 같은 링크로 이어집니다. |
| 이 PC 연결하기 | “이 PC 연결하기” | 같음 — 버튼 이름이 같습니다. 튜토리얼은 누르는 순서를 설명합니다. |
| 북AI에서 읽기 기록을 남겨요. | “로그인하지 않아도 읽기 기록과 Memory가 이 기기에 저장돼요.” | 같음 — 기기에 저장되는 범위가 같습니다. |
| 로그인하면 다른 기기에서도 이어서 볼 수 있어요. | “파디엠 계정으로 로그인하면 계정에도 저장되어 다른 기기에서 이어져요.” | 표현만 다름 — 도움말은 저장 위치까지, 튜토리얼은 결과만 적습니다. |
| 로그인이 필요한 항목은 로그인 안내로 안전하게 막아요. | “되돌리기 어려운 동작으로 보일 때는 실행하기 전에 묻고” | 다름 — 도움말은 실행 전 확인, 튜토리얼 장면은 목록 접근 차단입니다. 문구 통일은 후속 과제입니다. |
| 계정 탈퇴 | (항목 없음) | 다름 — help.html에 탈퇴 항목이 아직 없습니다. |

## 화면 페이지

``apps/padiem-chat/static/help-tutorials``에 같은 대본으로 6장(목차 1장 + 튜토리얼 5장)을 만듭니다. 도움말 화면과 같은 ``styles.css``·``help.css``를 쓰고, 단계 화면은 ``assets/<문서>/step-NN.webp``로 저장소에 넣었습니다(장당 150KB 이하). 사용 안내(``help.html``) 목차에서 ``./help-tutorials/index.html``로 이어집니다.

영상과 자막은 저장소에 넣지 않습니다. 페이지에는 "영상 준비 중" 자리만 두고, 나중에 고정 주소를 넣을 설정 키는 ``PADIEM_TUTORIAL_MEDIA_BASE_URL``입니다(예: ``PADIEM_TUTORIAL_MEDIA_BASE_URL/<문서>/video.webm``).

## 도움말 문안 제안

``apps/padiem-chat/static/help.html``은 이 선에서 고치지 않습니다. 아래 두 곳은 내용이 다르므로 Chat 화면 담당이 반영합니다.

| 위치 | 지금 문구 | 제안 문구 | 이유 |
|---|---|---|---|
| help.html · 권한 안내(#policyTitle) 둘째 문단 | “되돌리기 어려운 동작으로 보일 때는 실행하기 전에 묻고,” | 로그인이 필요한 화면은 열기 전에 로그인 안내로 막고, 로그인·결제·게시·발송처럼 되돌리기 어려운 동작은 실행하기 전에 묻습니다. | 튜토리얼은 로그인 장면을 목록 접근 차단으로 설명하는데, 도움말은 실행 전 확인만 말합니다. |
| help.html · 목차와 새 절(#account) | “(항목 없음)” | 계정 탈퇴 — 설정의 계정 메뉴에서 탈퇴할 수 있어요. 확인을 위해 계정 이메일이나 정해진 확인 문구를 입력하고, 내 문서·대화 기록·첨부는 지워지며 공통 로그인 계정은 남습니다. | 튜토리얼 ⑤가 다루는 내용이 도움말에 없습니다. 탈퇴 기능이 병합된 뒤에 넣습니다. |

## 다시 만들기

```bash
python tools/tutorial/build_tutorials.py           # 문서 생성
python tools/tutorial/build_tutorials.py --check   # 문서가 최신인지 확인
python -m unittest discover -s tools/tutorial/tests -t tools/tutorial
python tools/tutorial/capture_guest_scenes.py --dry-run
```
