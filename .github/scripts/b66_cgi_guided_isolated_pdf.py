"""CGI production-front-end Guided wizard + certified PDF proof.

Temporary Guided draft GET/PUT/DELETE are fulfilled exclusively in this
Playwright browser, never forwarded to server. The existing CGI account's
persistent D1 Guided row is preserved byte-for-byte. Real password login,
approved Saved Skill/CompanyProfile, QuoteCore, CGI preview and PDF download.
No provider invocation, source uploads, history or profile mutations.
"""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlparse

spec=importlib.util.spec_from_file_location(
    "b66_cgi_final_handoff_smoke",
    Path(__file__).with_name("b66_cgi_final_handoff_smoke.py"))
assert spec is not None and spec.loader is not None
base=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=base
spec.loader.exec_module(base)

ORIGIN="quick-quote-kr.pages.dev"
GUIDED="/api/padiem/b66/guided-draft"
LOGIN="/api/padiem/auth/password/login"
LOGOUT="/api/padiem/auth/logout"

def routing_decision(method,url):
    p=urlparse(url)
    if p.scheme=="https" and p.netloc==ORIGIN and p.path==GUIDED:
        return "virtual" if method in ("GET","PUT","DELETE") else "abort"
    if method in ("GET","HEAD","OPTIONS"):
        return "continue"
    if (method=="POST" and p.scheme=="https" and p.netloc==ORIGIN
            and p.path in (LOGIN,LOGOUT)):
        return "continue"
    return "abort"

def run():
    username=os.getenv("B66_CGI_ALPHA_USERNAME","")
    password=os.getenv("B66_CGI_ALPHA_PASSWORD","")
    if not username or not password:
        print("B66_GUIDED_ISOLATED=FAIL_CREDENTIAL_MISSING",flush=True)
        return 2
    state={"slot":None,"gets":0,"puts":0,"deletes":0,"blocked":0}
    counters=base.Counters()
    logged=False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            context=browser.new_context(
                viewport={"width":1440,"height":1100},
                service_workers="block",
            )
            def guard(route):
                req=route.request
                decision=routing_decision(req.method,req.url)
                if decision=="abort":
                    state["blocked"]+=1
                    route.abort("blockedbyclient")
                    return
                if decision=="virtual":
                    if req.method=="GET":
                        state["gets"]+=1
                    elif req.method=="PUT":
                        try:
                            incoming=json.loads(req.post_data or "null")
                            if (not isinstance(incoming,dict) or
                                    incoming.get("schema")!="b66.guided-draft.v1" or
                                    incoming.get("mode")!="guided"):
                                state["blocked"]+=1
                                route.fulfill(status=422,content_type="application/json",
                                    body='{"ok":false}')
                                return
                            state["slot"]=incoming
                            state["puts"]+=1
                        except (ValueError,TypeError):
                            state["blocked"]+=1
                            route.fulfill(status=422,content_type="application/json",
                                body='{"ok":false}')
                            return
                    elif req.method=="DELETE":
                        state["slot"]=None
                        state["deletes"]+=1
                    route.fulfill(
                        status=200,content_type="application/json",
                        body=json.dumps({"ok":True,"state":state["slot"]},
                                        ensure_ascii=False),
                    )
                    return
                route.continue_()

            context.route("**/*",guard)
            page=context.new_page()
            browser_downloads=[]
            page.on("download",lambda download: browser_downloads.append(download))
            try:
                base._login(page,username,password)
                logged=True
                print("CGI_GUIDED_REAL_LOGIN_AND_SKILL=PASS",flush=True)
                # The CGI alpha server state is intentionally neither read nor
                # modified by GuidedAPI. Only the per-browser slot is used.
                base._guided(page,counters)
                if len(browser_downloads)!=1:
                    raise base.SmokeFailure("cgi_pdf_download_not_unique")
                from b66_cgi_original_visual_compare import measure
                root=Path(__file__).resolve().parents[2]
                original=root/"reference/b66-public-standard-templates/cgi/v1/source/original.pdf"
                template=root/"reference/b66-public-standard-templates/cgi/v1/sol61/template/template.json"
                manifest=root/"reference/b66-public-standard-templates/cgi/v1/PUBLIC_RELEASE_MANIFEST.json"
                report=measure(original,Path(browser_downloads[0].path()).read_bytes(),template,manifest)
                print("CGI_ORIGINAL_REFERENCE_HASH=PASS",flush=True)
                print("CGI_ORIGINAL_PAGE_A4=PASS",flush=True)
                print("CGI_BROWSER_PDF_TEXT_CHARACTERS="+str(report["browserTextCharacters"]),flush=True)
                print("CGI_ORIGINAL_PDF_TEXT_CHARACTERS="+str(report["originalTextCharacters"]),flush=True)
                print("CGI_ORIGINAL_UNMASKED_MAE="+str(report["unmaskedMAE"]),flush=True)
                print("CGI_ORIGINAL_UNMASKED_CHANGED16_PCT="+str(report["unmaskedChanged16Percent"]),flush=True)
                print("CGI_ORIGINAL_UNMASKED_CHANGED32_PCT="+str(report["unmaskedChanged32Percent"]),flush=True)
                print("CGI_ORIGINAL_VISUAL_CERTIFICATION=NOT_ASSERTED",flush=True)
                if counters.interpret_posts or counters.pdf_posts:
                    raise base.SmokeFailure("unexpected_model_or_server_pdf_call")
                # The completion clears only the in-memory virtual slot.
                for _ in range(30):
                    if state["puts"]>0 and state["deletes"]>0:
                        break
                    page.wait_for_timeout(100)
                if state["puts"]<1 or state["deletes"]<1 or state["slot"] is not None:
                    raise base.SmokeFailure("virtual_guided_save_cleanup_incomplete")
                if state["blocked"]!=0 or state["gets"]<1:
                    raise base.SmokeFailure("unexpected_outbound_or_no_guided_preflight")
                print("CGI_GUIDED_REAL_BROWSER_PDF=PASS",flush=True)
                print("CGI_GUIDED_VIRTUAL_GETS_PRESENT=PASS",flush=True)
                print("CGI_GUIDED_VIRTUAL_PUTS_PRESENT=PASS",flush=True)
                print("CGI_GUIDED_VIRTUAL_DELETE=PASS",flush=True)
                print("CGI_GUIDED_REAL_D1_MUTATIONS=0",flush=True)
                print("CGI_GUIDED_MODEL_POSTS=0",flush=True)
                base._logout_after_verified_pdf_handoff(page)
                logged=False
                print("B66_GUIDED_ISOLATED=PASS",flush=True)
                return 0
            finally:
                if logged:
                    try:
                        base._logout_after_verified_pdf_handoff(page)
                        print("CGI_GUIDED_FAILPATH_LOGOUT=PASS",flush=True)
                    except Exception:
                        print("CGI_GUIDED_FAILPATH_LOGOUT=UNVERIFIED",flush=True)
                context.close()
                browser.close()
    except base.SmokeFailure as exc:
        print("B66_GUIDED_ISOLATED=FAIL_"+str(exc),flush=True)
    except Exception as exc:
        print("B66_GUIDED_ISOLATED=FAIL_BROWSER_"+type(exc).__name__,flush=True)
    print("REAL_D1_WRITES=0; MODEL_POSTS=0; RETRY=0",flush=True)
    print("GUIDED_VIRTUAL_GETS="+str(state["gets"]),flush=True)
    print("GUIDED_VIRTUAL_PUTS="+str(state["puts"]),flush=True)
    print("GUIDED_VIRTUAL_DELETES="+str(state["deletes"]),flush=True)
    print("OUTBOUND_BLOCKS="+str(state["blocked"]),flush=True)
    print("PASSWORD_OUTPUT=0; COOKIE_OUTPUT=0; RAW_RESPONSE_OUTPUT=0",flush=True)
    return 1

if __name__=="__main__":
    raise SystemExit(run())
