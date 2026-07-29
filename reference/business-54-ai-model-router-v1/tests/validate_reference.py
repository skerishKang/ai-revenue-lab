from html.parser import HTMLParser
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'index.html').read_text(encoding='utf-8')
css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
manifest=(ROOT/'IMAGE_SOURCES.md').read_text(encoding='utf-8')
notes=(ROOT/'REFERENCE_NOTES.md').read_text(encoding='utf-8')
states=['cover','task','candidates','policy','fallback','decision','mobile']
labels=['SYNTHETIC ROUTING CASE','TASK REQUIREMENT','HARD CONSTRAINT','WEIGHTED PREFERENCE','MODEL CANDIDATE — FICTIONAL','DOMESTIC CANDIDATE','EXTERNAL CANDIDATE','LOCAL CANDIDATE','QUALITY EVIDENCE — SYNTHETIC','COST ESTIMATE — NOT A QUOTE','LATENCY ESTIMATE','PRIVACY BOUNDARY','AVAILABILITY — UNKNOWN / UNAVAILABLE','CANDIDATE EXCLUDED','PRIMARY ROUTE — NOT EXECUTED','FALLBACK ROUTE — NOT EXECUTED','NO SAFE ROUTE','HUMAN HANDOFF','BEST MODEL NOT CLAIMED','MODEL/PROVIDER NOT ACTIVATED','HUMAN-APPROVED MODEL ROUTING POLICY','VISUAL REFERENCE ONLY','NO LIVE MODEL CALL, API KEY, BILLING, OR ROUTING EXECUTION']
persistent=['HARD CONSTRAINT','CANDIDATE EXCLUDED','AVAILABILITY — UNKNOWN / UNAVAILABLE','PRIMARY ROUTE — NOT EXECUTED','FALLBACK ROUTE — NOT EXECUTED','NO SAFE ROUTE','HUMAN HANDOFF','BEST MODEL NOT CLAIMED','MODEL/PROVIDER NOT ACTIVATED']
forbidden=['UNIVERSAL BEST MODEL','PROVIDER ACTIVATED','MODEL CALL EXECUTED','API KEY CONNECTED','BILLING ACTIVE','UNAVAILABLE CANDIDATE SELECTED','PRIVACY WEIGHTED PREFERENCE']
class P(HTMLParser):
 def __init__(self):super().__init__();self.tabs=[];self.panels=[];self.ids=[]
 def handle_starttag(self,tag,attrs):
  d={k:v or '' for k,v in attrs}
  if d.get('id'):self.ids.append(d['id'])
  if d.get('role')=='tab':self.tabs.append(d)
  if d.get('role')=='tabpanel':self.panels.append(d)
p=P();p.feed(html)
assets=sorted((ROOT/'assets/images').glob('*.svg'))
checks={
'exact_states':[x.get('data-state') for x in p.panels]==states,
'exact_controls':[x.get('data-state-control') for x in p.tabs]==states,
'tab_panel_count':len(p.tabs)==len(p.panels)==7,
'unique_ids':len(p.ids)==len(set(p.ids)),
'reciprocal_aria':all(t.get('id')==f'tab-{s}' and t.get('aria-controls')==f'panel-{s}' and q.get('id')==f'panel-{s}' and q.get('aria-labelledby')==f'tab-{s}' for s,t,q in zip(states,p.tabs,p.panels)),
'required_labels':all(x in html for x in labels),
'persistent_decision_mobile':all(html.count(x)>=2 for x in persistent),
'forbidden_absent':not any(x in html for x in forbidden),
'assets_at_least_8':len(assets)>=8,
'assets_documented':all(a.name in manifest for a in assets),
'focal_assets':all((ROOT/'assets/images'/n).exists() for n in ['task-requirement-manifest.svg','candidate-route-switchyard.svg','constraint-gate.svg','fallback-handoff-ledger.svg']),
'asset_manifest_columns':all(x in manifest for x in ['Asset type','Role','Source / ownership','Licence basis','Creation date','Intended use']),
'research_comparables':all(x in notes for x in ['OpenRouter','LiteLLM','Portkey','AWS Bedrock']),
'research_editorial':all(x in notes for x in ['NASA Graphics Standards Manual','Harry Beck','The Pudding']),
'local_runtime':not re.search(r'(?:src|href)="https?://|//cdn',html+css+js),
'deterministic_version':'amr-v1-20260730' in html,
'animationend':'animationend' in js and 'routingPolicyComplete' in js,
'no_timeout':'setTimeout' not in js,
'motion_760':bool(re.search(r'routingPolicyComplete\s+110ms\s+650ms',css)),
'reduced_motion':'prefers-reduced-motion:reduce' in css,
'no_live_capabilities':not re.search(r'fetch\(|XMLHttpRequest|WebSocket|localStorage|sessionStorage|getUserMedia|geolocation',js),
}
assert all(checks.values()),{k:v for k,v in checks.items() if not v}
out={'status':'PASS','checks':checks,'states':states,'assets':len(assets),'matrix_contract':21,'viewports':[[1440,1100],[768,1024],[390,844]],'independent_validation':False}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
