# 튜토리얼·영상 자동 생성 — 다음 단계 (#6724 2)

시나리오 대본에서 사용자 튜토리얼(`docs/help/tutorials/`)을 만들고, 게스트 장면을 실제 촬영하는 단계까지 들어왔습니다. 이 문서는 계정이 필요한 나머지와 미디어를 어디에 둘지 정리합니다.

## 지금 되는 것

- `python tools/tutorial/build_tutorials.py`가 01~05 대본을 튜토리얼 md로 만듭니다. 개발 용어는 표로 바뀌고, 계정 단계는 자리 표시로 남습니다.
- 같은 명령이 도움말 화면 옆 정적 페이지(`apps/padiem-chat/static/help-tutorials/`, 목차 1장 + 튜토리얼 5장)를 만들고, 촬영 PNG를 webp로 줄여 저장소에 넣습니다.
- `help.html` 목차 첫 항목에서 `./help-tutorials/index.html`로 이어집니다.
- `python tools/tutorial/capture_guest_scenes.py`가 게스트 장면을 촬영해 PNG·WebM·VTT·manifest를 저장소 밖 `out/`에 남깁니다. GET/HEAD 외 요청은 브라우저에서 막습니다.
- `--check`와 단위 시험이 대본과 문서의 어긋남을 잡습니다.

## 시험 계정이 필요한 항목

| 시나리오 | 단계 | 필요한 것 | 지금 상태 |
|---|---|---|---|
| 01 첫 방문 | 4–6 | 로그인 세션, 첫 질문 1회 | 자리 표시 |
| 02 PC 연결 | 3–5 | 로그인, 시험 PC 등록·온라인, 연결 승인 | 자리 표시 |
| 03 문서 작업 | 1–3 | 로그인, 민감정보 없는 합성 문서 | 자리 표시 |
| 04 북AI | 2, 4 | 로그인, 북AI 세션, 두 번째 기기(빈 프로필) | 자리 표시 |
| 05 계정 탈퇴 | 1–3 | 기능 병합·활성화, 시험 계정 | 자리 표시(촬영하지 않음) |

세션 파일 이름은 `PADIEM_LIVE_STORAGE_STATE` 하나로 정했습니다. 값은 아직 없고, 파일은 저장소·GitHub Secrets에 넣지 않습니다. 계정이 확정되면 촬영 스크립트가 이 파일로 컨텍스트를 열어 계정 단계를 같은 키(`asset://chat-tutorial/<문서>/…`)에 이어 찍습니다.

## 영상·이미지 호스팅 후보

| 후보 | 장점 | 확인할 것 |
|---|---|---|
| R2 버킷 + Worker 서명/공개 경로 | 큰 영상, 캐시·범위 요청, 저장소와 분리 | 버킷 권한, 공개 범위, 비용, 키 규칙(`chat-tutorial/…`) |
| 앞단 정적 자산(`apps/padiem-chat/static`) | 배포가 단순하고 같은 출처 | 저장소 크기, 배포마다 늘어나는 바이너리, 캐시 무효화 |
| 문서 저장소 안에 두지 않음 | 저장소 비대화 방지 | 링크가 깨지지 않게 키→URL 매핑을 한 곳에서 관리 |

확정: 이미지는 앞단 정적 자산입니다. 촬영 PNG(장당 약 1MB)를 webp로 줄여 `apps/padiem-chat/static/help-tutorials/assets/<문서>/step-NN.webp`로 넣고, 장당 150KB·합계 약 640KB를 유지합니다. 생성 단계에서 크기를 넘으면 `--check`가 `image_too_large`로 멈춥니다.

영상·자막은 저장소에 넣지 않습니다. 페이지에는 "영상 준비 중" 자리만 있고, 나중에 고정 주소를 넣을 설정 키는 `PADIEM_TUTORIAL_MEDIA_BASE_URL` 하나입니다(예: `<키>/chat-tutorial/01-first-visit/video.webm`). 호스팅을 R2로 정하면 이 키 값만 채우면 되고 페이지는 다시 만들 필요가 없습니다.

## 도움말 화면 연결

`apps/padiem-chat/static/help.html`은 지금 문장 예시 모음입니다. 연결은 이렇게 마쳤습니다.

1. 목차 첫 항목 `단계별 튜토리얼` → `./help-tutorials/index.html` 한 곳. 본문 문구는 건드리지 않았습니다.
2. 페이지는 생성 단계에서 `apps/padiem-chat/static/`에 직접 만듭니다. 별도 복사 스크립트나 Worker 라우트가 필요 없고 정적 사이트 그대로입니다. `docs/help/tutorials`의 md는 사람이 읽는 사본, 화면은 같은 대본에서 나온 html입니다.
3. 이미지는 `./assets/<문서>/step-NN.webp` 고정 경로, 영상은 `PADIEM_TUTORIAL_MEDIA_BASE_URL` 키로 붙입니다. 호스팅을 바꿔도 페이지를 다시 만들 필요가 없습니다.
4. help.html과 다른 문구 2건은 `docs/help/tutorials/README.md`의 문안 제안 표에 있습니다. `help.html` 반영은 Chat 화면 담당이 합니다.
5. 대본·문서·페이지·이미지가 어긋나는 PR은 `.github/workflows/tutorial-generation-contract.yml`이 막습니다.

## 확인 명령

```bash
python tools/tutorial/build_tutorials.py --check
python -m unittest discover -s tools/tutorial/tests -t tools/tutorial -v
python tools/tutorial/capture_guest_scenes.py --dry-run
```

촬영은 게스트 화면만 대상입니다. 로그인·결제·발송·삭제 버튼을 누르는 단계는 계정 확정 전까지 실행하지 않습니다.
