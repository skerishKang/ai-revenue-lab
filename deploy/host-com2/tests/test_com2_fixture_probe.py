import importlib.util
import json
from pathlib import Path
import pytest

path = Path(__file__).resolve().parents[1] / 'com2_fixture_probe.py'
spec = importlib.util.spec_from_file_location('fixture_probe', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Response:
    def __init__(self, status, content): self.status,self.content=status,content
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,*args): return self.content

class Fake:
    def __init__(self, hwpx_absent=False, fail_convert=False):
        self.events=[]; self.hwpx_absent=hwpx_absent; self.fail_convert=fail_convert
    def open(self, req, timeout):
        url=req.full_url; method=req.method
        self.events.append((method,url))
        def reply(s, obj): return Response(s, json.dumps(obj,ensure_ascii=False).encode())
        if url.endswith('/api/auth/password/login'): return reply(200,{'ok':True})
        if url.endswith('/api/projects') and method=='POST': return reply(201,{'project':{'id':'proj_smoke'}})
        if url.endswith('/api/projects/proj_smoke') and method=='DELETE': return reply(200,{})
        if url.endswith('/api/files/ticket'): return reply(200,{'ok':True,'upload_url':'https://files.padiem.net/files','headers':{}})
        if '/files?filename=' in url:
            if 'hwpx' in url and self.hwpx_absent: return reply(415,{'error':{'code':'unsupported_file_type'}})
            return reply(201,{'file_id':'file_'+'a'*32})
        if url.endswith('/text'): return Response(200,b'smoke sample text')
        if url.endswith('/api/chat'): return reply(422,{'error':{'message':'암호를 풀고 다시 올려 주세요'}})
        if url.endswith('/api/document-conversions'): return reply(201,{'job':{'id':'job_1'}})
        if url.endswith('/job_1/files'): return reply(201,{'items':[{'id':'item_1'}]})
        if url.endswith('/item_1/run'): return reply(503 if self.fail_convert else 200,{})
        if url.endswith('/item_1/markdown'): return Response(200,b'# smoke')
        if url.endswith('/items/item_1') and method=='DELETE': return reply(200,{})
        if '/api/b66/pc-quote/pdf?' in url: return Response(200,(m.FIXTURES/'sample.pdf').read_bytes())
        raise AssertionError(url)

@pytest.mark.parametrize('absent', [True, False])
def test_all_checks_and_cleanup(monkeypatch, absent):
    monkeypatch.setenv('B66_CGI_ALPHA_USERNAME','test')
    monkeypatch.setenv('B66_CGI_ALPHA_PASSWORD','test')
    fake=Fake(hwpx_absent=absent)
    rows=m.run_probes('https://chat.padiem.net',fake)
    assert [r[1] for r in rows] == ['PASS','SKIP' if absent else 'PASS','PASS','PASS']
    assert ('DELETE','https://chat.padiem.net/api/projects/proj_smoke') in fake.events
    assert ('DELETE','https://chat.padiem.net/api/document-conversions/items/item_1') in fake.events

def test_cleanup_on_conversion_failure(monkeypatch):
    monkeypatch.setenv('B66_CGI_ALPHA_USERNAME','test')
    monkeypatch.setenv('B66_CGI_ALPHA_PASSWORD','test')
    fake=Fake(fail_convert=True)
    rows=m.run_probes('https://chat.padiem.net',fake)
    assert rows[2][1]=='FAIL'
    assert ('DELETE','https://chat.padiem.net/api/document-conversions/items/item_1') in fake.events
    assert ('DELETE','https://chat.padiem.net/api/projects/proj_smoke') in fake.events

def test_cleanup_failure_cannot_pass():
    row=m.fixture_probe('sample', lambda: 1, lambda _:None, lambda _: (503,b''))
    assert row[1]=='FAIL'
