## CLAW1 — 보강: `D1 040 재적용 0건` 계약 근거 (읽기 전용, 관측 추가 없음)

위 보고의 `D1_040_SCHEMA=EXACT` / 재적용 0건 항목에 대해, 해당 run에서 실제로 통과한 계약 테스트(`B62_D1_MIGRATION_040_GATE_TESTS=PASS`)가 재적용 no-op 경로를 직접 고정하고 있음을 확인했습니다 — `.github/tests/test_b62_d1_migration_040_gate.py` @ `2235754e`:

```text
assert "if: ${{ env.PREMUTATION_SCHEMA_STATE == 'pre_040' }}" in workflow   # ALTER 단계
assert "if: ${{ env.PREMUTATION_SCHEMA_STATE == 'exact' }}"   in workflow   # no-op 단계
assert "SKIPPED_ALREADY_APPLIED" in workflow
recheck < application                                                        # 재점검 후에만 ALTER
assert recheck < preapply < application                                      # recovery bookmark → ALTER 순서
forbidden = (wrangler d1 create, d1 migrations apply, pywrangler deploy, wrangler deploy,
             DROP TABLE, DROP INDEX, DELETE FROM)                            # 전부 부재 단언
```

즉 라이브가 `EXACT`인 현재 상태에서 040 apply를 디스패치하면 `PREMUTATION_SCHEMA_STATE=exact` → `B62_D1_MIGRATION_040=SKIPPED_ALREADY_APPLIED`, `PRODUCTION_MUTATION=0`이고 **ALTER 문 0건**입니다. 이 경로는 회귀 테스트로 봉인되어 있고 해당 테스트는 위 run에서 PASS였습니다.

수정 사항 없음. `PRODUCTION_MUTATION=0` 유지.
