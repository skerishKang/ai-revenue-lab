"""Real form.requestSubmit DOM path proof; app.js integration is separate."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

MODULE = Path(__file__).resolve().parents[1] / "static" / "voice-live-turn-controller.js"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content("""<!doctype html><html><body>
               <form id="composerForm">
                 <textarea id="messageInput"></textarea>
                 <button id="sendButton" type="submit">Send</button>
               </form></body></html>""")
            page.add_script_tag(path=str(MODULE))
            return page.evaluate("""() => {
              const form = document.getElementById('composerForm');
              const input = document.getElementById('messageInput');
              const button = document.getElementById('sendButton');
              const sent = [];
              form.addEventListener('submit',event=>{
                event.preventDefault();sent.push(input.value);
              });
              let user = 'verified-a1', sending = false;
              const c = window.PadiemVoiceLiveTurnController.create({
                accountKey:'verified-a1', getAccountKey:()=>user,
                getInFlight:()=>sending, getCanSubmit:()=>!button.disabled,
                commitText:text=>{input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}));},
                submit:()=>form.requestSubmit()
              });
              const checks = {};
              checks.constructor_no_send = c.getState().mode === 'basic';
              c.setMode('live');const generation = c.getState().sessionGeneration;
              const final = (id,value)=>({accountKey:'verified-a1',sessionGeneration:generation,
                accepted:true,endOfTurn:true,finalId:id,text:value});
              c.handleInterim({accountKey:'verified-a1',sessionGeneration:generation,
                isInterim:true,text:'not final'});
              checks.interim_zero = sent.length === 0;
              c.handleFinal({...final('a','unsafe'),accepted:false});
              checks.rejected_zero = sent.length === 0;
              button.disabled=true;c.handleFinal(final('a','disabled'));
              checks.disabled_zero = sent.length === 0;
              button.disabled=false;
              const accepted=c.handleFinal(final('a','real first'));
              checks.exact_one = sent.length === 1 && sent[0] === 'real first';
              c.handleFinal(final('a','duplicate'));
              checks.no_duplicate = sent.length === 1;
              sending=true;c.handleFinal(final('b','overlap'));
              checks.no_overlap = sent.length === 1;
              sending=false;
              const settled = c.markAnswerSettled({accountKey:'verified-a1',finalKey:accepted.finalKey});
              checks.settled = settled.ok === true;
              c.setCompositionActive(true);c.handleFinal(final('b','during IME'));
              checks.no_ime = sent.length === 1;
              c.endComposition();
              checks.no_deferred = sent.length === 1;
              c.handleFinal(final('b','real second'));
              checks.second_form_submit = sent.length === 2 && sent[1] === 'real second';
              user='signed-out';
              c.handleFinal(final('c','forbidden'));
              checks.auth_loss = sent.length === 2;
              return {checks,sent};
            }""")
        finally:
            browser.close()

if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(result["checks"].values()), result
    assert result["sent"] == ["real first", "real second"], result
