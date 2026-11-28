# -*- coding: utf-8 -*-
"""#8778 third pass A-H: red-before-green browser behaviour contracts."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer

import pytest
from playwright.sync_api import sync_playwright

from test_8778_design_fix2 import (
    StaticHandler, STYLES, rgba, composite, contrast, ratio, set_style
)

ROOT = Path(__file__).resolve().parents[1]
PORT = 9462  # 4462 + 5000, outside the CGI reservation ranges
PHOTO = (ROOT / 'static/assets/sns-card.jpg').read_bytes()


@pytest.fixture(scope='module')
def url():
    server = ThreadingHTTPServer(('127.0.0.1', PORT), StaticHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{PORT}/apps/council/'
    server.shutdown()
    server.server_close()


def fake_files(kind, count):
    return [
        {
            'id': f'{kind}{i}', 'name': f'{kind}_지역주민_행사_{i:02d}_2026-11-28.txt',
            'media_type': 'text/plain', 'doc_kind': kind, 'content_chars': 170+i,
            'created_at': '2026-11-28T09:00:00Z', 'updated_at': '2026-11-28T10:00:00Z'
        }
        for i in range(count)
    ]


def open_case(browser, url, *, width=390, files=(), grade='pro', tiers=None,
              authenticated=True, methods=None, pairing=False, save_error=False):
    ctx = browser.new_context(
        viewport={'width': width, 'height': 900 if width > 500 else 844},
        locale='ko-KR', reduced_motion='reduce'
    )
    ctx.add_init_script("localStorage.removeItem('padiem-council-tool')")
    records = list(files)
    record_by_id = {f['id']: f for f in records}
    roster = {'version': 2, 'photos': [
        {'fileId': f['id'], 'name': f['name'], 'position': 'auto'}
        for f in records if f['media_type'].startswith('image/')
    ]}
    def mock(route):
        request = route.request
        path = request.url.split('?', 1)[0].split('://', 1)[-1].partition('/')[2]
        if path == 'api/chat/stream':
            body = 'data: '+json.dumps({'delta':'주민 여러분, 반갑습니다.'}, ensure_ascii=False)
            body += '\n\nevent: done\ndata: {"done":true}\n\n'
            route.fulfill(status=200,content_type='text/event-stream',body=body)
            return
        if path == 'api/auth/status':
            data = {'authenticated':authenticated,'member_grade':grade,
                    'methods':methods if methods is not None else {'password':True,'google':False},
                    'user':{'id':'test','name':'시험'}}
        elif path == 'api/account/model-selection':
            data = {'allowed_tiers':tiers if tiers is not None else ['free','plus','pro'],
                    'restorable_tier':(tiers or ['pro'])[-1]}
        elif path == 'api/projects':
            data = {'projects':[{'id':'test-council','name':'의원3종'}]}
        elif path == 'api/projects/test-council/files':
            if request.method == 'POST':
                if save_error:
                    route.fulfill(status=503,content_type='application/json',body='{"error":{"code":"store_unavailable"}}')
                    return
                data={'file':{'id':'saved-new','name':'new.txt','content_chars':19}}
            else:
                data={'files':records}
        elif path == 'api/pc/pairings':
            data={'links':[{'state':'active','id':'paired'}] if pairing else []}
        elif path.startswith('api/projects/test-council/files/') and path.endswith('/original'):
            route.fulfill(status=200,content_type='image/jpeg',body=PHOTO)
            return
        elif path.startswith('api/projects/test-council/files/'):
            file_id=path.split('/')[-1]
            file=record_by_id.get(file_id)
            if file and file['name']=='SNS 사진 구성.json':
                data={'file':{'id':file_id,'content':json.dumps(roster,ensure_ascii=False)}}
            else:
                text='회의 일시: 2026-11-28T10:00\n\n내용이 있는 회의 기록입니다.'
                data={'file':{'id':file_id,'content':text,'text':text}}
        else:
            data={'ok':True,'items':[]}
        route.fulfill(status=200,content_type='application/json',body=json.dumps(data,ensure_ascii=False))
    ctx.route('**/api/**',mock)
    page=ctx.new_page()
    page.set_default_timeout(4500)
    page.goto(url,wait_until='load')
    page.wait_for_timeout(350)
    return ctx,page


def open_tool(page, name):
    page.locator(f'#council-{name} .council-card-select').click()
    page.wait_for_timeout(300)


def test_A_saved_speech_and_sns_page_ten_with_metadata_and_reference_selection(url):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for kind, tool in (('speech','speech'),('sns','sns')):
            records=fake_files(kind,24)
            ctx,page=open_case(browser,url,width=1440,files=records)
            try:
                open_tool(page,tool)
                root=page.locator('#council'+tool.capitalize()+'Saved')
                items=root.locator('.council-saved-item')
                page.wait_for_timeout(250)
                assert items.count()==10,(kind,items.count())
                more=root.get_by_role('button',name='더 보기')
                assert more.is_visible()
                more.click()
                assert items.count()==20
                more.click()
                assert items.count()==24
                assert more.count()==0 or more.is_hidden()
                label=items.first.locator('.council-saved-open')
                assert '.txt' not in label.inner_text()
                assert '2026' in label.inner_text() and '170자' in label.inner_text()
                assert label.get_attribute('title')==records[0]['name']
                if kind=='speech':
                    ref=items.first.locator('.council-speech-use-ref')
                    assert ref.bounding_box()['height']>=44
                    assert float(ref.evaluate("e=>getComputedStyle(e).borderTopWidth").replace('px',''))>=1
                    ref.click()
                    page.wait_for_function("""() => document.querySelector('#councilSpeechSaved .council-saved-item').classList.contains('council-saved-selected')""", timeout=4000)
                    assert 'council-saved-selected' in items.first.get_attribute('class')
                    assert '✓' in items.first.locator('.council-saved-mark').inner_text()
            finally:ctx.close()
        browser.close()


def test_B_sns_selected_tabs_and_boundary_photo_controls(url):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        photos=[
            {'id':'im0','name':'현장1.jpg','media_type':'image/jpeg','doc_kind':'','content_chars':0},
            {'id':'im1','name':'현장2.jpg','media_type':'image/jpeg','doc_kind':'','content_chars':0},
            {'id':'roster','name':'SNS 사진 구성.json','media_type':'application/json','doc_kind':'','content_chars':100},
        ]
        for style in STYLES:
            ctx,page=open_case(browser,url,files=photos,width=1440)
            try:
                open_tool(page,'sns')
                set_style(page,style)
                for platform in ('blog','facebook','instagram'):
                    tab=page.locator(f'.council-sns-tab[data-platform="{platform}"]')
                    tab.click()
                    assert tab.get_attribute('aria-pressed')=='true',(style,platform)
                    css=tab.evaluate("""e=>{const s=getComputedStyle(e);
                       return {color:s.color,background:s.backgroundColor,under:getComputedStyle(e.parentElement).backgroundColor};}""")
                    assert contrast(css['color'],css['background'],css['under'])>=4.5,(style,platform,css)
                page.locator('.council-sns-tab[data-platform=blog]').click()
                photo_rows=page.locator('.council-photo-item')
                assert photo_rows.count()==2,(style,photo_rows.count())
                assert photo_rows.first.locator('button[data-move="-1"]').is_disabled()
                assert photo_rows.last.locator('button[data-move="1"]').is_disabled()
                assert float(photo_rows.first.locator('button[data-move="-1"]').evaluate('e=>getComputedStyle(e).opacity')) < 1
                assert photo_rows.first.locator('.council-photo-pos-select').get_attribute('aria-label')=='삽입 위치'
                assert '삽입 위치' not in photo_rows.first.inner_text()
            finally:ctx.close()
        browser.close()


def test_C_activity_book_selection_period_grid_accent_and_reorder_feedback(url):
    records=fake_files('meeting',4)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for width in (390,1440):
            ctx,page=open_case(browser,url,width=width,files=records)
            try:
                open_tool(page,'meeting')
                quick=page.locator('.council-book-quick')
                assert quick.count()==4
                coords=quick.evaluate_all("""items=>items.map(e=>{let r=e.getBoundingClientRect();
                   let s=getComputedStyle(e);return {x:r.x,y:r.y,height:r.height,border:s.borderTopWidth};})""")
                assert all(x['height']>=44 and float(x['border'].replace('px',''))>=1 for x in coords),coords
                if width==390:
                    assert abs(coords[0]['y']-coords[1]['y'])<2,coords
                    assert coords[2]['y']>coords[0]['y']+40,coords
                    assert abs(coords[2]['y']-coords[3]['y'])<2,coords
                    select=page.locator('#councilBookSelectPeriod').bounding_box()
                    assert select['width']>quick.first.bounding_box()['width']*1.7
                status=page.locator('#councilBookSelectedCount')
                generate=page.locator('#councilBookGenerate')
                assert status.inner_text()=='0개 선택됨'
                assert generate.is_disabled()
                assert page.get_by_text('기록을 1개 이상 골라 주세요.').is_visible()
                cb=page.locator('.council-book-check')
                cb.first.check()
                assert status.inner_text()=='1개 선택됨'
                assert generate.is_enabled()
                css=cb.first.evaluate('e=>({accent:getComputedStyle(e).accentColor,token:getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()})')
                assert css['accent'] and css['accent']!='auto'
                move=page.locator('.council-archive-item .council-record-move')
                move.nth(1).click()
                assert page.locator('#councilBookMoveStatus').get_attribute('aria-live')=='polite'
                assert '번째로 옮겼습니다' in page.locator('#councilBookMoveStatus').inner_text()
                moved=page.locator('.council-archive-item').nth(1)
                assert 'council-record-just-moved' in moved.get_attribute('class')
            finally:ctx.close()
        browser.close()


def test_D_meeting_inputs_are_grouped_in_a_fieldset(url):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx,page=open_case(browser,url)
        try:
            open_tool(page,'meeting')
            form=page.locator('#councilMeetingForm')
            group=form.locator('fieldset.council-fieldset').filter(has=page.locator('legend:text-is("회의 정보")'))
            assert group.count()==1
            for name in ('title','when','attendees','content'):
                assert group.locator(f'[name="{name}"]').count()==1
        finally:
            ctx.close();browser.close()


def test_E_pc_format_anchored_and_save_failure_near_actions_with_retry(url):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx,page=open_case(browser,url,width=390,pairing=True,save_error=True)
        try:
            open_tool(page,'speech')
            page.locator('#councilSpeechForm [name=event]').fill('주민 행사')
            page.locator('#councilSpeechGenerate').click()
            page.locator('#councilSpeechResult:not([hidden])').wait_for()
            pc=page.locator('#councilSpeechPcSave')
            pc.click()
            chooser=page.locator('.council-pc-format-choice')
            chooser.wait_for(state='visible',timeout=4000)
            assert chooser.is_visible()
            assert chooser.evaluate("e=>e.parentElement.classList.contains('council-actions')")
            labels=[b.inner_text() for b in chooser.locator('button').all()]
            assert labels==['한글','워드','텍스트','취소'],labels
            assert all(x=='1px' for x in chooser.locator('button').evaluate_all(
                "buttons=>buttons.map(b=>getComputedStyle(b).borderTopWidth)"))
            chooser.get_by_role('button',name='취소').click()
            assert chooser.count()==0
            page.locator('#councilSpeechSave').click()
            failure=page.locator('#councilSpeechResult .council-save-failure')
            failure.wait_for(state='visible',timeout=4000)
            assert failure.is_visible()
            assert failure.locator('button').inner_text()=='다시 시도'
            assert failure.get_attribute('data-tone')=='error'
            assert failure.evaluate('e=>e.previousElementSibling.classList.contains("council-actions")')
        finally:ctx.close();browser.close()


def test_F_home_cards_hover_padding_and_2560_alignment(url):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for width in (390,2560):
            ctx,page=open_case(browser,url,width=width,authenticated=False)
            try:
                for style in STYLES:
                    set_style(page,style)
                    card=page.locator('#council-speech')
                    before=card.evaluate("""e=>{
                      const p=e.querySelector('p'),r=e.getBoundingClientRect(),q=p.getBoundingClientRect();
                      const s=getComputedStyle(e);
                      return {left:q.left-r.left,right:r.right-q.right,
                              border:s.borderTopColor,shadow:s.boxShadow};}""")
                    assert before['left']>=24 and before['right']>=24,(width,style,before)
                    card.hover()
                    after=card.evaluate("""e=>{const s=getComputedStyle(e);
                       return {border:s.borderTopColor,shadow:s.boxShadow};}""")
                    assert before['border']!=after['border'] or before['shadow']!=after['shadow'],(width,style,before,after)
                    page.mouse.move(1,1)
                if width==2560:
                    m=page.evaluate("""() => {
                      const left=s=>document.querySelector(s).getBoundingClientRect().left;
                      return {brand:left('.council-brand'),hero:left('.council-hero-copy .council-eyebrow'),
                       cards:left('.council-works-head'),strip:left('.council-strip ul')};
                    }""")
                    assert max(m.values())-min(m.values())<=24,m
            finally:ctx.close()
        browser.close()


def test_G_one_tier_and_one_country_are_badges_not_choice_controls(url):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx,page=open_case(browser,url,tiers=['pro'],grade='pro')
        try:
            assert page.locator('#councilTierBadge').is_visible()
            assert page.locator('#councilTierBadge').inner_text()=='Padiem Pro'
            assert page.locator('#councilTier').is_hidden()
            set_style(page,'dark')
            page.locator('#councilThemeTrigger').click()
            assert page.locator('#councilCountryBadge').is_visible()
            assert page.locator('#councilCountryGroup button[data-country=kr]').is_hidden()
            assert page.locator('#councilCountryBadge').inner_text()=='한국'
        finally:ctx.close();browser.close()


def test_H_signup_contrast_and_google_flag_from_server_methods(url):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for google in (False,True):
            ctx,page=open_case(browser,url,authenticated=False,methods={'password':True,'google':google})
            try:
                page.locator('#councilAuthAction').click()
                assert page.locator('#councilGoogleRow').is_visible()==google
                for style in STYLES:
                    set_style(page,style)
                    login=page.locator('#councilSignupLink').evaluate("""e=>{
                      const s=getComputedStyle(e),parent=getComputedStyle(e.parentElement);
                      return {ink:s.color,background:parent.backgroundColor,
                        surface:getComputedStyle(e.closest('#councilAuthPanel')).backgroundColor};
                    }""")
                    assert contrast(login['ink'],login['background'],login['surface'])>=4.5, (google,style,login)
            finally:ctx.close()
        browser.close()


def test_E_missing_metadata_is_not_mislabeled_zero_characters(url):
    """#8778 E-6: a mock without valid counts must not be presented as (0자)."""
    files=fake_files('speech',1)
    files[0]['content_chars']=0  # the old design QA mock omitted the real API count
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx,page=open_case(browser,url,files=files)
        try:
            open_tool(page,'speech')
            item=page.locator('#councilSpeechSaved .council-saved-open').first
            assert item.is_visible()
            assert '0자' not in item.inner_text()
            assert item.get_attribute('title')==files[0]['name']
        finally:ctx.close();browser.close()
