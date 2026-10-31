"""Verify live Worker binding identity before operating on Engine D1."""
import json
import sys
from pathlib import Path
DB="6b77ad02-bc27-488f-bb97-6325f6750cba"
def verify(data):
    if not isinstance(data,dict) or data.get("success") is not True: raise ValueError("worker settings unavailable")
    result=data.get("result")
    if not isinstance(result,dict) or not isinstance(result.get("bindings"),list): raise ValueError("bindings unavailable")
    hits=[b for b in result["bindings"] if isinstance(b,dict) and b.get("name")=="ENGINE_IDEMPOTENCY" and b.get("type")=="d1"]
    if len(hits)!=1 or hits[0].get("id")!=DB: raise ValueError("binding mismatch")
if __name__=="__main__":
    verify(json.loads(Path(sys.argv[1]).read_text(encoding="utf8")))
    print("ENGINE_BINDING_ID=VERIFIED")
