# StoryMemory 성경 본문 출처와 이용 조건

검토일: 2026-11-04  
범위: 저장소에 포함된 `apps/bookai/public/content/bible-web/` 성경 본문. 이 문서는 출처·권리 상태를 정리한 운영 전 검토 자료이며 법률 의견서가 아니다.

## 저장소에 있는 본문

`public/content/bible-web/manifest.json`은 저자를 `World English Bible / KRV-1961`, 판본을 `KRV-1961`로 표시한다. 각 장 데이터에는 영어 `en`과 한국어 `ko` 본문이 함께 있다. 현재 manifest는 판본 이름과 파일별 해시를 기록하지만, 실제 수집 파일의 원본 배포 URL·다운로드 날짜·배포판 해시는 밝히지 않는다. 특히 KRV-1961 본문의 정확한 원본 파일 및 수집 이력은 배포 전에 대조해야 한다.

## 영어 본문: World English Bible (WEB / ENGWEBP)

- **표시 이름·약칭:** World English Bible (WEB); eBible.org 카탈로그 식별자는 `engwebp`, 짧은 식별자는 `ENGWEBP`이다.
- **출처와 조건:** eBible.org의 [WEB 저작권 안내](https://www.ebible.org/eng-web/copyright.htm)는 World English Bible을 퍼블릭 도메인이고 저작권으로 보호되지 않는 본문이라고 선언하며 복사·출판·배포 등 자유 이용을 허용한다. 같은 안내는 “World English Bible” 이름이 상표이며, 본문을 변경한 결과물에는 혼동 방지를 위해 그 이름을 사용하지 말라고 한다. [WEB FAQ](https://www.ebible.org/eng-web/webfaq.htm)도 출판 목적의 퍼블릭 도메인 상태를 확인한다.
- **카탈로그 확인:** [eBible 성경 저작권 목록](https://ebible.org/Scriptures/copyright.php)은 World English Bible, 1997–2023, Public Domain, `engwebp` / `ENGWEBP`로 등록한다.
- 이 상태 설명은 WEB **본문**에 관한 것이다. PDF에 함께 들어 있는 지도·삽화·타사 자료에는 별도 권리가 있을 수 있으므로 이 문서로 허가 범위를 넓히지 않는다. 본문을 손대지 않고 faithful copy로 유지하며 화면에 World English Bible (WEB), 출처 eBible.org를 표시한다.

## 한국어 본문: 성경전서 개역한글판 (KRV-1961)

- **표시 이름·약칭·출처:** 성경전서 개역한글판 (KRV-1961), 대한성서공회.
- **권리자 안내:** [대한성서공회 저작권 안내](https://www.biblekorea.kr/bbs/content.php?co_id=subpage2_3_4_1)는 개역한글판의 최초 발행일을 1961-07-10으로 기록하고, 저작재산권 보호기간이 2011-12-31 소멸했다고 표시한다. 운영 판단의 가장 직접적인 근거로 이 권리자 안내를 사용한다.
- **보호기간 해석 근거:** [1957년 저작권법](https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=29306) 당시 단체명의 저작물은 발행·공연 후 30년 보호되었고 다음 해부터 기간을 계산했다는 점은 [법원 판결의 구법 설명](https://www.law.go.kr/LSW/precInfoP.do?precSeq=77376)에 정리되어 있다. [1986년 전부개정법(법률 제3916호)](https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=57808)은 1987-07-01 시행되었으며, 개정 법의 단체명의 저작물 보호기간은 공표 다음 해부터 50년으로 정해졌다(제38조·제40조; [한국저작권보호원 해설 자료](https://www.kcopa.or.kr/download.do?uuid=1b3764b7-3910-413d-8d3d-e14f685d2044.pdf) 참고). 개역한글판의 1961년 발행을 이 보호기간 계산에 대입하면 1962년부터 50년을 계산하여 2011-12-31에 끝나며, 이는 대한성서공회의 안내와 일치한다.
- **판본 구분:** [대법원 1994. 8. 12. 선고 93다9460](https://www.law.go.kr/LSW/precInfoP.do?precSeq=199797)은 1961년판이 1952년판과 달라 별도로 보호되는 저작물이라고 판단했다. 이 판결은 1961년판이 독립 보호 대상이었던 점을 확인하는 자료이지, 만료일 자체를 판단한 판결은 아니다.
- 2011년 보호기간 연장 개정의 경과규정은 시행 전에 이미 소멸한 권리를 되살리지 않는다고 정한다([저작권법 개정문·부칙, 법률 제11110호](https://www.law.go.kr/LSW/lsRvsDocListP.do?chrClsCd=010202&lsId=000798&lsRvsGubun=all)). 이 자료와 권리자 안내의 일자를 함께 대조했다.
- 위 계산은 단체명의 저작물 보호기간에 따른 문서화된 해석이다. 저장소의 실제 한국어 파일이 해당 판본의 원문과 동일한지, 별도의 편집·주석·배열 권리가 있는지는 manifest만으로 확인되지 않는다. 무단 변경을 하지 말고 출처를 표시한다.

> **운영 전 대한성서공회 안내 재확인 필요** — 배포 직전 대한성서공회에 현재 권리 안내와 저장소가 보유한 정확한 KRV-1961 파일·판본을 확인하고, 확인 일자와 회신 또는 URL을 운영 기록에 남긴다. 번역 본문은 새로 추가하지 않았다.

## 화면 표기

- 한국어: `성경전서 개역한글판 (KRV-1961) · 출처: 대한성서공회`
- 영어: `World English Bible (WEB / ENGWEBP) · 출처: eBible.org`
- 본문을 수정하거나 다른 자료를 섞었으면 원판 이름을 붙인 채 배포하지 말고, 출처와 권리 조건을 다시 확인한다.

## 확인한 공개 자료

| 자료 | 이 문서에서 확인한 내용 |
|---|---|
| [eBible WEB copyright](https://www.ebible.org/eng-web/copyright.htm) | WEB 퍼블릭 도메인 선언, 이용 범위, 상표 이름 사용 조건 |
| [eBible WEB FAQ](https://www.ebible.org/eng-web/webfaq.htm) | 출판 목적의 퍼블릭 도메인 상태와 공식 배포 출처 |
| [eBible Bible copyright catalog](https://ebible.org/Scriptures/copyright.php) | WEB 1997–2023, Public Domain, `engwebp` / `ENGWEBP` |
| [대한성서공회 저작권 안내](https://www.biblekorea.kr/bbs/content.php?co_id=subpage2_3_4_1) | KRV 최초 발행일과 2011-12-31 보호기간 소멸 표기 |
| [1957년 저작권법](https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=29306), [구법을 설명한 법원 판결](https://www.law.go.kr/LSW/precInfoP.do?precSeq=77376) | 단체명의 저작물 30년 및 다음 해 기산에 대한 역사적 근거 |
| [1986년 전부개정 저작권법](https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=57808), [한국저작권보호원 해설 자료](https://www.kcopa.or.kr/download.do?uuid=1b3764b7-3910-413d-8d3d-e14f685d2044.pdf) | 1987 시행 법과 단체명의 저작물 보호기간 50년 해석 자료 |
| [대법원 93다9460](https://www.law.go.kr/LSW/precInfoP.do?precSeq=199797) | 개역한글 1961년판의 독립된 저작물성에 관한 판결 |
| [법률 제11110호 개정문·부칙](https://www.law.go.kr/LSW/lsRvsDocListP.do?chrClsCd=010202&lsId=000798&lsRvsGubun=all) | 이미 소멸한 권리를 연장 개정으로 되살리지 않는 경과규정 |