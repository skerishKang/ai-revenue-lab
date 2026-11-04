#!/bin/bash
# PADIEM 컴2 오류 순찰(읽기 전용) — 최근 3일 5개 유닛 저널에서
# 5xx·traceback·timeout·refusal을 뽑아 유형별로 요약한다.
# 아무것도 변경하지 않는다(저널 읽기만). WSL Ubuntu에서 실행.
#
#   bash patrol.sh [일수]   # 기본 3일
set -uo pipefail
DAYS="${1:-3}"
SINCE="${DAYS} days ago"
UNITS=(padiem-chat-com2 padiem-p01 padiem-b14 padiem-mesh-queue cloudflared-padiem)

echo "== 순찰 시작: $(date -Is) (최근 ${DAYS}일) =="

for unit in "${UNITS[@]}"; do
  echo
  echo "--- $unit ---"
  log=$(journalctl -u "$unit" --since "$SINCE" --no-pager 2>/dev/null)
  [ -z "$log" ] && { echo "  (저널 없음)"; continue; }

  tb=$(echo "$log" | grep -c "Traceback")
  t5xx=$(echo "$log" | grep -oE '"status":5[0-9]{2}' | wc -l)
  h5xx=$(echo "$log" | grep -oE ' HTTP/1\.1" 5[0-9]{2}' | wc -l)
  to=$(echo "$log" | grep -ci "timeout")
  ref=$(echo "$log" | grep -c "refused")
  echo "  traceback=$tb http5xx=$((t5xx + h5xx)) timeout=$to refused=$ref"

  if [ "$t5xx" -gt 0 ]; then
    echo "  5xx 경로별:"
    echo "$log" | grep -E '"status":5[0-9]{2}' \
      | grep -oE '"route":"[^"]+","service":"[^"]+"' | sort | uniq -c | sort -rn | head -5 \
      | sed 's/^/    /'
    echo "  5xx 대표 request_id(첫 건):"
    echo "$log" | grep -E '"status":5[0-9]{2}' \
      | grep -oE '"request_id":"[^"]+"' | head -1 | sed 's/^/    /'
  fi
  if [ "$tb" -gt 0 ]; then
    echo "  traceback 시각 분포:"
    echo "$log" | grep "Traceback" | awk '{print $1, $2}' | sort | uniq -c | sort -rn | head -3 \
      | sed 's/^/    /'
  fi
  if [ "$ref" -gt 0 ]; then
    echo "  refused 사유별:"
    echo "$log" | grep "refused" | grep -oE "reason=[A-Za-z]+" | sort | uniq -c | sort -rn | head -3 \
      | sed 's/^/    /'
  fi
done

echo
echo "== 종료: $(date -Is) — 변경 없음(읽기 전용) =="
