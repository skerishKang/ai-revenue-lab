#!/bin/bash
OUT=/mnt/d/PADIEM/com2-audit-261103/ab2.txt
{
echo "## A2-3. b14 logrotate 나머지"
cat /etc/logrotate.d/padiem-b14 2>/dev/null | tail -8
echo "## A2-4. b14 파일 로그 실물 (크기/가장 오래된 회전)"
ls -la --time-style=+%Y-%m-%d /opt/padiem/b14/logs/ 2>/dev/null | head -12
echo "## A3-3. 저널 전체 최초 기록"
journalctl --no-pager -q 2>/dev/null | head -1 | cut -c1-60
echo "## A4. 유닛별 최근 기록 항목 종류 분류 (내용 미수록, 카테고리만)"
python3 - <<'PYEOF'
import subprocess, re
UNITS=['padiem-chat-com2','padiem-mesh-queue','padiem-b14','padiem-meshcentral','cloudflared-chat-com2','cloudflared-padiem','padiem-file-lane','padiem-p01']
for U in UNITS:
    try:
        out = subprocess.run(['journalctl','-u',U,'-n','60','--no-pager','-q','-o','cat'],capture_output=True,text=True,timeout=30).stdout
    except Exception as e:
        print(f'-- {U}: error {e}'); continue
    lines=[l for l in out.split('\n') if l.strip()]
    cats=set()
    ip=re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')
    email=re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
    for l in lines:
        if ip.search(l): cats.add('IP 있음')
        if re.search(r'\b(user|uid|session|actor)\b', l, re.I): cats.add('사용자/세션 식별자 있음')
        if email.search(l): cats.add('이메일 있음')
        if re.search(r'(GET|POST|PUT|DELETE) /', l): cats.add('HTTP 요청 라인 있음(경로)')
        if re.search(r'body|payload|json', l, re.I): cats.add('본문 언급 있음')
        if re.search(r'token|secret|key|Bearer', l, re.I): cats.add('키/토큰 언급 있음(값 여부 미판정)')
    print(f'-- {U}: 최근 {len(lines)}줄 | 항목 종류: ' + (', '.join(sorted(cats)) if cats else '(해당 없음)'))
PYEOF
echo "## A5. 앱 DB 보관 (Chat access log / B14 call ledger)"
python3 - <<'PYEOF'
import sqlite3, glob, os, datetime
cands = []
for pat in ['/opt/padiem/**/*.db','/opt/padiem/**/*.sqlite*','/opt/padiem/**/data/*.db']:
    cands += glob.glob(pat, recursive=True)
seen=set()
for p in sorted(set(cands)):
    if p in seen or os.path.getsize(p)==0: continue
    seen.add(p)
    try:
        con = sqlite3.connect(f'file:{p}?mode=ro', uri=True, timeout=5)
        cur = con.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        interesting = [t for t in tables if any(k in t.lower() for k in ('log','ledger','call','access','event','request'))]
        print(f'-- {p} ({os.path.getsize(p)} B) tables={len(tables)}' + (f' 관련테이블: {interesting}' if interesting else ''))
        for t in interesting[:4]:
            try:
                cnt = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{t}")').fetchall()]
                tcol = next((c for c in cols if c.lower() in ('created_at','ts','time','timestamp','at','created')), None)
                oldest = cur.execute(f'SELECT MIN("{tcol}") FROM "{t}"').fetchone()[0] if tcol else None
                print(f'   {t}: rows={cnt} oldest({tcol})={str(oldest)[:24]}')
            except Exception as e:
                print(f'   {t}: 조회실패 {str(e)[:40]}')
        con.close()
    except Exception as e:
        pass
PYEOF
echo "## B1. 유닛 env 파일에서 CLAW_ENGINE_DESKTOP_SECRET 이름 확인"
for EF in /opt/padiem/chat-com2/.env /opt/padiem/b14/env/b14.env /opt/padiem/p01/.env /opt/padiem/p01/env/*.env /opt/padiem/mesh-queue/queue.env; do
  [ -e "$EF" ] && echo "-- $EF : $(grep -c '^CLAW_ENGINE_DESKTOP_SECRET=' "$EF" 2>/dev/null) 건"
done
echo "## B1-2. padiem-p01 유닛 상세"
systemctl show padiem-p01 -p ActiveState -p FragmentPath -p EnvironmentFiles -p ExecMainPID 2>/dev/null
echo "## B2. /proc environ 로드 확인 (길이+끝4자리만)"
python3 - <<'PYEOF'
import os, hashlib, glob
NAME='CLAW_ENGINE_DESKTOP_SECRET'
targets = {'chat': None, 'p01': None, 'b14': None, 'queue': None}
# systemd main PIDs
import subprocess
for svc in targets:
    try:
        pid = subprocess.check_output(['systemctl','show',svc,'-p','ExecMainPID','--value'], text=True).strip()
        targets[svc] = int(pid) if pid.isdigit() and int(pid)>0 else None
    except: pass
vals={}
for svc,pid in targets.items():
    if not pid:
        print(f'{svc}: PID 없음'); continue
    try:
        raw = open(f'/proc/{pid}/environ','rb').read().decode('utf-8','replace').split('\x00')
        hit = [x for x in raw if x.startswith(NAME+'=')]
        if hit:
            v = hit[0].split('=',1)[1]
            vals[svc]=v
            print(f'{svc} (pid {pid}): 이름 있음 | 길이 {len(v)} | 끝4자리 …{v[-4:]}')
        else:
            print(f'{svc} (pid {pid}): 이름 없음 (environ {len(raw)}개 중)')
    except Exception as e:
        print(f'{svc}: /proc 읽기 실패 {str(e)[:50]}')
if 'chat' in vals and 'p01' in vals:
    print('Chat vs P01 값 일치:', '같음' if hashlib.sha256(vals["chat"].encode()).digest()==hashlib.sha256(vals["p01"].encode()).digest() else '다름')
PYEOF
} > "$OUT" 2>&1
echo "AB2 done"
