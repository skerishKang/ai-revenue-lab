#!/bin/bash
# #7078 stage-1 shadow verification aggregate (read-only).
# Usage: bash auth_shadow_aggregate.sh [unit] [since]
set -u
UNIT="${1:-padiem-chat-com2}"
SINCE="${2:-1 day ago}"
WORK="$(mktemp)"
journalctl -u "$UNIT" --since "$SINCE" -o short-iso 2>/dev/null \
  | grep 'shadow_verify outcome=' > "$WORK" || true
echo "unit=$UNIT since=$SINCE"
echo "total=$(wc -l < "$WORK")"
echo "outcome:"
sed -n 's/.*shadow_verify outcome=\([^ ]*\).*/\1/p' "$WORK" | sort | uniq -c | sort -rn
echo "uid_match:"
sed -n 's/.*uid_match=\([^ ]*\).*/\1/p' "$WORK" | sort | uniq -c | sort -rn
echo "token:"
sed -n 's/.*token=\([^ ]*\).*/\1/p' "$WORK" | sort | uniq -c | sort -rn
echo "verdict:"
sed -n 's/.* verdict=\([^ ]*\).*/\1/p' "$WORK" | sort | uniq -c | sort -rn
echo "jwks_cold_first_last:"
grep 'outcome=jwks_cold' "$WORK" 2>/dev/null | sed -n '1p;$p' | cut -c1-40 || true
echo "first_last_line:"
sed -n '1p;$p' "$WORK" | cut -c1-40
rm -f "$WORK"
