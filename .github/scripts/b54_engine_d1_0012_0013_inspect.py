"""Read-only D1 inventory for the engine apply gate."""
import json
import os
import sys
import urllib.request
from pathlib import Path
import b54_engine_d1_0009_0013_schema as schema
import b54_engine_d1_0009_0013_foreign_keys as fk
import b54_engine_d1_0012_0013_apply_evidence as evidence

ACCOUNT="9be14bb7b8974e65d0afba647ab16932"
DB="6b77ad02-bc27-488f-bb97-6325f6750cba"

def query(sql):
    if os.environ.get("CLOUDFLARE_ACCOUNT_ID") != ACCOUNT: raise ValueError("account mismatch")
    token=os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token: raise ValueError("token unavailable")
    url=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DB}/query"
    request=urllib.request.Request(url,data=json.dumps({"sql":sql}).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(request,timeout=30) as response:
        return json.load(response)

def table_counts():
    inventory=fk.rows(query(fk.TABLES_QUERY))
    names=[]
    for row in inventory:
        if not isinstance(row,dict) or not isinstance(row.get("name"),str) or not row["name"] or "\x00" in row["name"] or row["name"] in names:
            raise ValueError("invalid table list")
        names.append(row["name"])
    if not names or len(names)>450: raise ValueError("unsupported table count")
    def lit(name): return "'"+name.replace("'","''")+"'"
    def ident(name): return '"'+name.replace('"','""')+'"'
    sql=" UNION ALL ".join("SELECT "+lit(n)+" AS name, count(*) AS n FROM "+ident(n) for n in names)
    return evidence.counts(query(sql),set(names))

def inspect():
    payload=query(schema.schema_sql())
    states,grouped=schema.classify(payload)
    data={"migrations":states,"indexes":sorted(x[1] for x in grouped[evidence.RUNS] if x[0]=="index"),"rebuild_table":evidence.RUNS}
    counts=table_counts()
    return data,counts

def as_payload(counts):
    return {"success":True,"result":[{"success":True,"results":[{"name":k,"n":v} for k,v in counts.items()]}]}

def main():
    mode,path=sys.argv[1:]
    current,counts=inspect()
    if mode=="before":
        fks=fk.inventory(query)
        selected={k:counts[k] for k in (evidence.XLSX,evidence.QUOTE,evidence.RUNS)}
        evidence.before(current,as_payload(selected),fks)
        Path(path).write_text(json.dumps(counts,sort_keys=True),encoding="utf8")
        print("PRECHECK=PASS",json.dumps({"migrations":current["migrations"],"counts":selected,"inbound_foreign_keys":len(fks["inbound_foreign_keys"])}))
    elif mode=="after":
        baseline=json.loads(Path(path).read_text(encoding="utf8"))
        if not isinstance(baseline,dict) or any(type(v)!=int or v<0 for v in baseline.values()): raise ValueError("bad baseline")
        selected={k:counts[k] for k in (evidence.XLSX,evidence.QUOTE,evidence.RUNS,evidence.RESULTS)}
        evidence.after(current,as_payload(selected),{k:baseline[k] for k in (evidence.XLSX,evidence.QUOTE,evidence.RUNS)})
        if any(k not in counts or counts[k]!=v for k,v in baseline.items()): raise ValueError("existing table counts changed")
        print("POSTCHECK=PASS",json.dumps({"migrations":current["migrations"],"existing_tables_preserved":len(baseline),"indexes":current["indexes"]}))
    else: raise ValueError("invalid mode")

if __name__=="__main__":
    try: main()
    except Exception as exc:
        print("ENGINE_APPLY_INSPECTION=FAIL: "+type(exc).__name__,file=sys.stderr)
        sys.exit(1)
