#!/usr/bin/env python3
"""Read-only inbound FK inventory from sqlite_master CREATE TABLE SQL."""
import json
import os
import re
import sys
import urllib.request

DATABASE = "6b77ad02-bc27-488f-bb97-6325f6750cba"
ACCOUNT = "9be14bb7b8974e65d0afba647ab16932"
TARGET = "padiem_engine_agent_runs_v1"
TABLES_QUERY = "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
# Tokenize quoted identifiers, string literals, comments and ordinary identifiers.
TOKEN = re.compile(r"""\s+|--[^\r\n]*|/\*[\s\S]*?\*/|"(?:""|[^"])*"|'(?:''|[^'])*'|`(?:``|[^`])*`|\[[^\]]*\]|[A-Za-z_][A-Za-z_0-9$]*|.""")
def references(sql):
    if not isinstance(sql, str) or not sql: raise ValueError("missing CREATE SQL")
    tokens = [m.group() for m in TOKEN.finditer(sql)]
    tokens = [x for x in tokens if not x.isspace() and not x.startswith(("--", "/*"))]
    found = False
    for i, token in enumerate(tokens):
        if token.casefold() != "references": continue
        if i + 1 >= len(tokens): raise ValueError("unparseable REFERENCES")
        name = tokens[i + 1]
        if name[0] in ('"', "'", "`", "["):
            end = "]" if name[0] == "[" else name[0]
            if not name.endswith(end) or len(name) < 2: raise ValueError("unparseable identifier")
            name = name[1:-1].replace(end + end, end)
        elif not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9$]*", name):
            raise ValueError("unparseable REFERENCES")
        if name.casefold() == TARGET.casefold(): found = True
    return found

def rows(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True: raise ValueError("D1 API failure")
    blocks = payload.get("result")
    if not isinstance(blocks,list) or len(blocks)!=1 or not isinstance(blocks[0],dict) or blocks[0].get("success") is not True or not isinstance(blocks[0].get("results"),list): raise ValueError("D1 response failure")
    return blocks[0]["results"]

def inventory(query):
    def tables():
        data=rows(query(TABLES_QUERY))
        if len(data)>500: raise ValueError("too many tables")
        result={}
        for row in data:
            if not isinstance(row,dict) or not isinstance(row.get("name"),str) or not isinstance(row.get("sql"),str) or row["name"] in result: raise ValueError("invalid table inventory")
            result[row["name"]] = row["sql"]
        return result
    before=tables()
    refs=[{"table": name} for name,sql in before.items() if references(sql)]
    if before!=tables(): raise ValueError("schema changed during inspection")
    return {"inbound_foreign_keys":refs,"tables_inspected":len(before)}

def main():
    if os.environ.get("CLOUDFLARE_ACCOUNT_ID")!=ACCOUNT: raise ValueError("account mismatch")
    token=os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token: raise ValueError("token missing")
    url=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"
    def query(sql):
        req=urllib.request.Request(url,data=json.dumps({"sql":sql}).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=30) as response: return json.load(response)
    print(json.dumps(inventory(query),indent=2))
    return 0

if __name__=="__main__":
    try: sys.exit(main())
    except Exception:
        print("FOREIGN_KEY_INVENTORY=UNAVAILABLE",file=sys.stderr)
        sys.exit(1)
