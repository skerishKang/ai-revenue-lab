#!/usr/bin/env python3
from __future__ import annotations
from html.parser import HTMLParser
from pathlib import Path
import json, re, sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_TEXT = [ROOT/'index.html', ROOT/'styles.css', ROOT/'app.js']
EVIDENCE = ROOT/'evidence'
EVIDENCE.mkdir(parents=True, exist_ok=True)

class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.assets=[]
    def handle_starttag(self, tag, attrs):
        values=dict(attrs)
        if tag in {'img','script'} and values.get('src'): self.assets.append(values['src'])
        if tag=='link' and values.get('href'): self.assets.append(values['href'])

errors=[]
parser=AssetParser(); parser.feed((ROOT/'index.html').read_text(encoding='utf-8'))
for ref in parser.assets:
    if ref.startswith(('http://','https://','//','data:')):
        errors.append(f'external or embedded runtime reference: {ref}')
        continue
    if not (ROOT/ref).is_file(): errors.append(f'missing local asset: {ref}')

external_pattern=re.compile(r'''(?:https?:)?//|url\(\s*['"]?https?:|fetch\s*\(|XMLHttpRequest|WebSocket''',re.I)
for path in RUNTIME_TEXT:
    text=path.read_text(encoding='utf-8')
    if external_pattern.search(text): errors.append(f'network-capable or external reference in {path.relative_to(ROOT)}')

required_files=['README.md','REFERENCE_NOTES.md','IMAGE_SOURCES.md','MOTION_SPEC.md','index.html','styles.css','app.js']
for name in required_files:
    if not (ROOT/name).is_file(): errors.append(f'missing required file: {name}')
asset_count=len(list((ROOT/'assets/images').glob('*')))
if asset_count < 8: errors.append(f'asset count {asset_count} < 8')

required_labels=[
'DATA OWNER','REQUESTER','CONNECTOR OPERATOR','AUTHORIZED PURPOSE','REQUESTED SCOPE','APPROVED SCOPE',
'LEAST-PRIVILEGE ACCESS','METADATA PERMISSION','CONTENT PERMISSION','PERMITTED PATH','PROHIBITED PATH',
'SENSITIVE FIELD — EXCLUDED','CREDENTIAL REFERENCE — VALUE NOT STORED','NO SECRET DISPLAY','RETENTION LIMIT',
'DELETION REQUIREMENT','AUDIT EVIDENCE — NOT EMPLOYEE MONITORING','ACCESS REVOCABLE','INCIDENT HANDOFF',
'ACCESS APPROVAL ≠ DATA-USE APPROVAL','CONNECTOR READINESS — NOT CONNECTED',
'HUMAN-APPROVED PRIVATE DATA CONNECTOR ACCESS SPEC','VISUAL REFERENCE ONLY',
'NO LIVE PRIVATE DATA, CREDENTIAL, EXTRACTION, OR MODEL-TRAINING CONNECTION']
html=(ROOT/'index.html').read_text(encoding='utf-8')
for label in required_labels:
    if label not in html: errors.append(f'missing required label: {label}')

report={
    'status':'PASS' if not errors else 'FAIL',
    'asset_count':asset_count,
    'local_references':parser.assets,
    'external_runtime_requests':0 if not any('external' in e or 'network' in e for e in errors) else None,
    'errors':errors,
}
(EVIDENCE/'static-contract.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
sys.exit(1 if errors else 0)
