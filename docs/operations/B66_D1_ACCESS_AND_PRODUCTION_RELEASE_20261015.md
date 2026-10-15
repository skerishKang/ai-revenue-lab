# B66 운영 D1 접근·배포 재사용 절차 (2026-10-15)

**기준:** `skerishKang/ai-revenue-lab`; 관련 [#4803](https://github.com/skerishKang/ai-revenue-lab/issues/4803), 고객 운영 수용 [#4316](https://github.com/skerishKang/ai-revenue-lab/issues/4316).
**범위:** 기존 B66/Chat 운영 D1 구조의 비파괴 확인 및 승인된 코드 배포. 비밀값·고객 자료·인증 쿠키는 기록하지 않는다.

## 문제와 검증된 해결

COM1 `Padiem-Command-Center`에서 기본 설치된 `wrangler d1 execute ... --remote`를 호출하면 Cloudflare `Authentication error [code: 10000]`가 발생할 수 있다. 이는 **그 시점 로컬 CLI 인증 자격증명에 해당 D1 API 접근 권한이 없다는 관찰값**이다. D1 테이블이 없거나 B66 서버가 고장났다는 증거가 아니다.

**이미 동작하는 기존 운영 경로:** GitHub Actions의 `secrets.CLOUDFLARE_API_TOKEN` / `secrets.CLOUDFLARE_ACCOUNT_ID`를 쓰는 보호된 워크플로. 운영 D1 ID는 현재 `padiem-chat` Worker의 `PADIEM_CHAT_DB` 바인딩을 **서버 측으로 조회**해 찾으며 이름만 추측하거나 별도 DB를 생성하지 않는다. 자격증명을 브라우저나 GitHub 로그에 출력하거나 로컬 Wrangler 자격증명으로 복사하지 않는다.

### 확인된 실제 실행 기록

- 2026-10-14 읽기 전용 사전 확인: [run 38564919043](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38564919043) 성공.
- 2026-10-14 보호된 `apply`: [run 38565043521](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38565043521) 성공. **041·042는 이미 EXACT였고 이 실행에서는 044만 적용**한 뒤 `B66_D1_SCHEMA_041_042=EXACT`, `B66_D1_SCHEMA_044=EXACT`, `B66_D1_RELEASE=APPLIED_AND_VERIFIED`를 남겼다.
- 2026-10-15 최신 main read-only 재확인: [run 38693899424](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38693899424) 성공, `B66_D1_SCHEMA_041_042=EXACT`, `B66_D1_SCHEMA_044=EXACT`, `B66_CANONICAL_D1_AND_RECOVERY=PASS`; 운영 row 변경 0.
- 2026-10-15 Chat Worker: [run 38694004676](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38694004676) 성공. `POSTDEPLOY_SERVED_VERSION_ID=cbf25e70-3ea1-4a74-9528-6792928a92ea`, `B62_BINDING_AUTHORITY_PRESERVED=PASS`, `POSTDEPLOY_SERVED_SECRET_COUNT=15`, `B62_PRODUCTION_SMOKE=PASS`.
- 2026-10-15 B66 Pages: [run 38694294138](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38694294138) exact-main 성공. `validate-and-release`와 `post-deploy-contracts` 성공.

## 다음 세션에서 반복 가능한 최소 명령 (운영자 GitHub 권한 전제)

아래 명령은 **현재 main SHA를 반드시 새로 확인**하고 읽기 전용 검사를 먼저 하는 예시이다. 작업을 반복한다는 이유만으로 이미 적용된 D1 마이그레이션을 다시 실행하지 않는다.

```bash
REPO=skerishKang/ai-revenue-lab
SHA="$(gh api repos/$REPO/git/ref/heads/main --jq .object.sha)"
gh workflow run b62-b66-d1-041-042-044-release.yml --repo "$REPO" --ref main \
  -f mode=readonly -f target_sha="$SHA"
# 새로 생성된 run id를 gh run list/view 또는 GitHub Actions에서 확인.
# 041·042·044가 모두 EXACT이면 D1 apply 생략.
```

실제 스키마가 없다는 **읽기 전용 증거**가 나왔을 때에만, 해당 워크플로의 소스·현재 운영 DB ID·Time Travel 복구 조건을 확인한 후 보호된 `apply`를 사용한다. 배포 전 승인된 변경이라도 **다른 D1·다른 고객 데이터베이스로 우회하지 않는다**.

```bash
# D1이 정확히 준비된 후에만 기존 Chat Worker 보호 배포
gh workflow run b62-production-code-deploy-gate.yml --repo "$REPO" --ref main \
  -f mode=deploy_production_code -f target_sha="$SHA" \
  -f confirmation=DEPLOY_B62_PRODUCTION_CODE_FROM_EXACT_MAIN
# Worker 성공 후 기존 B66 Pages 보호 배포
gh workflow run b66-neutral-pages-beta.yml --repo "$REPO" --ref main \
  -f target_sha="$SHA" -f confirmation=DEPLOY_B66_PAGES_FROM_EXACT_MAIN_ONCE
```

두 배포 간 `main`이 이동하면 이전 SHA로 무조건 반복하지 않는다. 최신 main의 변경 파일과 제품 영향 범위를 확인하고 새로운 exact SHA를 사용한다. Pages의 5분 배포 간격 제한이 나오면 제한이 끝난 후 정상 절차를 따른다.

## 성공 판정과 미확인 구분

- D1의 041/042/044 **스키마 준비 성공** ≠ 로그인 사용자의 견적 대화 정상 작동.
- Worker/Pages 배포와 읽기 전용 필수 검사 성공 ≠ 실제 유료 모델 답변·동일 견적 수량 변경·CGI 인증 PDF 생성 성공.
- 브라우저 수용은 기존 [#4316](https://github.com/skerishKang/ai-revenue-lab/issues/4316)에 남긴다. 이전에 통과한 로그인/이력 검증을 반복하지 않고 이번 변경의 실제 견적→PDF→수정→재다운로드 한 흐름만 검증한다.
- `10000` 오류 해결책은 **확인된 권한을 가진 보호된 운영 워크플로의 재사용**이지, 권한 없는 토큰을 다른 계정·엔드포인트로 우회하는 것이 아니다.
