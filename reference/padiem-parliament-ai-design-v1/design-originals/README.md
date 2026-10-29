# PADIEM Parliament AI — 최초 시안 원본 4종 정본 보관 (#5967)

대표가 2026-10-27 전달한 생성 시안 패키지 `PADIEM Parliament AI Design Concepts 20261027`의
원본 PNG 4종을 **바이트 그대로(무변형)** 보관한다. #5967 수용 조건의 마지막 항목
"시안 원본 PNG 4개를 저장소 디자인 reference 폴더에 업로드"를 충족한다.

시안 검토는 종료됐다(v3 원본 대조 → 04 한국 시네마틱 채택 → PR #5974 · #6041 · #6044 · #6222
병합, 4국가 × 5스타일 운영 배포 검증 완료). 검토 기간에 `.gitignore`로 비공개 유지하던
로컬 보관본(`reference/design-assets/`, `reference/generated-assets/`)과 이 정본 사본은
별개이며, 로컬 경로의 ignore 규칙은 작업 복제본 보호를 위해 그대로 둔다.

## 원본 대조

두 독립 출처가 6/6 SHA-256 일치로 확인됐다(2026-10-28 COM1 실검증 기록과도 일치).

1. 대표 전달 ZIP `G:\downloads\PADIEM_Parliament_AI_Design_Concepts_20261027.zip`
   (ZIP SHA-256 `3f7a56502c019715bf463990e76c42396eeb5866e1db1c3282f9b4bf9d70a4e8`)
2. LOCAL0 워크트리 비공개 보관본 `E:\wt-5967-design-261027\reference\design-assets\`

이 디렉터리의 파일은 (2)에서 복사했고 복사 후 해시를 재계산해 동일함을 확인했다.

## 파일 목록

| 파일 | 크기(bytes) | 해상도 | SHA-256 |
| --- | --- | --- | --- |
| `01_uk_classic.png` | 1,821,464 | 1586×992 | `d94be404ef53f7a3dd214b539ecff2110078ec89178811951b49266dc26a53a1` |
| `02_us_cinematic.png` | 1,983,021 | 1586×992 | `f4ff66f1d505e7f2f48ebb3e69bf3641a2a867d14ebbe9da3f5280505f5f6542` |
| `03_global_theme_matrix.png` | 2,156,248 | 1536×1024 | `c0bd23e1fc8b0fa669e670ebd96072690caf834034d779839768df032774e75b` |
| `04_korea_cinematic_home.png` | 1,902,433 | 1672×941 | `86f9e8e9cd0e88ff25e075d892af9798366b22471d45bea8c1219987a3ce6dab` |

패키지에는 이 4종과 함께 로컬 갤러리 2파일이 있었고 저장소 등록은 4 PNG만 한다.
갤러리 파일의 해시는 6/6 대조 기록 보존용이다:

```text
index.html  94c73a24568eb24b308315e650b4b29aa357cc0888ff3435f4ed304cbbd0f313
README.md   2976264091cdcbbc9f020d5ccac4f8d445e367db4e4b63ed6f9b816294a0ad3e
```

## 내용 (패키지 README 기준)

- `01_uk_classic.png` — 웨스트민스터·네이비·앤티크 골드, 대시보드형 클래식 시안
- `02_us_cinematic.png` — 미국 의회 건축·크림·네이비, 3업무 편집기 시안
- `03_global_theme_matrix.png` — 한국·미국·프랑스·영국 × 클래식·모던·다크·라이트·미니멀 비교 매트릭스
- `04_korea_cinematic_home.png` — 서울 국회의사당·석양, 간결한 3업무 CTA (대표 채택 정본)

프랑스 단독 시안 원본은 패키지에 없으며 03 매트릭스의 프랑스 패널이 유일한 증거다
(패키지 README가 직접 기록). 이미지들은 탐색 단계 생성 시안이고 실제 구현·데이터·문구의
정확성을 보증하지 않는다. 공식 의회 기관의 표장·로고는 사용하지 않았다.

## 재검증 방법

```bash
sha256sum reference/padiem-parliament-ai-design-v1/design-originals/*.png
```
