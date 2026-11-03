# 튜토리얼 도구 (#6724 2)

시나리오 대본(`docs/qa/scenarios/01~05`)에서 사용자 튜토리얼을 만들고, 게스트로 볼 수 있는 장면만 실제로 촬영합니다.

## 문서 생성

```bash
python tools/tutorial/build_tutorials.py           # docs/help/tutorials/ 생성
python tools/tutorial/build_tutorials.py --check   # 대본과 문서가 어긋났는지 확인
```

- 대본의 표(단계·동작 → 기대 화면·확인 지표·캡션)가 유일한 원본입니다. 문서를 손으로 고치면 다음 생성에서 사라집니다.
- 개발 용어는 `TERM_RULES` 표로 사용자 말로 바꿉니다(504 → 시간 초과, ms → 걸린 시간 등).
- 계정이 필요한 단계는 `[화면 준비 중 — 시험 계정 확정 후 촬영]` 자리로 남기고 화면을 지어내지 않습니다.
- 06 장애 복구는 운영 문서라 제외합니다.
- 출력은 결정적입니다. 같은 대본이면 같은 바이트가 나오고, 날짜·실행 ID를 넣지 않습니다.

## 촬영

```bash
python tools/tutorial/capture_guest_scenes.py --dry-run   # 브라우저 없이 단계 목록
python tools/tutorial/capture_guest_scenes.py --out ../out
```

- 게스트 장면만 찍습니다. 라우터가 GET/HEAD 외 요청을 브라우저에서 막고, 로그인·입력·제출을 하지 않습니다.
- 산출물은 저장소 밖(기본 `<repo>/../out`)에만 둡니다: 장면 PNG, `video.webm`, `captions.vtt`, `manifest.json`.
- 계정 세션 파일 이름은 `PADIEM_LIVE_STORAGE_STATE`로 정해 두었고 지금은 값이 없습니다. 파일은 절대 저장소에 넣지 않습니다.

## 시험

```bash
python -m unittest discover -s tools/tutorial/tests -t tools/tutorial -v
```

생성 문서의 결정성·용어 치환·자리 표시·이미지 키, VTT 형식, 촬영 `--dry-run` 계획을 확인합니다.
