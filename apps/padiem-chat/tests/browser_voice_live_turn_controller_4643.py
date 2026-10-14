"""Isolated browser contract evidence for explicit Mode 2 (no product wiring)."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

MODULE = Path(__file__).resolve().parents[1] / "static" / "voice-live-turn-controller.js"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content("<!doctype html><html><body></body></html>")
            page.add_script_tag(path=str(MODULE))
            return page.evaluate("""() => {
              const api = window.PadiemVoiceLiveTurnController;
              let user = 'a1', busy = false, enabled = true, count = 0;
              const submissions = [], commits = [], previews = [];
              const c = api.create({
                mode:'live', accountKey:'a1',
                getAccountKey:()=>user, getInFlight:()=>busy,
                getCanSubmit:()=>enabled,
                commitText:t=>{commits.push(t);},
                submit:(t,m)=>{submissions.push([t,m]);count++;},
                onPreview:t=>previews.push(t)
              });
              const checks = {};
              checks.constructor_manual = c.getState().mode === 'basic';
              const gen0 = c.getState().sessionGeneration;
              c.setMode('live');
              const g = c.getState().sessionGeneration;
              checks.mode_generation_advanced = g > gen0;
              const event = (id,text) => ({accountKey:'a1',sessionGeneration:g,
                accepted:true,endOfTurn:true,finalId:id,text:text});
              checks.interim_no_submit = c.handleInterim({accountKey:'a1',
                sessionGeneration:g,isInterim:true,text:'preview'}).submitted === false && count === 0 && previews.length === 1;
              checks.no_missing_account = c.handleFinal({...event('f0','missing'),accountKey:undefined}).submitted === false;
              checks.no_missing_generation = c.handleFinal({...event('f0','missing'),sessionGeneration:undefined}).submitted === false;
              checks.no_missing_final_id = c.handleFinal({...event('f0','missing'),finalId:undefined}).submitted === false;
              checks.no_missing_accepted = c.handleFinal({...event('f0','missing'),accepted:undefined}).submitted === false;
              checks.no_missing_eot = c.handleFinal({...event('f0','missing'),endOfTurn:false}).submitted === false;
              checks.no_stale_generation = c.handleFinal({...event('f0','missing'),sessionGeneration:g-1}).submitted === false;
              busy=true;
              checks.no_inflight = c.handleFinal(event('f0','busy')).submitted === false;
              busy=false;enabled=false;
              checks.no_disabled = c.handleFinal(event('f0','disabled')).submitted === false;
              enabled=true;c.setCompositionActive(true);
              checks.no_ime = c.handleFinal(event('f0','ime')).submitted === false;
              c.endComposition();
              const first = c.handleFinal(event('f1','hello'));
              checks.submits_once = first.submitted === true && count === 1;
              checks.no_duplicate = c.handleFinal(event('f1','hello')).submitted === false && count === 1;
              checks.no_overlap = c.handleFinal(event('f2','next')).submitted === false && count === 1;
              checks.wrong_answer_rejected = c.markAnswerSettled({accountKey:'a1',finalKey:'wrong'}).ok === false;
              checks.answer_settle = c.markAnswerSettled({accountKey:'a1',finalKey:first.finalKey}).ok === true;
              checks.next_after_settle = c.handleFinal(event('f2','next')).submitted === true && count === 2;
              user='a2';
              checks.signout_revokes = c.handleFinal(event('f3','stale')).submitted === false;
              c.cancel();
              checks.cancel_revokes = c.handleFinal(event('f3','stale')).submitted === false;
              const unauth = api.create({mode:'live',accountKey:'a1',submit:()=>{count++},commitText:()=>{},getInFlight:()=>false});
              unauth.setMode('live');
              checks.no_auth_adapter = unauth.handleFinal({accountKey:'a1',sessionGeneration:2,
                accepted:true,endOfTurn:true,finalId:'x',text:'text'}).submitted === false;
              return {checks,submits:count,commits:commits.length,previews:previews.length};
            }""")
        finally:
            browser.close()

if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(result["checks"].values()), result
    assert result["submits"] == 2, result
