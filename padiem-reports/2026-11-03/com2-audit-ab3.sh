#!/bin/bash
OUT=/mnt/d/PADIEM/com2-audit-261103/ab3.txt
{
echo "## B2-수정. /proc environ (정식 유닛명)"
python3 - <<'PYEOF'
import subprocess, hashlib
NAME='CLAW_ENGINE_DESKTOP_SECRET'
units={'padiem-chat-com2':'chat','padiem-p01':'p01','padiem-b14':'b14','padiem-mesh-queue':'queue','padiem-file-lane':'file-lane'}
vals={}
for unit,label in units.items():
    try:
        pid = subprocess.check_output(['systemctl','show',unit,'-p','ExecMainPID','--value'], text=True).strip()
    except Exception as e:
        print(f'{label}: unit 조회 실패 {e}'); continue
    if not pid.isdigit() or int(pid)==0:
        print(f'{label}: PID 없음'); continue
    try:
        raw = open(f'/proc/{pid}/environ','rb').read().decode('utf-8','replace').split('\x00')
        hit = [x for x in raw if x.startswith(NAME+'=')]
        if hit:
            v = hit[0].split('=',1)[1]
            vals[label]=v
            print(f'{label} ({unit}, pid {pid}): 이름 있음 | 길이 {len(v)} | 끝4자리 …{v[-4:]}')
        else:
            print(f'{label} ({unit}, pid {pid}): 이름 없음 (environ 항목 {len(raw)}개)')
    except Exception as e:
        print(f'{label}: /proc 읽기 실패 {str(e)[:60]}')
if 'chat' in vals and 'p01' in vals:
    same = hashlib.sha256(vals['chat'].encode()).digest() == hashlib.sha256(vals['p01'].encode()).digest()
    print('Chat vs P01 값 해시 비교:', '같음' if same else '다름')
PYEOF
echo "## B1-수정. 모든 env 파일에서 이름 검색 (이름만)"
grep -rl "CLAW_ENGINE_DESKTOP_SECRET" /opt/padiem/chat-com2/.env* /opt/padiem/p01/ /opt/padiem/b14/env/ /opt/padiem/mesh-queue/queue.env /etc/systemd/system/padiem-chat-com2.service /etc/systemd/system/padiem-p01.service 2>/dev/null
echo "(위 경로가 비면 해당 파일에 이름 없음)"
echo "-- 유닛 내 Environment= 인라인 확인"
grep -l "CLAW_ENGINE_DESKTOP_SECRET" /etc/systemd/system/padiem-*.service /etc/systemd/system/padiem-*.service.d/*.conf 2>/dev/null || echo "(유닛 인라인에도 없음)"
echo "## A5-수정. b14 ledger 컬럼/최소시각"
python3 - <<'PYEOF'
import sqlite3
con = sqlite3.connect('file:/opt/padiem/b14/ledger/b14-call-ledger.db?mode=ro', uri=True)
cur = con.cursor()
for t in ('b14_model_call','b14_model_call_attempt'):
    cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{t}")').fetchall()]
    tcol = next((c for c in cols if any(k in c.lower() for k in ('time','at','date','ts','epoch'))), None)
    cnt = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    if tcol:
        lo, hi = cur.execute(f'SELECT MIN("{tcol}"), MAX("{tcol}") FROM "{t}"').fetchone()
        print(f'{t}: rows={cnt} cols={cols[:8]} {tcol}: min={lo} max={hi}')
    else:
        print(f'{t}: rows={cnt} cols={cols[:10]} (시간 컬럼 후보 없음)')
con.close()
PYEOF
echo "## A5-수정. chat.sqlite3 전체 테이블 중 로그성 테이블"
python3 - <<'PYEOF'
import sqlite3
con = sqlite3.connect('file:/opt/padiem/chat-com2/data/chat.sqlite3?mode=ro', uri=True)
cur = con.cursor()
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
logish = []
for t in tables:
    try:
        cnt = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    except: continue
    if cnt > 0 and any(k in t.lower() for k in ('log','ledger','request','event','history','audit','session','pairing')):
        logish.append((t, cnt))
for t, cnt in logish:
    cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{t}")').fetchall()]
    tcol = next((c for c in cols if any(k in c.lower() for k in ('created','time','ts','at'))), None)
    lo = cur.execute(f'SELECT MIN("{tcol}") FROM "{t}"').fetchone()[0] if tcol else None
    print(f'{t}: rows={cnt} oldest({tcol})={str(lo)[:24]}')
con.close()
PYEOF
echo "## A3-수정. padiem-p01 저널 최초 기록"
journalctl -u padiem-p01 --no-pager -q 2>/dev/null | head -1 | cut -c1-50
echo "## A2-수정. chat-com2 앱 로그 파일 존재"
find /opt/padiem/chat-com2 /opt/padiem/p01 /opt/padiem/mesh-queue -maxdepth 3 -name '*.log*' 2>/dev/null | head -8
echo "(위가 비면 파일 로그 없음 — 전부 journald)"
} > "$OUT" 2>&1
echo "AB3 done"
