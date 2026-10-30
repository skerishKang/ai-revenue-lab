#!/usr/bin/env python3
"""Read-only inbound FK inventory for Engine D1. No data rows are read."""
import json
import os
import sys
import urllib.request

DATABASE = "6b77ad02-bc27-488f-bb97-6325f6750cba"
ACCOUNT = "9be14bb7b8974e65d0afba647ab16932"
TARGET = "padiem_engine_agent_runs_v1"
TABLES_QUERY = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"

def pragma_for(name):
    if not isinstance(name, str) or not name or len(name) > 255 or "\x00" in name:
        raise ValueError("invalid table name")
    return "PRAGMA foreign_key_list('" + name.replace("'", "''") + "')"

def rows(payload):
    if not isinstance(payload,dict) or payload.get("success") is not True:
        raise ValueError("D1 API failure")
    blocks=payload.get("result")
    if not isinstance(blocks,list) or len(blocks)!=1 or blocks[0].get("success") is not True or not isinstance(blocks[0].get("results"),list):
        raise ValueError("D1 response failure")
    return blocks[0]["results"]

def inventory(query):
    def tables():
        data=rows(query(TABLES_QUERY))
        names=[r.get("name") for r in data if isinstance(r,dict)]
        if len(names)!=len(data) or len(names)>500 or len(set(names))!=len(names):
            raise ValueError("invalid table inventory")
        for name in names: pragma_for(name)
        return sorted(names)
    before=tables()
    refs=[]
    for name in before:
        for row in rows(query(pragma_for(name))):
            if not isinstance(row,dict) or not isinstance(row.get("table"),str):
                raise ValueError("invalid FK result")
            if row["table"].casefold()==TARGET.casefold():
                refs.append({"table":name, "on_delete":row.get("on_delete"), "on_update":row.get("on_update")})
    if before!=tables(): raise ValueError("table inventory changed during inspection")
    return {"inbound_foreign_keys":refs,"tables_inspected":len(before)}

def main():
    if os.environ.get("CLOUDFLARE_ACCOUNT_ID")!=ACCOUNT: raise ValueError("account mismatch")
    token=os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token: raise ValueError("token missing")
    url=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"
    def query(sql):
        req=urllib.request.Request(url,data=json.dumps({"sql":sql}).encode(),
            headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=30) as response: return json.load(response)
    print(json.dumps(inventory(query),indent=2))
    return 0

if __name__=="__main__":
    try: sys.exit(main())
    except Exception:
        print("FOREIGN_KEY_INVENTORY=UNAVAILABLE",file=sys.stderr)
        sys.exit(1)
