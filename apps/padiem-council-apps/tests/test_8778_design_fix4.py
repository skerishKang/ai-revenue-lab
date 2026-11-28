# -*- coding: utf-8 -*-
"""#8778 final recheck: red-before-green tests for CTO #8784 #8788 #8795.

Static 9463 only; no operational account, secrets, or production requests.
"""
from __future__ import annotations
import json
import threading
from http.server import ThreadingHTTPServer

import pytest
from playwright.sync_api import sync_playwright
from test_8778_design_fix2 import StaticHandler,STYLES,rgba,composite,ratio
from test_8778_design_fix3 import fake_files,open_case,open_tool,set_style

PORT=9463


@pytest.fixture(scope="module")
def url():
    s=ThreadingHTTPServer(("127.0.0.1",PORT),StaticHandler)
    threading.Thread(target=s.serve_forever,daemon=True).start()
    yield f"http://127.0.0.1:{PORT}/apps/council/"
    s.shutdown()
    s.server_close()


@pytest.mark.parametrize("tool,kind",(("speech","speech"),("sns","sns")))
def test_saved_lists_page_ten_even_with_25_records_after_style_switch(url,tool,kind):
    """#8788 CTO: 25 entries never render all at initial load; More adds exactly 10."""
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for width,style in ((390,"light"),(1440,"dark"),(390,"minimal"),
                            (1440,"light"),(390,"classic"),(1440,"modern")):
            ctx,page=open_case(browser,url,width=width,files=fake_files(kind,25))
            try:
                open_tool(page,tool)
                set_style(page,style)
                listing=page.locator(f"#council{tool.capitalize()}Saved")
                items=listing.locator(".council-saved-item")
                page.wait_for_function("""(id)=>document.querySelector('#'+id+' .council-saved-item')!==null""",
                                       arg=f"council{tool.capitalize()}Saved")
                assert items.count()==10,(width,style,tool,items.count())
                more=listing.get_by_role("button",name="더 보기")
                assert more.is_visible()
                more.click()
                assert items.count()==20,(width,style,tool,items.count())
                more.click()
                assert items.count()==25,(width,style,tool,items.count())
                assert more.count()==0
            finally:ctx.close()
        browser.close()


@pytest.mark.parametrize("tool,kind",(("speech","speech"),("sns","sns")))
def test_filename_date_is_not_repeated_but_title_is_complete(url,tool,kind):
    """#8788 CTO: display removes trailing duplicate _YYYY-MM-DD, not the title attr."""
    docs=fake_files(kind,2)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx,page=open_case(browser,url,width=1440,files=docs)
        try:
            open_tool(page,tool)
            q=page.locator(f"#council{tool.capitalize()}Saved .council-saved-open").first
            q.wait_for(state="visible")
            visible=q.inner_text()
            actual=q.get_attribute("title")
            assert actual==docs[0]['name'],(visible,actual)
            # The date appears in the dedicated metadata column only.
            assert visible.count("2026-11-28")==1,(visible,actual)
            assert "170자" in visible
            assert ".txt" not in visible
        finally:ctx.close();browser.close()


def test_login_google_and_close_borders_five_styles(url):
    """#8784 CTO D6: both modal controls have 3:1 non-text border contrast."""
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for style in STYLES:
            ctx,page=open_case(browser,url,width=1440,authenticated=False,
                               methods={"password":True,"google":True})
            try:
                set_style(page,style)
                page.locator("#councilAuthAction").click()
                panel=page.locator("#councilAuthPanel")
                panel.wait_for(state="visible")
                assert page.locator("#councilGoogleRow").is_visible()
                measurements=panel.evaluate("""p=>{
                  const sheet=getComputedStyle(p);
                  return {surface:sheet.backgroundColor,body:getComputedStyle(document.body).backgroundColor,
                    actions:['#councilGoogleLogin','#councilAuthClose'].map(s=>{
                      const e=p.querySelector(s),cs=getComputedStyle(e),b=e.getBoundingClientRect();
                      return {selector:s,foreground:cs.color,background:cs.backgroundColor,
                        border:cs.borderTopColor,borderWidth:cs.borderTopWidth,
                        width:b.width,height:b.height};
                    })};
                }""")
                bg=composite(rgba(measurements['surface']),
                             composite(rgba(measurements['body']),[1,1,1]))
                for ctl in measurements['actions']:
                    border_under=composite(rgba(ctl['background']),bg)
                    painted=composite(rgba(ctl['border']),border_under)
                    assert ctl['height']>=44 and float(ctl['borderWidth'].replace('px',''))>=1,(style,ctl)
                    assert ratio(painted,bg)>=3.0,(style,ctl['selector'],round(ratio(painted,bg),3),measurements)
            finally:ctx.close()
        browser.close()


def test_invalid_login_keeps_visible_modal_and_inline_error_at_390_dark(url):
    """#8784 CTO: mock 401 must leave the dialog open and show its real failure text."""
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx,page=open_case(browser,url,width=390,authenticated=False)
        try:
            set_style(page,"dark")
            calls=[]
            def fail(route):
                calls.append(route.request.method)
                route.fulfill(status=401,content_type='application/json',body=json.dumps(
                    {'error':{'message':'이메일 또는 비밀번호가 올바르지 않습니다.'}},ensure_ascii=False))
            ctx.route("**/api/auth/password/login",fail)
            page.locator("#councilAuthAction").click()
            panel=page.locator("#councilAuthPanel")
            panel.wait_for(state="visible")
            panel.locator('[name=identifier]').fill("test@example.invalid")
            panel.locator('[name=password]').fill("invalid-local-simulation")
            panel.locator('button[type=submit]').click()
            page.wait_for_function("""()=>{
                const p=document.querySelector('#councilAuthPanel');
                const e=document.querySelector('#councilAuthStatus');
                return p && !p.hidden && e && !e.hidden &&
                  e.textContent.trim()==='이메일 또는 비밀번호가 올바르지 않습니다.';
            }""",timeout=6000)
            assert calls==["POST"],calls
            assert panel.is_visible()
            assert page.locator("#councilAuthStatus").is_visible()
            rect=panel.bounding_box()
            error=page.locator("#councilAuthStatus").bounding_box()
            assert rect and error and rect['height']>180,(rect,error)
            assert rect['y']>=0 and rect['y']+rect['height']<=844,(rect,error)
            assert error['y']>=rect['y'] and error['y']<=rect['y']+rect['height'],(rect,error)
        finally:ctx.close();browser.close()


@pytest.mark.parametrize("kind",("save","generation"))
def test_error_icon_stays_in_first_text_row_and_matches_generation_failure(url,kind):
    """#8795 CTO D1: ! inline to left of error at 390 and 1440."""
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for width,style in ((390,"light"),(1440,"dark")):
            ctx,page=open_case(browser,url,width=width,save_error=kind=="save")
            try:
                if kind=="generation":
                    ctx.route("**/api/chat/stream",lambda route:route.fulfill(
                        status=503,content_type='application/json',body='{"error":{"code":"unavailable"}}'))
                set_style(page,style)
                open_tool(page,"speech")
                page.locator('#councilSpeechForm [name=event]').fill('시험용 행사')
                page.locator("#councilSpeechGenerate").click()
                if kind=="save":
                    page.locator("#councilSpeechResult:not([hidden])").wait_for()
                    page.wait_for_function("""()=>{
                        const b=document.querySelector('#councilSpeechSave');
                        return b && !b.disabled;
                    }""",timeout=6000)
                    page.locator("#councilSpeechSave").click()
                    box=page.locator("#councilSpeechResult .council-save-failure")
                else:
                    box=page.locator("#councilSpeechNotice[data-tone=error]")
                box.wait_for(state="visible",timeout=7000)
                values=box.evaluate("""el=>{
                    const s=getComputedStyle(el);
                    const pseudo=getComputedStyle(el,'::before');
                    const first=el.firstChild;
                    let rect=null;
                    if(first&&first.nodeType===3){
                        const r=document.createRange();r.selectNodeContents(first);
                        const b=r.getClientRects()[0];
                        if(b)rect={x:b.x,y:b.y,height:b.height,right:b.right};
                    }
                    return {display:s.display,columns:s.gridTemplateColumns,
                        align:s.alignItems,wrap:s.flexWrap,
                        pseudo:pseudo.content,text:rect,
                        box:el.getBoundingClientRect().toJSON(),
                        childCount:el.childNodes.length};
                }""")
                assert "!" in values['pseudo'],values
                assert values['display']=="grid",(width,style,kind,values)
                assert len(values['columns'].split())==2,(width,style,kind,values)
                assert values['align']=="center",(width,style,kind,values)
                assert values['text'] and values['text']['x']>values['box']['x']+14,(width,kind,values)
            finally:ctx.close()
        browser.close()


@pytest.mark.parametrize("tool,kind",(("speech","speech"),("sns","sns")))
def test_saved_more_button_border_contrast_five_styles(url,tool,kind):
    """#8976 CTO: the More control has >=3:1 outline against its list surface."""
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            for style in STYLES:
                ctx,page=open_case(browser,url,width=1440,files=fake_files(kind,25))
                try:
                    open_tool(page,tool)
                    set_style(page,style)
                    container=page.locator(f"#council{tool.capitalize()}Saved")
                    button=container.get_by_role("button",name="더 보기")
                    button.wait_for(state="visible")
                    assert container.locator(".council-saved-item").count()==10
                    measured=button.evaluate("""b=>{
                      const c=getComputedStyle(b),p=getComputedStyle(b.closest('.council-saved-list'));
                      const card=getComputedStyle(b.closest('.council-card'));
                      return {border:c.borderTopColor,bg:c.backgroundColor,card:card.backgroundColor,
                        list:p.backgroundColor,width:c.borderTopWidth,height:b.getBoundingClientRect().height};
                    }""")
                    paper=composite(rgba(measured['list']),composite(rgba(measured['card']),[1,1,1]))
                    border=composite(rgba(measured['border']),composite(rgba(measured['bg']),paper))
                    actual=ratio(border,paper)
                    assert measured['height']>=44 and float(measured['width'].replace("px",""))>=1,(
                        tool,style,measured)
                    assert actual>=3.0,(tool,style,round(actual,3),measured)
                finally:ctx.close()
        finally:browser.close()


def test_all_nonprimary_outline_buttons_five_styles(url):
    """#8976 CTO: inspect dark/other themes across home, tools, auth, style,
    stored history, book and result screens. Exclude only filled primary
    controls, menu pills and intentionally disabled/iconless controls.
    Collect all weak outlines before failing to supply one actionable inventory.
    """
    cases={
        # #8976: filled card CTAs are primary controls and deliberately excluded.
        "home":["#councilAuthAction","#councilThemeTrigger"],
        "login":["#councilGoogleLogin","#councilAuthClose"],
        "style":["#councilStyleGroup button:not([aria-checked=true])"],
        "speech":["#councilSpeechSaved .council-saved-more",
                  "#councilSpeechSaved .council-speech-use-ref",
                  "#councilSpeechSaved .council-saved-open",
                  "#councilSpeechResult .council-result-action:not(.council-primary)"],
        "sns":[".council-sns-tab:not([aria-pressed=true])",
               "#councilSnsPhotoAdd"],
        "book":[".council-book-quick","#councilBookSelectPeriod",
                ".council-archive-item .council-record-move"],
    }
    # At each candidate use the nearest ancestor's visibly painted surface.
    js="""(selectors)=>{
      const rgba=c=>{const m=c.match(/rgba?\\(([^)]+)\\)/);return m?m[1].split(/[ ,/]+/).map(Number):[];};
      function a(c){const n=rgba(c);return n.length>=4?n[3]:n.length>=3?1:0;}
      function parentBg(el){
        let p=el.parentElement;
        while(p){let color=getComputedStyle(p).backgroundColor;
          if(a(color)>.02)return color;
          p=p.parentElement;
        }return 'rgb(255,255,255)';
      }
      const result=[];
      for(const selector of selectors) {
        for(const el of document.querySelectorAll(selector)){
          const rect=el.getBoundingClientRect(),s=getComputedStyle(el);
          if(rect.width<1||rect.height<1||s.visibility==='hidden'||s.display==='none'
              ||el.disabled||el.closest('[hidden]'))continue;
          result.push({selector,id:el.id,kind:String(el.className||''),
            label:(el.innerText||el.textContent||'').trim().replace(/\\s+/g,' ').slice(0,35),
            border:s.borderTopColor,bg:s.backgroundColor,surface:parentBg(el),
            stroke:s.borderTopWidth,height:rect.height});
        }
      }return result;
    }"""
    failed=[]
    inspected=0
    unique=set()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            for style in STYLES:
                # Anonymous home, login dialog and style chooser.
                ctx,page=open_case(browser,url,width=1440,authenticated=False,
                                   methods={"password":True,"google":True})
                try:
                    set_style(page,style)
                    groups=[("home",cases["home"])]
                    groups[0][1] # keep stage keys explicit
                    for stage,selectors in groups:
                        records=page.evaluate(js,selectors)
                        for x in records:
                            inspected+=1
                            surface=composite(rgba(x['surface']),[1,1,1])
                            border=composite(rgba(x['border']),composite(rgba(x['bg']),surface))
                            value=ratio(border,surface)
                            unique.add((stage,x['selector']))
                            if value<3.0 or float(x['stroke'].replace('px',''))<1:
                                failed.append((style,stage,x['selector'],x['label'],round(value,2)))
                    page.locator("#councilAuthAction").click()
                    for x in page.evaluate(js,cases['login']):
                        inspected+=1;unique.add(("login",x['selector']))
                        surface=composite(rgba(x['surface']),[1,1,1])
                        border=composite(rgba(x['border']),composite(rgba(x['bg']),surface))
                        v=ratio(border,surface)
                        if v<3 or float(x['stroke'].replace('px',''))<1:failed.append((style,"login",x['selector'],x['label'],round(v,2)))
                    page.locator("#councilAuthClose").click()
                    page.locator("#councilThemeTrigger").click()
                    for x in page.evaluate(js,cases["style"]):
                        inspected+=1;unique.add(("style",x['selector']))
                        surface=composite(rgba(x['surface']),[1,1,1])
                        border=composite(rgba(x['border']),composite(rgba(x['bg']),surface))
                        v=ratio(border,surface)
                        if v<3 or float(x['stroke'].replace('px',''))<1:failed.append((style,"style",x['selector'],x['label'],round(v,2)))
                finally:ctx.close()

                for kind in ("speech","sns","book"):
                    docs=(fake_files("speech",25) if kind=="speech" else
                          fake_files("meeting",16) if kind=="book" else [])
                    ctx,page=open_case(browser,url,width=1440,files=docs,pairing=True)
                    try:
                        set_style(page,style)
                        open_tool(page,"meeting" if kind=="book" else kind)
                        if kind=="speech":
                            page.locator('#councilSpeechSaved .council-saved-more').wait_for(state="visible")
                            page.locator('#councilSpeechResult').evaluate("(e)=>{e.hidden=false}")
                        if kind=="book":
                            page.locator('.council-archive-item').first.wait_for(state="visible")
                        for x in page.evaluate(js,cases[kind]):
                            inspected+=1;unique.add((kind,x['selector']))
                            surface=composite(rgba(x['surface']),[1,1,1])
                            border=composite(rgba(x['border']),composite(rgba(x['bg']),surface))
                            v=ratio(border,surface)
                            if v<3 or float(x['stroke'].replace('px',''))<1:
                                failed.append((style,kind,x['selector'],x['label'],round(v,2)))
                    finally:ctx.close()
        finally:browser.close()
    print("SECONDARY_BUTTON_AUDIT inspected=",inspected,"unique_sectors=",len(unique),
          "failures=",len(failed))
    print("SECONDARY_BUTTON_WEAK",sorted(set(failed)))
    assert inspected>=80,(inspected,unique)
    assert not failed,sorted(set(failed))
