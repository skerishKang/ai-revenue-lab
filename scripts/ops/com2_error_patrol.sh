#!/bin/bash
# PADIEM 컴2 오류 순찰(읽기 전용) — 최근 3일 5개 유닛 저널에서
# 5xx·traceback·timeout·refusal을 뽑아 유형별로 요약한다.
# 아무것도 변경하지 않는다(저널 읽기만). WSL Ubuntu에서 실행.
#
#   bash patrol.sh [일수]   # 기본 3일
#
# scanner_404 = 인터넷 스캐너가 두드리는 경로(접두 일치)의 합계·종류 수만 한 줄로 요약한다(개별 경로는 숨김).
# internal_404 = 우리 망(PATROL_INTERNAL_IPS, 공백 구분, 기본 127.0.0.1)에서 온 404로, 경로·건수를 그대로 보여 레인 스크립트 오탈자 신호로 쓴다.
set -uo pipefail
DAYS="${1:-3}"
INTERNAL_IPS="${PATROL_INTERNAL_IPS:-127.0.0.1}"
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

  # 404는 접근 로그의 경로·출처를 쓴다(구조화 이벤트에는 실제 경로·IP가 없다).
  a404=$(echo "$log" | grep -E '" 404( |$)' \
    | sed -nE 's/^.* ([0-9A-Fa-f:.]+):[0-9]+ - "[A-Z]+ ([^ "]+) HTTP\/[0-9.]+" 404( .*)?$/\1 \2/p')
  scanner_total=0
  internal_total=0
  other_total=0
  declare -A scanner_seen=() internal_counts=() other_counts=() internal_ips=()
  for ips in $INTERNAL_IPS; do
    internal_ips["$ips"]=1
  done
  if [ -n "$a404" ]; then
    while IFS=' ' read -r ip path; do
      [ -z "${path:-}" ] && continue
      path="${path%%\?*}"
      case "$path" in
        '/.env'*|'/.git/'*|'/.svn/'*|'/.hg/'*|'/admin'*|'/robots.txt'*|'/sellers.json'*|'/ads.txt'*|'/wp-'*|'/.well-known/'*|'/phpmyadmin'*|'/vendor/'*|'/cgi-bin/'*)
          scanner_total=$((scanner_total + 1))
          scanner_seen["$path"]=1
          ;;
        *)
          if [ -n "${internal_ips["$ip"]:-}" ]; then
            internal_total=$((internal_total + 1))
            internal_counts["$path"]=$(( ${internal_counts["$path"]:-0} + 1 ))
          else
            other_total=$((other_total + 1))
            other_counts["$path"]=$(( ${other_counts["$path"]:-0} + 1 ))
          fi
          ;;
      esac
    done <<< "$a404"
  else
    j404=$(echo "$log" | grep -c '"status":404' || true)
    if [ "${j404:-0}" -gt 0 ]; then
      other_total=$j404
      other_counts["<unmatched>"]=$j404
    fi
  fi
  total404=$((scanner_total + internal_total + other_total))
  if [ "$total404" -gt 0 ]; then
    echo "  404 집계:"
    echo "    scanner_404=${scanner_total} (경로 ${#scanner_seen[@]}종)"
    if [ "$internal_total" -gt 0 ]; then
      echo "    internal_404 (우리 망):"
      for p in "${!internal_counts[@]}"; do
        printf '      %s %s\n' "$p" "${internal_counts[$p]}"
      done | sort -k2 -rn
    fi
    if [ "$other_total" -gt 0 ]; then
      echo "    기타 404 경로별:"
      for p in "${!other_counts[@]}"; do
        printf '      %s %s\n' "$p" "${other_counts[$p]}"
      done | sort -k2 -rn | head -10
    fi
  fi
done

echo
echo "== 종료: $(date -Is) — 변경 없음(읽기 전용) =="
