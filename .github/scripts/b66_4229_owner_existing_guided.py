"""Owner-authorized #4229: assess/finish existing CGI alpha Guided test draft.

Production credentials are read from GitHub Actions protected environment, never printed.
NO customer quote or D1 row may be reset. Finish mode only accepts a preexisting
blank first-question draft with approved server Skill, and lets the product issue
its own completion DELETE after the PDF is verified.
"""
import argparse
import os
import sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

import b66_cgi_final_handoff_smoke as base

URL = "https://quick-quote-kr.pages.dev/"
GUIDED_PATH = "/api/padiem/b66/guided-draft"
SKILL_SCHEMA = "b66.guided-draft.v1"
ALLOWED_MUTATING = {
    ("POST", "/api/padiem/auth/password/login"),
    ("POST", "/api/padiem/auth/logout"),
    ("PUT", GUIDED_PATH),
    ("DELETE", GUIDED_PATH),
}


def examine(page):
    """Return bounded classifications, never source quote content or identity."""
    data = page.evaluate("""async () => {
        const r=await fetch('/api/padiem/b66/guided-draft', {cache:'no-store'});
        const j=await r.json().catch(()=>null);
        const s=j?.state;
        const draft=s?.draft;
        const br=window.B66QuoteRuntimeBridge;
        return {
          http:r.status,
          valid:j?.ok===true,
          hasState:!!s,
          schemaOk:s?.schema==='b66.guided-draft.v1' && s?.mode==='guided',
          step:s?.step || 'absent',
          itemCount:Array.isArray(draft?.items)?draft.items.length:-1,
          hasRecipient:Boolean(draft?.recipient?.company),
          hasPerson:Boolean(draft?.recipient?.person),
          hasMemo:Boolean(draft?.memo),
          hasPrice:Array.isArray(draft?.items)&&draft.items.some(i=>i.unitPrice!=null),
          approvedSkill:!!s?.savedSkillId &&
            s.savedSkillId===br?.assignedSavedSkillId?.(),
        };
    }""")
    if not isinstance(data, dict) or data.get("http") != 200 or data.get("valid") is not True:
        raise base.SmokeFailure("state_read_unavailable")
    return data


def guard(route):
    req=route.request
    parsed=urlparse(req.url)
    if parsed.scheme!="https" or parsed.hostname not in ("quick-quote-kr.pages.dev",):
        route.abort("blockedbyclient")
        return
    if req.method in ("GET", "HEAD"):
        route.continue_()
        return
    if (req.method, parsed.path) in ALLOWED_MUTATING:
        route.continue_()
        return
    route.abort("blockedbyclient")


def run(mode):
    username=os.environ.get("B66_CGI_ALPHA_USERNAME", "")
    password=os.environ.get("B66_CGI_ALPHA_PASSWORD", "")
    if not username or not password:
        raise base.SmokeFailure("credential_unavailable")
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(accept_downloads=True, viewport={"width":1440,"height":1000}, service_workers="block")
        context.route("**/*",guard)
        page=context.new_page()
        authorized=False
        try:
            base._login(page,username,password)
            authorized=True
            status=examine(page)
            # Only allowed enum and booleans are reported, NEVER actual state / draft / identity.
            if status["step"] not in ("recipientCompany","recipientPerson","itemName","qty","price",
                  "moreItems","tax","memo","senderChoice","senderCompany","summary","absent"):
                raise base.SmokeFailure("unrecognized_saved_step")
            for key in ("hasState","schemaOk","step","itemCount","hasRecipient","hasPerson","hasMemo","hasPrice","approvedSkill"):
                print("EXISTING_"+key.upper()+"="+str(status[key]),flush=True)
            if mode=="audit":
                print("B66_4229_OWNER_OLD_DRAFT_AUDIT=PASS",flush=True)
                return 0
            # Existing blank original from failed canary may be completed; never reset
            # an arbitrary existing quote or overwrite a nonempty customer's facts.
            if not (
                status["hasState"] and status["schemaOk"] and
                status["step"]=="recipientCompany" and status["itemCount"]==0 and
                not status["hasRecipient"] and not status["hasPerson"] and
                not status["hasMemo"] and not status["hasPrice"] and status["approvedSkill"]
            ):
                raise base.SmokeFailure("existing_draft_not_blank_test_start")
            print("B66_4229_EXACT_BLANK_TEST_PRECONDITION=PASS",flush=True)
            page.locator("#resumeDraftStarter").click(timeout=12000)
            base._require_guided_input_ready(page)
            before=examine(page)
            if before["step"]!="recipientCompany" or before["itemCount"]!=0:
                raise base.SmokeFailure("post_resume_state_changed")
            base._send(page,"가이드테스트건설")
            base._click_chip_index(page,index=0,expected_count=1,stage="recipient_person_none")
            base._send(page,"배관")
            base._click_chip_index(page,index=1,expected_count=4,stage="quantity_two")
            base._send(page,"10000")
            base._click_chip_index(page,index=1,expected_count=2,stage="items_done")
            base._click_chip_index(page,index=0,expected_count=4,stage="tax_exclusive")
            base._click_chip_index(page,index=0,expected_count=1,stage="memo_none")
            base._click_chip_index(page,index=0,expected_count=1,stage="sender_current")
            base._click_chip_index(page,index=0,expected_count=3,stage="finish")
            base._assert_quote(page,recipient="가이드테스트건설",item="배관",qty=2,unit_price=10000,grand=22000)
            print("B66_4229_OWNER_EXISTING_GUIDED_QUOTECORE=PASS",flush=True)
            base._open_result_and_download(page,base.Counters())
            print("B66_4229_OWNER_EXISTING_PDF_DOWNLOAD=PASS",flush=True)
            # The normal product must enqueue DELETE on finish. Wait for D1
            # to become empty rather than manually deleting a possibly changed slot.
            page.wait_for_function("""async () => {
                const r=await fetch('/api/padiem/b66/guided-draft',{cache:'no-store'});
                const j=await r.json().catch(()=>null);
                return r.status===200 && j?.ok===true && j.state===null;
            }""",timeout=20000)
            print("B66_4229_OWNER_EXISTING_D1_EMPTY=PASS",flush=True)
            print("B66_4229_OWNER_EXISTING_GUIDED_COMPLETE=PASS",flush=True)
            return 0
        finally:
            if authorized:
                try:base._logout_after_verified_pdf_handoff(page)
                except Exception:print("B66_4229_LOGOUT=UNVERIFIED",flush=True)
            context.close()
            browser.close()


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode", choices=["audit","finish"],required=True)
    args=p.parse_args()
    try:return run(args.mode)
    except Exception as exc:
        code=str(exc) if isinstance(exc,base.SmokeFailure) else type(exc).__name__
        print("B66_4229_OWNED_PROD="+args.mode.upper()+"_FAIL_"+code,flush=True)
        print("RAW_PII_OR_SECRETS_IN_OUTPUT=NO",flush=True)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
