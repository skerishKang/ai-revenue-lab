"""Protected CGI freeform one model call / real PDF; existing Guided D1 unchanged."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

spec=importlib.util.spec_from_file_location("b66_cgi_final_handoff_smoke",Path(__file__).with_name("b66_cgi_final_handoff_smoke.py"))
assert spec and spec.loader
base=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=base
spec.loader.exec_module(base)
POSTS={"/api/padiem/auth/password/login","/api/padiem/auth/logout",base.INTERPRET_PATH}

def allowed(method,url):
    p=urlparse(url)
    if method in ("GET","HEAD","OPTIONS"):
        return True
    return method=="POST" and p.scheme=="https" and p.netloc=="quick-quote-kr.pages.dev" and p.path in POSTS

def run():
    user=os.getenv("B66_CGI_ALPHA_USERNAME","")
    password=os.getenv("B66_CGI_ALPHA_PASSWORD","")
    model=os.getenv("B66_CGI_SELECTED_MODEL_ID","")
    flow=os.getenv("B66_CGI_FLOW_MODE","complete")
    if flow not in ("complete","partial_followup"):
        print("B66_CGI_FREEFORM=FAIL_INVALID_FLOW")
        return 2
    allowed_posts=1 if flow=="complete" else 2
    if not user or not password or not base._B66_EXACT_MODEL_RE.fullmatch(model) or model=="b14/auto":
        print("B66_CGI_FREEFORM=FAIL_PREFLIGHT")
        return 2
    counts={"interpret":0,"blocked":0,"pdf":0}
    live_counters=base.Counters()
    logged_in=False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            context=browser.new_context(viewport={"width":1440,"height":1100},service_workers="block")
            def guard(route):
                req=route.request
                path=urlparse(req.url).path
                if not allowed(req.method,req.url):
                    counts["blocked"]+=1
                    route.abort("blockedbyclient")
                    return
                if req.method=="POST" and path==base.INTERPRET_PATH:
                    if counts["interpret"]>=allowed_posts:
                        counts["blocked"]+=1
                        route.abort("blockedbyclient")
                        return
                    counts["interpret"]+=1
                    live_counters.interpret_posts+=1
                if req.method=="POST" and path==base.PDF_PATH:
                    counts["pdf"]+=1
                    live_counters.pdf_posts+=1
                route.continue_()
            context.route("**/*",guard)
            page=context.new_page()
            try:
                base._login(page,user,password)
                logged_in=True
                print("CGI_LOGIN_AND_SAVED_SKILL=PASS",flush=True)
                # The D1 Guided row is never written, cleared, or modified.
                if flow=="partial_followup":
                    base._partial_followup(page,live_counters,model)
                else:
                    base._complete_free_form(page,live_counters,model)
                if counts["interpret"]!=allowed_posts or counts["pdf"] or counts["blocked"]:
                    raise base.SmokeFailure("bounded_network_contract")
                print("CGI_"+flow.upper()+"_PDF_DOWNLOAD=PASS",flush=True)
                print("GUIDED_D1_MUTATIONS=0",flush=True)
                base._logout_after_verified_pdf_handoff(page)
                logged_in=False
                print("CGI_MODEL_INTERPRET_POSTS="+str(counts["interpret"]),flush=True)
                print("B66_CGI_FREEFORM=PASS",flush=True)
                return 0
            finally:
                if logged_in:
                    try:
                        base._logout_after_verified_pdf_handoff(page)
                        print("FAILPATH_LOGOUT=PASS",flush=True)
                    except Exception:
                        print("FAILPATH_LOGOUT=UNVERIFIED",flush=True)
                context.close()
                browser.close()
    except base.SmokeFailure as exc:
        print("B66_CGI_FREEFORM=FAIL_"+str(exc),flush=True)
    except Exception as exc:
        print("B66_CGI_FREEFORM=FAIL_BROWSER_"+type(exc).__name__,flush=True)
    print("INTERPRET_POSTS="+str(counts["interpret"]),flush=True)
    print("BLOCKED_OUTBOUND="+str(counts["blocked"]),flush=True)
    print("PDF_SERVER_POSTS="+str(counts["pdf"]),flush=True)
    print("MODEL_RETRY=0; MODEL_FALLBACK=0",flush=True)
    print("PASSWORD_OUTPUT=0; COOKIE_OUTPUT=0; RAW_RESPONSE_OUTPUT=0",flush=True)
    return 1

if __name__=="__main__":
    raise SystemExit(run())
