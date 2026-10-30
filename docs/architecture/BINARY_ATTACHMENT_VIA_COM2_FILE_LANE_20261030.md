# 바이너리 첨부 문서를 컴2 파일 레인에서 파싱 — 2026-10-30

상태: 설계. 기준 main `d1eea300b`. 대표 결정(22:03): Chat에 Cloudflare 파서 Worker를 연결하지 않고 컴2 파일 레인으로 PDF·DOCX·PPTX·XLSX를 보낸다. #2824 / #5881.

## 현재 경로와 빈 곳

- Chat `app_factory.py:434`의 `binary_document_attachment_ready`는 Core `document_parser_boundary.py:248`을 읽는다. Worker에서 격리 파서가 설치되지 않으면 false다. `static/locale.js:753`이 파일 선택 기능에 전달하며, 인라인 바이너리는 `attachments.py:129,161` → `binary_documents.py:137` → Core 비동기 파서 경계에서 거부된다. 이 health 값은 **Worker 인라인 파서**의 상태이지 컴2 준비 여부가 아니다.
- `static/file-lane.js:4-10`과 `app/file_lane.py:24,155`은 현재 TXT/MD/CSV/PDF만 공지·전달한다. 파일 레인이 준비되고 인라인 파서가 없을 때 PDF는 작은 파일도 우회한다. DOCX/PPTX/XLSX는 브라우저 및 Chat의 형식 목록에서 빠져 있다. `attachments.py:141`, `chat_routes.py:334,865`, `orchestration_routes.py:180`, `claw_general_routes.py:1339`에는 file_id 해석 경로가 이미 있다.
- 컴2 구현은 `apps/padiem-file-lane/src/padiem_file_lane/{app,storage,tickets,parsing}.py`: 티켓 검증·스트리밍 업로드·사용자별 디렉터리·SHA-256·메타데이터·텍스트 조회가 있고, `/text` 최초 조회에서 동기 파싱 후 디스크 캐시한다. PDF·DOCX·PPTX·XLSX 종류도 구현돼 있다. XLSX의 `/structure`는 별도 양식 구조 API이며 모든 문서의 구조 결과를 반환하는 범용 API는 아니다. 호스트 서비스는 `deploy/host-com2/file-lane/`; 실제 설치·가동 상태와 설치된 코드 버전은 이번에 읽지 않았다.
- `parsing.py:13`의 OOXML은 Core `document_normalization.extract_binary_document`를, PDF는 Core `pdf_markdown.convert_pdf_to_markdown`을 재사용한다. 파서 Worker의 `worker.py:14` → `isolated_parser_service.py:45`도 같은 Core `extract_binary_document`를 사용한다. 동일 코드 기반을 컴2에서 재사용 가능하다. 단 PDF의 두 호출 경로는 동일 함수가 아니므로 안전 검사를 각각 입증한다.
- `PADIEM_CHAT_FILE_LANE_ORIGIN` 및 `PADIEM_CHAT_FILE_LANE_TICKET_SECRET` 구성·발급 경로는 이미 있다. Core 안전 보강 #6316은 이 설계 기준에서 미병합이다. 또한 컴2 OOXML 호출은 `ooxml_member_max_bytes=None`이므로 기본 멤버 예산 적용을 가정하지 않는다. #6316이 확정하는 검사와 현행 예외의 적용 범위를 구현 전 대조한다.

## 제안 흐름과 권한

1. 브라우저가 로그인된 사용자로 `/api/files/capabilities`를 조회한다. 파일 레인이 준비된 경우 네 형식을 표시하고 `/api/files/ticket`에서 서버가 발급한 티켓으로 파일을 컴2 `POST /files`에 스트리밍한다. 응답의 file_id만 대화에 전달하며 원본 바이트는 Chat Worker에 싣지 않는다.
2. Chat은 **서버 검증된 로그인 소유자**를 기준으로 새 읽기 티켓을 발급하고 파일 ID의 `/meta` → `/text`를 조회한다. 현재 COM2는 티켓과 그 소유자 디렉터리로 접근을 통제하며, COM2에서 로그인 JWT/JWKS를 직접 확인한다고 주장하지 않는다. 공통 로그인으로 전환할 때는 검증된 JWKS 서명·issuer·audience·만료 및 세션과 Chat의 사용자 ID 연결을 발급 전에 검증한다. 기존 로그인 경로의 검증과 동등함을 확인하고, 본문·파일명으로 소유자를 선택하지 않는다. 다른 사용자의 ID는 접근 거부한다.
3. 현재 구현처럼 최초 `GET /text`에서 안전 검사와 파싱을 동기 수행해 캐시하고, 후속 조회는 캐시를 읽는다. Chat은 추출된 텍스트를 기존 문서 첨부·신뢰하지 않는 자료 경로로 전달한다. 구조가 필요한 XLSX는 기존 구조 API를 별도 허가 아래 사용하고, 다른 형식의 구조가 필요하면 별도 계약을 정의한다. Engine의 문서 참조·윈도우 경로는 존재하나 Chat 호출부에 연결됐다고 가정하지 않는다.
4. 임의의 새 크기·시간 상한을 만들지 않는다. 현재 업로드는 티켓의 실제 크기 예산과 디스크 여유를 검증한다. 기존 안전 결정의 확장자·매직·암호화·압축 검사 및 각 파서의 기존 예산을 적용하되, #6316의 미병합 상태와 파일 레인 OOXML 예외를 해소·검증한다. 기존 10 MB는 라우팅 기준이며 거부 상한이 아니다. 모델 문맥과 기존 전송 제약은 별도 확인한다.
5. 미지원·손상·암호화·안전 검사 거부는 내용 없는 사용자 안내로 구분한다. 컴2 오프라인·업로드/파싱 실패 시 “파일 서버에 연결하지 못했어요. 연결을 확인하고 다시 시도해 주세요.”처럼 실패를 알리고 원본을 Worker 경로로 몰래 재전송하지 않는다. 실패 코드만 서버 로그에 남기고 문서·티켓·사용자 정보를 남기지 않는다.

## 구현 순서

1. **안전 계약**: #6316 확정본을 기준으로 컴2 PDF 및 OOXML 양 경로의 사전 검사를 통합·검증한다. 우회 인자, 압축 위장·암호화·부적합 입력과 정상 4종을 기존 테스트에 추가한다. 기존 크기 결정 변경은 별도 Owner 결정 전 금지.
2. **Chat 연결**: 기존 파일 레인 브라우저 형식 목록·capability·서버 resolver에 DOCX/PPTX/XLSX를 확장하고, PDF 포함 네 형식이 COM2 참조로 흐르게 한다. 로그인/JWKS 검증 결과와 티켓 소유자 연결, 사용자 간 격리·비로그인 거부·컴2 장애·기존 인라인 경로를 테스트한다.
3. **통합 검증**: Qoder가 컴2 설치본의 버전·의존성·실행 상태를 확인하고 기존 정식 절차로 반영한다. 실제 제품에서 네 형식 각각 업로드→파싱→답변, 교차 사용자 거부, 오프라인 실패를 확인한다. Engine 문서 윈도우 연결은 필요한 경우 별도 범위로 다룬다.

이미 있음: 파일 레인 저장·티켓·소유자 격리·텍스트 조회와 Core 기반 파서. 새로 만들 것: 4종 capability 연결, 안전 계약 일치·테스트, 사용자 오류 처리와 통합 검증. 만들지 않을 것: Cloudflare 파서 Worker 연결, 새 인증 권위, 임의 상한, 별도 분류 모델 호출.

대표 결정 필요: **없음**. #6316의 최종 결과와 컴2 설치본 실측은 구현 시 선행 확인한다.
