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
- 산출물은 저장소 밖(기본 `<repo>/../out`)에만 둡니다: 단계 PNG, 뷰포트 프레임, 5초 장면 WebM, `captions.vtt`, `manifest.json`.
- 장면 영상은 촬영된 게스트 화면 프레임을 순서대로 5초씩 보여 줍니다. `ffmpeg`와 `ffprobe`가 필요합니다.
- 계정 세션 파일 이름은 `PADIEM_LIVE_STORAGE_STATE`로 정해 두었고 지금은 값이 없습니다. 파일은 절대 저장소에 넣지 않습니다.

## 계정 장면 촬영(대표 세션)

로그인 화면은 저장 상태 파일을 만들지 않고 Tabbit의 대표 세션으로 촬영합니다.

- **프레임**: 사이드바(폭 252px)를 빼고 `clip {x:252, y:0, width:1028, height:900}`로 본문만 찍습니다. 대화 제목·프로젝트명·계정 이름이 프레임에 들어오지 않습니다.
- **클릭**: `locator.click()`은 숨김 요소에서 타임아웃되므로 `page.evaluate(() => el.click())`로 실행합니다.
- **스크린샷**: PNG만 지원합니다. `timeout: 25000`으로 찍고 실패하면 `backdrop-filter`를 끄고 재시도합니다(계산 스타일 기준 backdrop-filter 55개·filter 21개).
- **대본 연결**: 촬영한 단계는 대본에 `**촬영한 단계:** 1, 2`로 적습니다. 그 단계만 이미지로 바뀌고 나머지 계정 단계는 자리 표시로 남습니다.
- **저장**: 원본 PNG는 저장소 밖 `out/`, 저장소에는 webp(장당 150KB 이하)만 넣습니다. 저장 전에 직접 열어 개인 정보 0건을 확인합니다.
- **대화 장면(주의)**: 대화 화면은 메시지 머리글과 아바타에 계정 실명이 그대로 나옵니다. 잘라내기만으로는 부족하므로 `.message-author`·아바타 영역을 좌표로 가린 뒤 저장해야 합니다. 2026-11-03 시도에서는 이름이 찍혀 01 6단계·왜 1–2단계를 반영하지 않았습니다. 또 모델 응답이 “AI 작업 상태 · 답변 준비 중”에서 90초 안에 끝나지 않아 완료 화면을 얻지 못했습니다.

## 화면 페이지

같은 대본이 도움말 화면 옆 정적 페이지도 만듭니다: `apps/padiem-chat/static/help-tutorials/`에 목차 1장 + 튜토리얼 5장 + `tutorial.css`.

- 도움말 화면과 같은 `styles.css`·`help.css`를 씁니다. 색·글자·44px 누름 영역을 새로 정하지 않습니다.
- 단계 화면은 촬영 PNG를 webp로 줄여 `assets/<문서>/step-NN.webp`로 저장소에 넣습니다(장당 150KB 이하, 현재 7장 약 640KB).
- 영상·자막은 저장소에 넣지 않습니다. 게스트 촬영이 끝난 01·02·04는 `PADIEM_TUTORIAL_MEDIA_BASE_URL=https://tutorial-media.padiem.net`의 버전 주소를 사용하고 `<video controls preload="none" crossorigin="anonymous">`와 한국어 자막 트랙을 보여 줍니다. R2 CORS는 `https://chat.padiem.net` 출처와 GET/HEAD, Range 헤더만 허용합니다. 촬영되지 않은 튜토리얼은 "영상 준비 중"으로 남습니다.
- R2 업로드는 `tutorials/<문서>/video.v20261103.webm`와 `captions.v20261103.vtt`를 사용합니다. 버전이 바뀌면 `tools/tutorial/build_tutorials.py`의 `MEDIA_VERSION`도 함께 올립니다.
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

생성 문서의 결정성·용어 치환·자리 표시·이미지 키, 커밋된 페이지·이미지 목록과 크기, 미디어 도메인 제한·버전 경로, `--check`가 잡는 어긋남(페이지 문구·이미지 누락·고아 파일), 도움말 링크 1곳, VTT 형식과 영상 길이 경계, 촬영 `--dry-run` 계획을 확인합니다.

## CI

`.github/workflows/tutorial-generation-contract.yml`이 대본·문서·페이지·이미지가 바뀌는 PR에서 `--check`, 단위 시험, `--dry-run`을 돕니다. 브라우저·서비스·네트워크가 필요 없어 `b62-browser-qa-unified.yml`(잡 수 고정)에는 넣지 않았습니다.
