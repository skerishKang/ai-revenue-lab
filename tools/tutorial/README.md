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

## 화면 페이지

같은 대본이 도움말 화면 옆 정적 페이지도 만듭니다: `apps/padiem-chat/static/help-tutorials/`에 목차 1장 + 튜토리얼 5장 + `tutorial.css`.

- 도움말 화면과 같은 `styles.css`·`help.css`를 씁니다. 색·글자·44px 누름 영역을 새로 정하지 않습니다.
- 단계 화면은 촬영 PNG를 webp로 줄여 `assets/<문서>/step-NN.webp`로 저장소에 넣습니다(장당 150KB 이하, 현재 7장 약 640KB).
- 영상·자막은 저장소에 넣지 않습니다. 페이지에는 "영상 준비 중" 자리만 있고, 나중에 고정 주소를 넣을 설정 키는 `PADIEM_TUTORIAL_MEDIA_BASE_URL`입니다(예: `<키>/chat-tutorial/01-first-visit/video.webm`).
- 사용 안내(`help.html`) 목차에서 `./help-tutorials/index.html`로 한 번 이어집니다.
- 이미지를 다시 만들려면 Pillow가 필요합니다(`python -m pip install pillow`). `--check`와 단위 시험은 커밋된 webp를 이름·크기로만 보므로 Pillow 없이 돕니다.

```bash
python tools/tutorial/build_tutorials.py --shots ../out     # 문서 + 페이지 + 이미지
python tools/tutorial/build_tutorials.py --no-images         # 문서 + 페이지만
```

## 시험

```bash
python -m unittest discover -s tools/tutorial/tests -t tools/tutorial -v
python tools/tutorial/build_tutorials.py --check
```

생성 문서의 결정성·용어 치환·자리 표시·이미지 키, 커밋된 페이지·이미지 목록과 크기, `--check`가 잡는 어긋남(페이지 문구·이미지 누락·고아 파일), 도움말 링크 1곳, VTT 형식, 촬영 `--dry-run` 계획을 확인합니다.

## CI

`.github/workflows/tutorial-generation-contract.yml`이 대본·문서·페이지·이미지가 바뀌는 PR에서 `--check`, 단위 시험, `--dry-run`을 돕니다. 브라우저·서비스·네트워크가 필요 없어 `b62-browser-qa-unified.yml`(잡 수 고정)에는 넣지 않았습니다.
