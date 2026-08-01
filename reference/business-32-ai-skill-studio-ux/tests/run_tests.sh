#!/usr/bin/env bash
# Business 32 Phase 2 UX — repository-local test runner (no browser).
set -u
cd "$(dirname "$0")/.."
fail=0

step() {
  echo
  echo "== $1 =="
}

step "state machine contract test"
node tests/machine_test.js || fail=1

step "journey tests"
node tests/journey_test.js || fail=1

step "fixture contract test"
node tests/fixture_test.js || fail=1

step "static contract test (labels, keyboard, external deps 0, syntax)"
node tests/static_contract_test.js || fail=1

step "template ↔ machine consistency test"
node tests/template_machine_test.js || fail=1

step "final repair test (role history, boundaries, drawer, app wiring)"
node tests/final_repair_test.js || fail=1

step "javascript syntax (node --check)"
for f in scripts/*.js; do
  node --check "$f" || fail=1
done

step "git diff --check"
if git diff --check --cached 2>/dev/null | grep -q .; then
  git diff --check --cached
  fail=1
fi
if git diff --check 2>/dev/null | grep -q .; then
  git diff --check
  fail=1
fi
echo "git diff --check: ok"

step "scope check"
python3 tests/scope_check.py || fail=1

echo
if [ "$fail" -eq 0 ]; then
  echo "ALL TESTS PASSED"
else
  echo "TESTS FAILED"
fi
exit "$fail"
