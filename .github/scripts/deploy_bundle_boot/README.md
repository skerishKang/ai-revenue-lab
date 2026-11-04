# Deploy bundle boot tests (#6855)

CI already ran source tests, but a host bundle could still fail on first start
because a module was left out of the staging list, a file was root-only, or the
service account could not read the tree. These jobs build the bundle from the
deploy scripts and boot it from a bundle-only directory as a non-privileged
account.

| Job | Staging source | Boot | Health |
|---|---|---|---|
| `b14-bundle-boot` | `apps/korean-ai-platform/deploy.sh` module loops | Wrangler dry-run outdir, CPython `asgi:app` | `/health` 200 |
| `chat-bundle-boot` | `deploy/host-com2/chat/install.sh` required + symlink lists | `app.local_server` | `/health` 200 |
| `p01-bundle-boot` | `deploy/host-com2/p01/stage_code.sh` (called directly) | `uvicorn asgi:app` | `/internal/v1/health` 200 |

Each job also runs two negative controls against a copy of the same bundle:

1. delete one staged module and require the import to fail;
2. narrow the tree to root-only `0600/0700` and require the service account to
   be denied.

A job fails if a negative control unexpectedly succeeds. This is what proves
the positive result is sensitive to the two failures #6855 records.

## #6855 regression case

**원인 확인(2026-11-05 06:37 comp2 재현).** deploy.sh는 #6848부터
`conversation_bounds`·`evidence_blocks`를 스테이징하지만, COM2의 B14
installer(`deploy/host-com2/b14/install.sh`)는 `pc_work_metrics` 하나만
옮겨 왔다. 새 릴리스는 첫 기동에서
`ModuleNotFoundError: No module named 'padiem_ai_core.conversation_bounds'`
으로 크래시 루프에 들어갔고, 배포 스크립트가 이전 트리로 되돌렸다.
CI가 deploy.sh 목록으로 묶음을 만들어 통과시켰기 때문에 이 격차가 보이지
않았다.

- 고침: installer가 deploy.sh의 `for module in ...` 목록을 그대로 읽어
  스테이징한다(두 목록이 다시 어긋날 수 없다).
- 회귀 시험: `deploy/host-com2/tests/test_b14_core_staging_261105.py` —
  installer 목록 == deploy.sh 목록, #6848 모듈 포함, 단일 모듈 하드코딩
  금지. 이것이 "옛 묶음(installer 목록 누락)에서 실패, 고친 묶음에서
  통과" 케이스다.
- 검증: 2026-11-05 comp2 실배포에서 installer 수정 전 롤백 / 수정 후
  기동 확인.

## Boundary

- No Cloudflare deploy, no systemd start, no tunnel, no real credential.
  Fake values are generated inside the job (`common.fake_hex`).
- The health wait exists only to let a booting process finish its imports and
  migrations; it is not an application time limit or a size ceiling.
