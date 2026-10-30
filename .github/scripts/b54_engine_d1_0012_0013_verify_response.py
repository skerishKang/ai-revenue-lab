"""Reject failed or incomplete D1 batch responses."""
import json
import sqlite3
import sys
from pathlib import Path

def count_statements(sql):
    buf=""
    count=0
    for line in sql.splitlines(keepends=True):
        buf+=line
        if sqlite3.complete_statement(buf):
            count+=1
            buf=""
    if buf.strip(): raise ValueError("incomplete SQL")
    return count

def verify(data,sql):
    if not isinstance(data,dict) or data.get("success") is not True: raise ValueError("D1 apply failed")
    blocks=data.get("result")
    if not isinstance(blocks,list) or len(blocks)!=count_statements(sql) or any(not isinstance(x,dict) or x.get("success") is not True for x in blocks):
        raise ValueError("D1 batch incomplete or failed")

if __name__=="__main__":
    data=json.loads(Path(sys.argv[1]).read_text(encoding="utf8"))
    payload=json.loads(Path(sys.argv[2]).read_text(encoding="utf8"))
    verify(data,payload["sql"])
    print("D1_BATCH_RESPONSE=PASS")
