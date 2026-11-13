#!/bin/bash
# 읽기 전용 로그 보관 감사 — 쓰기 없음, 상태 조회만
OUT=/mnt/d/PADIEM/com2-audit-261103/a-logs.txt
UNITS="padiem-chat-com2 padiem-mesh-queue padiem-b14 padiem-meshcentral cloudflared-chat-com2 cloudflared-padiem padiem-file-lane"
{
echo "## A0. 전체 padiem 유닛 + P01 탐색"
systemctl list-unit-files --no-pager 2>/dev/null | grep -iE 'padiem|p01|engine|orch' | grep -v actions.runner
echo "## A0-2. 타이머 전체"
systemctl list-timers --all --no-pager 2>/dev/null | grep -iE 'padiem|chat|mesh|cloudflare' | awk '{print $NF, "|", $1, $2}'
echo "## A1. 유닛별 로그 경로"
for U in $UNITS; do
  echo "-- $U"
  systemctl show $U -p ActiveState -p StandardOutput -p StandardError -p FragmentPath -p EnvironmentFiles -p ExecMainPID 2>/dev/null
  echo "   drop-ins: $(systemctl show $U -p DropInPaths 2>/dev/null | cut -c1-200)"
done
echo "## A3. journald 설정"
grep -nE '^(#\s*)?(Storage|SystemMaxUse|SystemKeepFree|MaxRetentionSec|RateLimitBurst)' /etc/systemd/journald.conf 2>/dev/null
ls /etc/systemd/journald.conf.d/ 2>/dev/null || echo "(journald.conf.d 없음)"
for f in /etc/systemd/journald.conf.d/*.conf; do [ -e "$f" ] && { echo "-- $f"; grep -E '^(Storage|SystemMaxUse|MaxRetentionSec)' "$f"; }; done
journalctl --disk-usage 2>/dev/null
echo "## A3-2. 유닛별 journald 최초 기록 (oldest, head -1)"
for U in $UNITS; do
  echo -n "-- $U : "
  journalctl -u "$U" --no-pager -q 2>/dev/null | head -1 | cut -c1-46
done
echo "## A2. logrotate"
ls -la /etc/logrotate.d/ 2>/dev/null | awk '{print $NF, $5}' | tail -n +2 | head -15
echo "-- 관련 logrotate 파일 내용 (chat/padiem/mesh/cloudflared 매칭)"
for F in /etc/logrotate.d/*; do
  if grep -qiE 'padiem|mesh|chat|cloudflared|b14' "$F" 2>/dev/null; then echo "-- $F"; cat "$F"; fi
done
echo "## A2-2. /opt 하위 앱 로그 파일"
find /opt/padiem /opt/padiem-ci -maxdepth 4 \( -name '*.log' -o -name '*.log.*' \) -printf '%s\t%T+\t%p\n' 2>/dev/null | sort -k3 | head -25
} > "$OUT" 2>&1
echo "A done -> $OUT"
