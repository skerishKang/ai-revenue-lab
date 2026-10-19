# Chat · Claw · B66 — 공통 대화 UI 원칙과 배포 계약

최신 대표 지시: **한 제품을 무조건 따라가는 방식이 아닌, 세 제품에서 검증된 더 좋은 기능을 공통 채택한다.** 공통 기능은 한 곳에서만 구현하고, 제품별 색상·브랜딩·견적·작업 실행의 책임은 분리한다.

## 구현된 첫 통합 범위 (#4488)

- 공통 원본: `packages/padiem-conversation-ui/composer-core.js`.
- 생성 자산: `apps/padiem-chat/static/shared-conversation-composer.js`, `reference/business-66-padiem-quote-v1/shared-conversation-composer.js`.
- 수정 흐름: **공통 원본 수정 → `python scripts/sync_shared_conversation_composer.py --write` → 두 생성 자산 커밋 → CI `--check` → B62·B66 각각 보호 배포**. 자산은 편집하지 않는다.
- **Chat·Claw의 장점:** 한글 IME 조합 시 Enter 전송 방지(조합중·keyCode 229·Shift/Ctrl/Alt/Meta 조합).
- **B66의 장점:** 견적 질문의 단일 입력·전송 흐름은 유지하며 입력창을 작성 상태에 따라 늘리고, 전송 후 초기 높이로 되돌린다.
- 세 제품은 동일한 입력 동작 `createCompositionGuard`, `shouldSubmitOnEnter`, `resizeTextarea`를 호출한다. 길게 입력하는 경우 180px까지 확장하며 넘치면 텍스트 영역 내부 스크롤을 사용한다.
- Chat·Claw의 기존 공통 입력 DOM, 대화 연속 화면, 승인·커넥터·모델 권한을 유지한다. B66은 견적 질문/파일·템플릿·계산·PDF·AI 대화 저장을 기존 제품 서버와 계정 권한으로 처리한다.

## 아직 공통 통합이 아닌 부분 — 별도 차례로 처리

1. 답변 액션(복사·다시 생성·음성 듣기·공유·TXT), 메시지 렌더러, 대화 메뉴·이력, 첫 화면 스크롤 계약과 접근성.
2. 파일 첨부·미리보기·음성 입력과 제품별 제공 능력 표시. B66 마이크 등 검증되지 않은 기능을 임의로 ON으로 만들지 않는다.
3. 모델·회원등급 선택의 공통 프레젠테이션. 서버 측 모델 자격·비용·승인·결제 조건은 각 기존 권한 경계가 강제한다.
4. 일반 대화에서 작업 실행으로 이어지는 사용자 안내. Claw 실행 및 B66 견적 갱신은 기존 확인·승인 절차를 반드시 따른다.

공통 코드를 수정한 것만으로 각 운영 URL이 자동으로 바뀌지는 않는다. B62 Worker와 B66 Pages는 별도 배포 표면이므로 **둘 다 실제 배포 후** 제공 자산과 기본 동작을 확인한다. 새 모델 API 호출, 자동 요약·제목 생성, 신규 DB·브로커·네임스페이스를 추가하지 않는다.

상위 공통 이슈: [#4488](https://github.com/skerishKang/ai-revenue-lab/issues/4488). B66 고유 견적 전체 흐름 검사는 기존 [#4316](https://github.com/skerishKang/ai-revenue-lab/issues/4316)으로 유지한다.
