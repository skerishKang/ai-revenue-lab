"""B66 shell: independent reusable-form dialog and quote conversation fallback."""
import http.server
import socketserver
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw):
        super().__init__(*a,directory=str(ROOT),**kw)
    def log_message(self,*a): pass

class Server(socketserver.TCPServer):
    allow_reuse_address = True

def main():
    with Server(("127.0.0.1",0),Handler) as server:
        threading.Thread(target=server.serve_forever,daemon=True).start()
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            try:
                for width in (390,873,1280):
                    page=browser.new_page(viewport={"width":width,"height":850})
                    errors=[]
                    page.on("pageerror",lambda error:errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html",wait_until="domcontentloaded")
                    page.wait_for_selector("#shellManualQuote", state="attached")
                    if not page.locator("#shellManualQuote").is_visible():
                        page.locator("#shellRailToggle").click()
                    assert not page.locator("#directView").is_visible()
                    page.locator("#shellManualQuote").click()
                    dlg=page.locator("#b66SkillStartDialog")
                    assert dlg.evaluate("(el) => el.open")
                    assert not page.locator("#directView").is_visible(), "Modal must not switch to line-item editor"
                    assert page.locator("#b66SkillStartFromFile").is_visible()
                    assert page.locator("#b66SkillStartFromBlank").is_visible()
                    page.locator("#b66SkillStartFromFile").click()
                    assert page.locator("#skillWizardPanel").is_visible()
                    assert page.get_by_text("1. 견적서 선택",exact=True).count()
                    page.locator("#skillWizardCancel").click()
                    page.wait_for_function("!document.querySelector('#b66SkillStartDialog').open")
                    if not page.locator("#shellManualQuote").is_visible():
                        page.locator("#shellRailToggle").click()
                    page.locator("#shellManualQuote").click()
                    page.locator("#b66SkillStartFromBlank").click()
                    assert page.locator("#skillManualPanel").is_visible()
                    assert not page.locator("#directView").is_visible()
                    page.locator("#b66SkillStartDialog").get_by_role("button",name="양식 만들기 닫기").click()
                    page.wait_for_function("!document.querySelector('#b66SkillStartDialog').open")
                    assert not page.locator("#skillManualPanel").is_visible()
                    page.wait_for_function("!!document.querySelector('#skillManualPanel').closest('#skillSection')")
                    # A signed-in member without an assigned CGI skill can now
                    # collect quote facts; no simulated model or CGI call.
                    page.evaluate("""() => {
                        window.B66QuoteRuntimeBridge = {
                          readiness: () => ({authenticated:true,skillReady:false,profileReady:false,ready:false}),
                          clearPending: () => {},
                          assignedSavedSkillId: () => ''
                        };
                    }""")
                    page.locator("#easyComposer").fill("대한건설에 배관 견적 만들고 싶어요")
                    page.locator("#easySend").click()
                    page.get_by_text("먼저 누구에게 보내는 견적인가요?",exact=False).wait_for()
                    assert page.locator("#easyMessageList").get_by_text("대한건설에 배관 견적 만들고 싶어요").count()
                    assert not page.locator("#easyComposer").is_disabled()
                    page.locator("#easyComposer").fill("대한건설")
                    page.locator("#easySend").click()
                    page.get_by_text("담당자 이름이 있나요?",exact=False).wait_for()
                    for answer in ("없음","배관","2","18000","없음","별도","없음","현재"):
                        assert not page.locator("#easyComposer").is_disabled(), answer
                        page.locator("#easyComposer").fill(answer)
                        page.locator("#easySend").click()
                    page.locator("#easyChipRow").get_by_role("button",name="견적서 만들기").click()
                    page.get_by_text("기본 견적서로 작성했습니다.",exact=False).wait_for()
                    assert "대한건설" in page.locator("#quotePaper").inner_text()
                    assert "배관" in page.locator("#quotePaper").inner_text()
                    assert not errors, errors
                    print(f"B66_FORM_AND_CHAT_PASS={width}",flush=True)
                    page.close()
            finally:
                browser.close()
        server.shutdown()

if __name__=="__main__":
    main()
