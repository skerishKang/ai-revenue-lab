"""10 manual live Step 5 quote-implementation probes; no retries or CI network."""
import argparse, asyncio, ast, copy, json, time
from pathlib import Path
MID="kilo/stepfun/step-5-preview-free"; UP="stepfun/step-5-preview-free"
KEYS=("subtotal_krw","discount_krw","vat_krw","shipping_krw","total_krw")
base="한국어 견적서 검증. JSON 객체만, 키는 subtotal_krw,discount_krw,vat_krw,shipping_krw,total_krw, 전부 정수. 상품대금 할인 후 부가세, 배송비 비과세·비할인. VAT 원단위 사사오입. 설명/Markdown 금지. "
cases=[
("01_basic","과세 A 32000원 2개, 할인0, VAT10%, 배송0.",(64000,0,6400,0,70400)),
("02_discount","과세 A 17500원 3개, 과세 B 23000원 2개, 상품합계 10%할인, VAT10%, 배송5000.",(98500,9850,8865,5000,102515)),
("03_coupon","과세 A 25000원 4개, 상품고정할인12500, VAT10%, 배송0.",(100000,12500,8750,0,96250)),
("04_exempt","면세 A 50000원 1개, 과세 B 20000원 1개, 할인0, 과세만 VAT10%, 배송0.",(70000,0,2000,0,72000)),
("05_zero_qty","과세 A 20000원 0개, B 0원 1개, C 3500원 3개, 할인0, VAT10%, 배송3000.",(10500,0,1050,3000,14550)),
("06_zero_vat","상품75000원 1개, 고정할인5000, VAT0%, 배송2500.",(75000,5000,0,2500,72500)),
("07_rounding","과세 A 9999원 9개, 할인0, VAT10% 원단위 사사오입, 배송0.",(89991,0,8999,0,98990)),
("08_twelve_items","과세 상품 12종 각각1000원 1개, 할인0, VAT10%, 배송10000.",(12000,0,1200,10000,23200)),
]
TASKS=[dict(id=i,kind="math",prompt=base+desc,expected=dict(zip(KEYS,nums))) for i,desc,nums in cases]
TASKS.append(dict(id="09_html",kind="html",expected={"subtotal_krw":25000,"vat_krw":2500,"total_krw":27500},
prompt="견적서 A4 인쇄 HTML 구현: 고객명은 <script>alert(1)</script> 고객. 과세 상품 A 25000원 1개, VAT10%, 할인/배송0. JSON 객체 1개만 출력. 키는 subtotal_krw,vat_krw,total_krw,html. html 문자열에는 @page CSS, table, 소계·VAT·총액, 고객명은 &lt;script&gt;로 안전하게 escape, 원본 script 태그 금지."))
TASKS.append(dict(id="10_python_code",kind="code",expected=None,
prompt="Python3 견적서 계산 함수 calculate_quote(items, discount_percent, shipping_krw)만 코드로 구현. items 원소는 qty,unit_price 정수인 dict. 상품 소계와 할인액=소계*할인율% 사사오입 정수, VAT=할인후 상품금액*10% 사사오입, 배송비는 비과세. 반환 dict에 정확히 subtotal_krw,discount_krw,vat_krw,shipping_krw,total_krw. 입력 불변, import/Markdown/설명 금지."))
assert len(TASKS)==10
def grade(task,answer):
 if task["kind"]!="code":
  try:x=json.loads(answer.strip())
  except ValueError:return False,{"issue":"invalid_json"}
  expected=task["expected"]
  shape=set(x)==(set(KEYS) if task["kind"]=="math" else set(expected)|{"html"})
  values=all(type(x.get(k)) is int and x[k]==v for k,v in expected.items())
  detail={"expected":expected,"received":{k:x.get(k) for k in expected},"valid_shape":shape}
  if task["kind"]=="html":
   html=x.get("html","")
   safe=isinstance(html,str) and "<script>" not in html.lower() and "&lt;script&gt;" in html
   printable=isinstance(html,str) and "<table" in html.lower() and "@page" in html.lower()
   detail.update(safe=safe,printable=printable,html_length=len(html) if isinstance(html,str) else 0)
   return bool(shape and values and safe and printable),detail
  return bool(shape and values),detail
 if chr(96)*3 in answer:return False,{"issue":"code_fence"}
 try:
  t=ast.parse(answer.strip())
  if len(t.body)!=1 or not isinstance(t.body[0],ast.FunctionDef) or t.body[0].name!="calculate_quote":return False,{"issue":"function_shape"}
  if any(isinstance(n,(ast.Import,ast.ImportFrom,ast.With,ast.AsyncWith,ast.Try,ast.Raise,ast.Global)) for n in ast.walk(t)):return False,{"issue":"forbidden_syntax"}
  import builtins
  allowed={n:getattr(builtins,n) for n in ("sum","len","range","min","max","int","round","enumerate","sorted","list","dict","abs")}
  # Strict syntax gate before running untrusted output in a local test.
  # No import, attribute access, infinite while, arbitrary builtins or dunder names.
  if any(isinstance(n,(ast.Attribute,ast.While,ast.ClassDef,ast.Lambda,ast.Delete,
                         ast.AsyncFunctionDef,ast.Await,ast.Yield,ast.YieldFrom))
         for n in ast.walk(t)):return False,{"issue":"unsafe_construct"}
  if any(isinstance(n,ast.Name) and n.id.startswith("__") for n in ast.walk(t)):
   return False,{"issue":"dunder_access"}
  if any(isinstance(n,ast.Call) and (
       not isinstance(n.func,ast.Name) or n.func.id not in allowed)
       for n in ast.walk(t)):return False,{"issue":"unapproved_function_call"}
  namespace={"__builtins__":allowed}
  exec(compile(t,"<approved-test-only-model-code>","exec"),namespace)
  fixtures=[
   ([{"qty":2,"unit_price":32000}],0,0,(64000,0,6400,0,70400)),
   ([{"qty":3,"unit_price":17500},{"qty":2,"unit_price":23000}],10,5000,(98500,9850,8865,5000,102515)),
   ([{"qty":0,"unit_price":20000}],0,0,(0,0,0,0,0)),
   ([{"qty":4,"unit_price":25000}],25,2500,(100000,25000,7500,2500,85000)),
   ([{"qty":9,"unit_price":9999}],0,0,(89991,0,8999,0,98990))]
  count=0
  for items,discount,shipping,expected in fixtures:
   src=copy.deepcopy(items)
   got=namespace["calculate_quote"](items,discount,shipping)
   count+=bool(got==dict(zip(KEYS,expected)) and items==src)
  return count==len(fixtures),{"unit_pass":count,"unit_total":len(fixtures)}
 except Exception as e:return False,{"issue":type(e).__name__,"detail":str(e)[:180]}
async def one(task):
 from app.pilot.platform import call_platform_chat_completions
 st=time.monotonic()
 try:
  response=await asyncio.wait_for(call_platform_chat_completions(
   model_id=MID,upstream_model=UP,provider="Kilo Gateway / StepFun",platform_provider_id="kilo",
   messages=[{"role":"user","content":task["prompt"]}],temperature=0.0,
   max_tokens=2200 if task["kind"]!="math" else 950),timeout=42)
  m=response["choices"][0].get("message") or {}
  content=m.get("content")
  if not isinstance(content,str):return {"id":task["id"],"status":"empty","pass":False}
  passed,detail=grade(task,content)
  return {"id":task["id"],"status":"completed","pass":passed,"duration_ms":round((time.monotonic()-st)*1000),
          "actual_model":response["model"],"usage":response.get("usage"),"detail":detail,"answer_excerpt":content[:360]}
 except Exception as e:return {"id":task["id"],"status":"error","pass":False,"duration_ms":round((time.monotonic()-st)*1000),
                            "error_type":type(e).__name__,"error_message":str(e)[:190]}
async def main(path):
 from app.pilot.model_registry_file import installed_model_ids
 assert MID in installed_model_ids(),"model not in JSON registry"
 results=[]
 for idx,task in enumerate(TASKS,1):
  result=await one(task)
  results.append(result)
  path.write_text(json.dumps({"model":MID,"total":10,"attempted":len(results),"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
  print(f"CASE={idx}/10 ID={task['id']} STATUS={result['status']} PASS={result['pass']} LATENCY_MS={result.get('duration_ms')} ERROR={result.get('error_type','')}",flush=True)
 print("DONE",len(results),"PASS",sum(r["pass"] for r in results),"COMPLETED",sum(r["status"]=="completed" for r in results),flush=True)
if __name__=="__main__":
 p=argparse.ArgumentParser()
 p.add_argument("--live",action="store_true")
 p.add_argument("--output",type=Path,default=Path(r"E:\stepfun-quote-10-evidence-261009.json"))
 opts=p.parse_args()
 if not opts.live:
  for t in TASKS:print("DRY",t["id"],t["kind"])
 else:
  import os
  if os.environ.get("B14_PROVIDER_MODE")!="live":raise SystemExit("live flag and B14_PROVIDER_MODE=live required")
  asyncio.run(main(opts.output))
