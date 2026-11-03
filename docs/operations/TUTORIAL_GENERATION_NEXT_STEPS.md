# 튜토리얼·영상 자동 생성 — 다음 단계 (#6724 2)

시나리오 대본에서 사용자 튜토리얼(`docs/help/tutorials/`)을 만들고, 게스트 장면을 실제 촬영하는 단계까지 들어왔습니다. 이 문서는 계정이 필요한 나머지와 미디어를 어디에 둘지 정리합니다.

## 지금 되는 것

- `python tools/tutorial/build_tutorials.py`가 01~05 대본을 튜토리얼 md로 만듭니다. 개발 용어는 표로 바뀌고, 계정 단계는 자리 표시로 남습니다.
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

권장: 지금은 키만 쓰고, 실제 파일은 R2에 두는 쪽이 저장소·배포 크기를 건드리지 않습니다. 앞단 정적 자산은 짧은 홍보 영상 1~2개로 제한합니다.

## 도움말 화면 연결

`apps/padiem-chat/static/help.html`은 지금 문장 예시 모음입니다. 튜토리얼을 붙이려면:

1. help.html 목차에 "단계별로 따라 하기" 항목을 추가하고 01~05로 링크합니다.
2. 링크 대상은 배포 산출물에 포함된 경로여야 합니다. 지금 `docs/help/tutorials`는 배포되지 않으므로, 다음 중 하나가 필요합니다.
   - Worker 라우트가 `docs/help/tutorials/*.md`를 읽어 HTML로 제공
   - 생성 단계에서 md를 `apps/padiem-chat/static/help/tutorials/`로 복사하는 스크립트 추가(정적 사이트 그대로 유지)
3. 이미지·영상은 키(`asset://chat-tutorial/…`)를 실제 URL로 바꾸는 매핑을 한 파일에 두고, 호스팅을 바꿔도 문서를 고치지 않게 합니다.
4. help.html의 "북AI" 절과 튜토리얼 04의 문구 차이는 `docs/help/tutorials/README.md` 표에 적었습니다. 화면 문구 통일은 별도 작업입니다.

## 확인 명령

```bash
python tools/tutorial/build_tutorials.py --check
python -m unittest discover -s tools/tutorial/tests -t tools/tutorial -v
python tools/tutorial/capture_guest_scenes.py --dry-run
```

촬영은 게스트 화면만 대상입니다. 로그인·결제·발송·삭제 버튼을 누르는 단계는 계정 확정 전까지 실행하지 않습니다.
