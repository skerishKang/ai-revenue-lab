"""Synthetic post-deploy upload probes; never log payloads or credentials."""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import tempfile
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPRedirectHandler

FIXTURES = Path(__file__).resolve().parent / 'smoke-fixtures'

class ProbeError(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def request(opener, url, method='GET', data=None, headers=None):
    req = Request(url, data=data, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=110) as r:
            return r.status, r.read(20_000_001)
    except HTTPError as e:
        return e.code, e.read(100_001)

def call_json(opener, url, method='GET', payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    status, body = request(opener, url, method, data, {'Content-Type': 'application/json'} if data else None)
    try:
        return status, json.loads(body)
    except (ValueError, UnicodeError):
        return status, {}

def require(ok, code):
    if not ok:
        raise ProbeError(code)

def file_request(opener, url, payload, name, mime):
    return request(opener, url, 'POST', payload, {'Content-Type':'application/octet-stream',
        'X-Padiem-Filename':name, 'X-Padiem-Media-Type':mime})

def fixture_probe(name, upload, verify, cleanup):
    """One lifecycle for each probe, including cleanup on a failed verification."""
    resource = None
    verdict, reason = 'PASS', '정리: 일부 남음(작업 기록)'
    try:
        resource = upload()
        verify(resource)
    except ProbeError as e:
        verdict, reason = 'FAIL', str(e) + '; 정리: 일부 남음(작업 기록)'
    except Exception:
        verdict, reason = 'FAIL', '점검 요청 실패; 정리: 일부 남음(작업 기록)'
    finally:
        if resource is not None:
            try:
                result = cleanup(resource)
                if isinstance(result, tuple) and result[0] not in (200, 204):
                    raise ProbeError('cleanup')
            except Exception:
                verdict, reason = 'FAIL', '시험 데이터 정리 실패; 정리: 일부 남음(작업 기록)'
    return (name, verdict, reason)

def run_probes(base, opener=None):
    base = base.rstrip('/')
    opener = opener or build_opener(HTTPCookieProcessor(CookieJar()), NoRedirect())
    names = ('암호 문서 안내', 'HWPX 본문 추출', 'PDF→MD 변환', '견적 XLSX→PDF')
    project = None
    rows = []
    try:
        username, password = os.environ.get('B66_CGI_ALPHA_USERNAME'), os.environ.get('B66_CGI_ALPHA_PASSWORD')
        require(username and password, '시험 계정 정보 없음')
        status, body = call_json(opener, base + '/api/auth/password/login', 'POST', {'identifier':username,'password':password})
        require(status == 200 and body.get('ok') is True, '시험 계정 로그인 실패')
        status, body = call_json(opener, base + '/api/projects', 'POST', {'name':'smoke-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'), 'instructions':''})
        candidate = body.get('project', {}).get('id')
        require(status == 201 and isinstance(candidate, str) and re.fullmatch(r'[A-Za-z0-9_-]+', candidate), '시험 프로젝트 생성 실패')
        project = candidate
        project_path = base + '/api/projects/' + project
        def lane_upload(filename):
            data = (FIXTURES / filename).read_bytes()
            s, ticket = call_json(opener, base + '/api/files/ticket', 'POST', {'size_bytes': len(data)})
            require(s == 200 and ticket.get('ok') is True, '파일 업로드 준비 실패')
            target = urlsplit(ticket.get('upload_url', ''))
            require(target.scheme == 'https' and target.hostname and
                    (target.hostname == 'padiem.net' or target.hostname.endswith('.padiem.net')) and
                    target.path == '/files' and not target.username and not target.password and
                    not target.query and not target.fragment, '파일 서버 주소 오류')
            headers = ticket.get('headers')
            require(isinstance(headers, dict), '파일 업로드 준비 실패')
            s, raw = request(opener, ticket['upload_url'] + '?' + urlencode({'filename': 'smoke-' + filename}), 'POST', data, headers)
            try: obj = json.loads(raw)
            except (ValueError, UnicodeError): obj = {}
            if filename.endswith('.hwpx') and s == 415 and obj.get('error', {}).get('code') == 'unsupported_file_type':
                return {'not_deployed': True}
            fid = obj.get('file_id', '')
            require(s == 201 and re.fullmatch(r'file_[a-f0-9]{32}', fid), '파일 업로드 실패')
            return {'id': fid, 'headers': headers, 'origin': target.scheme + '://' + target.netloc}
        def encrypted_check(item):
            s, body = call_json(opener, base + '/api/chat', 'POST', {
                'project_id': project, 'messages': [{'role':'user','content':'이 문서를 확인해 주세요'}],
                'attachments':[{'type':'file','file_id':item['id']}]})
            msg = body.get('error',{}).get('message','')
            require(s == 422 and isinstance(msg,str) and ('암호' in msg or '비밀번호' in msg), '암호 문서 안내 불일치')
        rows.append(fixture_probe(names[0], lambda:lane_upload('encrypted.pdf'), encrypted_check, lambda _:None))
        hwpx_absent = []
        def hwpx_check(item):
            if item.get('not_deployed'):
                hwpx_absent.append(True)
                return
            s, text = request(opener, item['origin'] + '/files/' + item['id'] + '/text', headers=item['headers'])
            require(s == 200 and b'smoke sample text' in text.lower(), 'HWPX 본문 추출 실패')
        hwpx = fixture_probe(names[1], lambda:lane_upload('sample.hwpx'), hwpx_check, lambda _:None)
        if hwpx_absent:
            hwpx = (names[1], 'SKIP', '해당 없음 — 미배포; 정리: 일부 남음(작업 기록)')
        rows.append(hwpx)
        def pdf_upload():
            status, body = call_json(opener, base + '/api/document-conversions', 'POST', {'mode':'fast'})
            jid = body.get('job',{}).get('id')
            require(status == 201 and isinstance(jid,str) and re.fullmatch(r'[A-Za-z0-9_-]+',jid), '변환 작업 생성 실패')
            status, raw = file_request(opener, base + '/api/document-conversions/' + jid + '/files', (FIXTURES/'sample.pdf').read_bytes(), 'smoke-sample.pdf','application/pdf')
            try: body = json.loads(raw)
            except (ValueError, UnicodeError): body = {}
            items = body.get('items',[])
            require(status == 201 and len(items)==1 and re.fullmatch(r'[A-Za-z0-9_-]+',items[0].get('id','')), '변환 파일 업로드 실패')
            return items[0]['id']
        def pdf_verify(item):
            s, _ = request(opener, base + '/api/document-conversions/items/'+item+'/run','POST', b'')
            require(s == 200, 'PDF 변환 실패')
            s, content = request(opener, base + '/api/document-conversions/items/'+item+'/markdown')
            require(s == 200 and bool(content.strip()), '변환 결과가 비어 있음')
        rows.append(fixture_probe(names[2], pdf_upload, pdf_verify, lambda item: request(opener,base+'/api/document-conversions/items/'+item,'DELETE')))
        def quote_upload():
            return lane_upload('quote.xlsx')['id']
        def quote_verify(fid):
            s,content=request(opener,base+'/api/b66/pc-quote/pdf?'+urlencode({'file_id':fid}))
            require(s==200 and content.startswith(b'%PDF-'),'견적 PDF 생성 실패')
            try:
                from pypdf import PdfReader
                import io
                count=len(PdfReader(io.BytesIO(content)).pages)
            except ImportError:
                with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
                    f.write(content); f.flush()
                    out=subprocess.run(['pdfinfo',f.name],capture_output=True,text=True,timeout=20,check=True).stdout
                    match=re.search(r'^Pages:\s*(\d+)\s*$',out,re.M)
                    count=int(match.group(1)) if match else 0
            require(count>=1,'견적 PDF 페이지 없음')
        rows.append(fixture_probe(names[3],quote_upload,quote_verify,lambda _:None))
    except ProbeError as e:
        rows.extend((name,'FAIL',str(e)) for name in names[len(rows):])
    except Exception:
        rows.extend((name,'FAIL','시험 준비 실패') for name in names[len(rows):])
    finally:
        if project:
            try:
                s,_ = request(opener, base+'/api/projects/'+project, 'DELETE')
                if s not in (200,204): rows.append(('시험 프로젝트 정리','FAIL','삭제 실패'))
            except Exception:
                rows.append(('시험 프로젝트 정리','FAIL','삭제 실패'))
    return rows
