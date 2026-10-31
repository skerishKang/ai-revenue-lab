# 화면 자산 출처 (ATTRIBUTION)

이 프로토타입이 실제로 내보내는 **이미지 7장**과 **웹폰트 7종**의 출처·변형·사용 조건 기록.
`tests/test_parliament_prototype.py`가 이 파일을 읽어, 자산마다 출처가 적혀 있는지 확인한다.

## 웹폰트 (Pretendard · MaruBuri)

한때 이 프로토타입은 CSS에 폰트 이름만 선언하고 파일을 싣지 않았다. 그래서 선언은
`Pretendard`·`NanumMyeongjo`인데 실제 렌더는 `Noto Sans KR`·`Batang`인 상태였다 — 보는 사람의
설치 폰트에 따라 화면이 달라졌다. B2 확정안(제목 마루부리 + 본문 Pretendard)과 함께 파일을
자체 호스팅해서 선언과 렌더를 일치시켰다.

| 파일 | 패밀리/가중치 | 출처 | 라이선스 | 변형 |
|---|---|---|---|---|
| `fonts/Pretendard-Regular.woff2` | Pretendard 400 | 공식 `pretendard-subset.css`가 가리키는 subset 빌드 (jsDelivr / GitHub `orioncactus/pretendard`) | **SIL OFL 1.1**, Reserved Font Name 'Pretendard' | 없음 — 공식 woff2 그대로 |
| `fonts/Pretendard-Medium.woff2` | Pretendard 500 | 〃 | 〃 | 없음 |
| `fonts/Pretendard-SemiBold.woff2` | Pretendard 600 | 〃 | 〃 | 없음 |
| `fonts/Pretendard-Bold.woff2` | Pretendard 700 | 〃 | 〃 | 없음 |
| `fonts/MaruBuri-Regular.woff2` | MaruBuri 400 | 공식 TTF `hangeul.pstatic.net/.../MaruBuri-Regular.ttf` | **네이버 글꼴** (저작권 © NAVER Corp. / NAVER Cultural Foundation) | TTF→WOFF2 컨테이너 변환만 |
| `fonts/MaruBuri-Bold.woff2` | MaruBuri 700 | 공식 TTF `.../MaruBuri-Bold.ttf` | 〃 | 〃 |
| `fonts/PlayfairDisplay-Bold-latin.woff2` | Playfair Display 700 (latin 서브셋) | Google Fonts v40 latin 블록이 가리키는 woff2 | **SIL OFL 1.1**, Reserved Font Name 'Playfair Display' | 없음 — 배포 빌드 그대로 |

- 고지문 동봉: `fonts/LICENSE-Pretendard-OFL-1.1.txt`(OFL 1.1 전문), `fonts/LICENSE-MaruBuri-NAVER.txt`(저작권 표기·라이선스 요지·영문 요약·변형 내역). 두 파일 모두 글꼴 파일과 같은 디렉터리에 둔다.
- 마루부리 변환은 컨테이너만 바꿨다. fontTools로 변환 전후를 대조해 **glyph 12466 / cmap 12398 / family·style·unitsPerEm 동일**을 확인했고, 용적만 Regular 3.12→0.41 MB, Bold 3.20→0.43 MB가 됐다. 글자 모양·전진폭·커닝은 그대로이므로 이름을 바꾸지 않았다.
- Pretendard subset 빌드는 한자·일어를 덜어낸 한국어+라틴 서브셋이다. **OFL의 Reserved Font Name 조항**에 따라 우리가 직접 서브셋을 추가 생성할 때는 'Pretendard' 이름을 그대로 쓰면 안 되고 이름을 바꿔야 한다. 지금은 공식 산출물을 그대로 받으므로 해당하지 않는다.
- CSS는 이 6개 파일만 `@font-face`로 선언하고, 화면이 요구하는 `font-weight`는 400/500/600/700 네 값만 쓴다. 면이 없는 650·750는 쓰지 않도록 정규화했다(근사면이 조용히 골라지는 것을 막기 위한 계약이며 테스트가 강제한다).
- Playfair Display 는 us/uk/fr 의 **라틴 제목에만** 쓴다(`--font-display` 첫 면). 한글 제목은 마루부리가 담당하고, 한국 테마의 스택은 바꾸지 않았다. 파일은 Google Fonts 가 배포하는 latin 서브셋 woff2(318 glyph, 23,224 bytes, sha256 28453852…)를 변형 없이 싣는다. licence 전문은 `fonts/LICENSE-PlayfairDisplay-OFL-1.1.txt`.
- 원격 폰트 CDN은 쓰지 않는다. `@import`·원격 `url()` 금지가 이 저장소의 네트워크 0 계약과 같은 선상에 있다.

## 해외 히어로 사진 3장 — Wikimedia Commons

라이선스는 Commons API(`prop=imageinfo&iiprop=extmetadata`)로 조회한 값을 근거로 적는다.
파일 페이지를 직접 확인하지 않은 값은 쓰지 않았다.

| 파일 | 장소 | 원본 URL | 저작자 | 라이선스 | 변형 |
|---|---|---|---|---|---|
| `parliament-uk-hero.jpg` | 웨스트민스터 궁과 빅벤(템스강에서, dusk) | https://commons.wikimedia.org/wiki/File:Westminster_and_big_ben.jpg | Farruk Ahmed Bhuiyan | **CC BY-SA 4.0** (저작자·라이선스 표기 필요) | 3840×2160 → 2560×1440, JPEG q82 재인코딩, EXIF/GPS 제거 |
| `parliament-us-hero.jpg` | 미국 국회의사당 서면 | https://commons.wikimedia.org/wiki/File:Capitol_Building_Full_View.jpg | Noclip | **퍼블릭 도메인** | 3840×1646 → 2560×1097, 〃 |
| `parliament-fr-hero.jpg` | 팔레 부르봉(국민의회) 열주와 삼색기 | https://commons.wikimedia.org/wiki/File:Palais_Bourbon,_Paris_7e,_NW_View_140402_1.jpg | DXR | **퍼블릭 도메인** | 3840×2302 → 2560×1535, 〃 |

- 세 장 모두 **실제 그 나라의 의회 건물**이다. 다른 나라 건물을 섞거나 실존 인물의 활동 사진을 만들지 않았다.
- 영국 사진은 CC BY-SA 4.0 이므로 화면 푸터에 저작자와 라이선스를 적고, 이 파일에 원본 URL 과 변형 내역을 남겼다.
  라이선스 전문: https://creativecommons.org/licenses/by-sa/4.0/
- 미국 사진은 연방정부 건물을 촬영한 퍼블릭 도메인, 프랑스 사진도 퍼블릭 도메인이다. 표기는 의무가 아니지만 같은 방식으로 남겼다.
- 원본은 내려받은 뒤 축소·재인코딩만 했고(자르기 없음), EXIF·GPS 는 제거했다. sha256 은 커밋 메시지에 기록했다.

## 이미지 — 제공자와 소유

네 장 모두 **PADIEM 대표가 AI 생성으로 만들어 LOCAL 0에게 전달**한 파일이다.
외부에서 내려받거나 스크랩한 이미지는 없다. 따라서 제3자 라이선스·표기 의무는 발생하지 않고,
공개 여부와 제품 사용은 대표의 소유 판단 범위다.

- 수신 위치(COM1 로컬, **비공개**): `E:\wt-5967-design-261027\reference\generated-assets\`
- 수신 일시: 2026-10-28 (ZIP `PADIEM_Parliament_AI_Design_Concepts_20261027.zip` 경유, SHA 4/4 확인)
- 원본 4장의 크기: 각 1672 × 941 px, aspect 1.777

## 저장소에 들어가는 파생본

| 파일 | 역할 | 원본 파일명 | 변형 | 화면 슬롯 |
|---|---|---|---|---|
| `parliament-hero.jpg` | 히어로 전폭 사진 | `3bcde80e-e4e3-47a5-907c-adf78ab9962d.png` | 리사이즈 없음(1672×941) · JPEG q84 재인코딩 | `--hero-photo` |
| `speech-card.jpg` | 카드 1 축사·인사말 | `5360d400-6432-4642-a19a-6e6ae57c8826.png` | 1120×630으로 축소(LANCZOS) · JPEG q84 | `--card-image-1` |
| `sns-card.jpg` | 카드 2 SNS 홍보 | `af6afe47-19bc-47cc-93b8-4ea3e89a4319.png` | 1120×630으로 축소 · JPEG q84 | `--card-image-2` |
| `meeting-card.jpg` | 카드 3 회의정리·활동집 | `af090a8b-6a91-4858-88e0-d8445c608fa7.png` | 1120×630으로 축소 · JPEG q84 | `--card-image-3` |

변형은 **리사이즈와 재인코딩만** 적용했다. 크롭·회전·색 보정은 파일에 구워 넣지 않고
렌더 단계(`background-size` / `background-position` / 오버레이 그라데이션)에서 결정한다.
어떤 파일에도 업스케일을 쓰지 않았다(파생본 폭 ≤ 원본 폭).

## 이미지별 실제 내용과 배치 근거

수신한 파일을 직접 열어 확인한 내용과, 시안 04에서 관찰한 구도:

| 자산 | 실제 내용 | 시안 04의 대응 요소 | 명도 계측(평균 luminance) | 배치 결정 |
|---|---|---|---|---|
| `parliament-hero.jpg` | 의사당 정면 + 중앙 돔 + 왼쪽으로 지는 석양 + 도시 스카이라인 | 히어로 오른쪽에 건물, 왼쪽은 먹색 기둥 | 좌측 반 122 / 우측 반 98 → **시안과 좌우가 반대** | `--hero-photo-position: 74% 44%`로 건물을 오른쪽에 두고, `.pa-scene::before`의 좌측 그라데이션(`--hero-scrim-strong`)으로 읽기를 보장 |
| `speech-card.jpg` | 본회의장 연단과 마이크 2본, 뒤로 의석 | 카드 1의 연단·마이크 사진 | x 3분위 67 / 85 / 56 → 중앙이 밝음 | `--card-position-1: 64% 52%`로 연단을 오른쪽에 두고 왼쪽은 색 오버레이 |
| `sns-card.jpg` | 책상 위 스마트폰, 화면에 사진 격자 | 카드 2의 스마트폰 사진 | x 3분위 39 / 60 / 37, 평균 45(4장 중 가장 어둡고 저채도) | `--card-position-2: 56% 50%`. 저채도이므로 카드 색(청록) 오버레이가 톤을 지배한다 |
| `meeting-card.jpg` | 회의 테이블 위의 인쇄 문서 + 네이비 노트 + 펜, 보라 톤 저녁실내 | 카드 3의 의정활동 보고서 | x 3분위 88 / 63 / 56 → **문서가 왼쪽** (시안은 오른쪽) | `--card-position-3: 42% 58%`로 문서를 가운데-오른쪽으로 밀고 카드 3 그라데이션으로 왼쪽을 누름 |

시안의 3개 카드는 서로 다른 소재를 쓰므로, 같은 사진 한 장을 위치만 바꿔 세 번 깔지 않는다.

## 제거한 자산

`assembly-night-1200.jpg` / `assembly-night-2400.jpg`(Wikimedia Commons “Dangsan Railway Bridge Night View”,
저작자 Tony, CC BY 2.0)는 **이 저장소에서 삭제**했다. 당산철교 야경은 시안의 의사당과 주제가 다르고,
대표가 역할별 생성본 4장을 전달했으므로 대체 이유가 사라졌다. 삭제와 동시에 화면 하단의 CC BY 표기도
제거해 크레딧이 실제 사용과 일치하도록 정리했다. 라이선스 자체는 표기 의무만 있어 재배포 없이 삭제로 끝난다.

## 비공개로 남기는 것

- `reference/design-assets/`의 시안 PNG 4종(01~04)과 그 픽셀을 축소한 비교 원판 → **추적 제외**.
  공개 커밋 여부는 대표의 별도 결정이다.
- `reference/generated-assets/`의 수신 원본 PNG 4장 → 화면에 필요한 파생본만 `assets/`에 넣었다.
