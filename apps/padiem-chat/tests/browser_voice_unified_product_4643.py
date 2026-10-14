"""Mocked real DOM integration: Mode 1 stays manual; Mode 2 single auto-send; TTS click-only."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
SCRIPTS = (
    "voice-stt-input.js", "voice-composer.js",
    "voice-live-turn-controller.js", "voice-tts-output.js",
    "voice-ui-integration.js",
)


def run():
    with sync_playwright() as tool:
        browser = tool.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content("""<!doctype html><html lang="ko"><body>
              <div class="app-shell" data-state="chat">
                <form id="composerForm">
                  <div class="composer-actions">
                    <button id="sendButton" type="submit" disabled>Send</button>
                  </div>
                  <textarea id="messageInput"></textarea>
                </form>
                <main id="messageList">
                  <article class="assistant-message">
                    <div class="assistant-meta">Padiem Chat</div>
                    <div class="assistant-content">Hello from answer</div>
                  </article>
                </main>
              </div>
            </body></html>""")
            page.evaluate("""() => {
              window.__voices = [{name:'Korean',lang:'ko-KR'}];
              window.__ttsSpoken = [];
              window.__ttsCancelled = 0;
              Object.defineProperty(window, 'speechSynthesis', {configurable:true,value:{
                getVoices:()=>window.__voices,
                speak:u=>window.__ttsSpoken.push(u),
                cancel:()=>{window.__ttsCancelled++},
                get speaking(){return false;}
              }});
              window.SpeechSynthesisUtterance = function(text){this.text=text;};
            }""")
            for script in SCRIPTS:
                page.add_script_tag(path=str(STATIC / script))
            page.evaluate("""() => {
              const input = document.getElementById('messageInput');
              const send = document.getElementById('sendButton');
              const form = document.getElementById('composerForm');
              window.__test = {sent:[], callbacks:null};
              input.addEventListener('input',()=>{ send.disabled = !input.value.trim(); });
              form.addEventListener('submit',e=>{
                e.preventDefault();
                window.__test.sent.push(input.value);
                input.disabled=true; send.disabled=true;
                setTimeout(()=>{input.disabled=false;input.value='';send.disabled=true;},0);
              });
              window.PadiemVoiceComposer.registerRecognizerFactory((cb)=>{
                window.__test.callbacks=cb;return {stop:()=>{}};
              });
              window.dispatchEvent(new CustomEvent('padiem:auth-state',{
                detail:{authenticated:true,identityKey:'account-one'}
              }));
            }""")
            page.wait_for_timeout(90)
            first = page.evaluate("""() => {
              const checks = {};
              const composer = window.PadiemVoiceComposer.getController();
              const mic = document.getElementById('voiceMicButton');
              const toggle = document.getElementById('voiceAutoSendToggle');
              checks.new_toggle_present = !!toggle && !toggle.disabled;
              checks.mode1_is_default = toggle.getAttribute('aria-pressed')==='false';
              checks.tts_button_present = !!document.querySelector('.voice-answer-listen');
              checks.tts_no_auto = window.__ttsSpoken.length===0;
              mic.click();
              window.__test.callbacks.onFinal({text:'draft manual',utteranceId:'first'});
              composer.stop('user-stopped');
              window.__test.callbacks.onTurnComplete({accepted:true,endOfTurn:true,finalId:'first'});
              checks.manual_no_auto = window.__test.sent.length===0 &&
                document.getElementById('messageInput').value.includes('draft manual');
              return checks;
            }""")
            page.evaluate("""() => {
              const input = document.getElementById('messageInput');
              input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));
              document.getElementById('voiceAutoSendToggle').click();
            }""")
            page.wait_for_timeout(90)
            second = page.evaluate("""() => {
              const checks = {};
              const composer = window.PadiemVoiceComposer.getController();
              const mic = document.getElementById('voiceMicButton');
              checks.mode2_opt_in = window.PadiemVoiceMode2UI.getState().mode==='live';
              mic.click();
              checks.auto_mode_armed = window.PadiemVoiceMode2UI.isLiveActive();
              window.__test.callbacks.onInterim('partial not accepted');
              checks.interim_not_sent = window.__test.sent.length===0;
              window.__test.callbacks.onAutoStopRequested(); // same as VAD silence
              checks.auto_stopped_composer = composer.getStatus().active === false;
              window.__test.callbacks.onFinal({text:'accepted message',utteranceId:'second',stopped:true});
              window.__test.callbacks.onTurnComplete({accepted:true,endOfTurn:true,finalId:'second'});
              checks.auto_exactly_once = window.__test.sent.length===1 &&
                window.__test.sent[0]==='accepted message';
              window.__test.callbacks.onTurnComplete({accepted:true,endOfTurn:true,finalId:'second'});
              checks.no_duplicate = window.__test.sent.length===1;
              return checks;
            }""")
            page.wait_for_timeout(70)
            page.evaluate("""() => {
              document.getElementById('voiceMicButton').click();
              document.getElementById('messageInput').focus();
            }""")
            page.keyboard.type("typed during recording")
            typed = page.evaluate("""() => {
              const composer=window.PadiemVoiceComposer.getController();
              window.__test.callbacks.onAutoStopRequested();
              window.__test.callbacks.onFinal({
                text:'recognized but edited',utteranceId:'user-edited',stopped:true
              });
              window.__test.callbacks.onTurnComplete({
                accepted:true,endOfTurn:true,finalId:'user-edited'
              });
              return {
                manual_edit_prevents_auto:window.__test.sent.length===1,
                editable_input_preserved:document.getElementById('messageInput').value.includes('typed during recording')
              };
            }""")
            page.wait_for_timeout(70)
            third = page.evaluate("""() => {
              const checks = {};
              const button=document.querySelector('.voice-answer-listen');
              checks.no_tts_before_click = window.__ttsSpoken.length===0;
              button.click();
              checks.click_speaks_once = window.__ttsSpoken.length===1 &&
                window.__ttsSpoken[0].text==='Hello from answer';
              checks.explicit_korean_voice = window.__ttsSpoken[0].voice.lang==='ko-KR';
              button.click();
              checks.second_click_stops = window.__ttsCancelled>0;
              window.dispatchEvent(new CustomEvent('padiem:auth-state',{detail:{authenticated:false}}));
              checks.signout_disarms_tts = button.getAttribute('aria-pressed')==='false';
              return checks;
            }""")
            return {"checks": {**first, **second, **typed, **third},
                    "sent":page.evaluate("window.__test.sent"),
                    "speaks":page.evaluate("window.__ttsSpoken.length")}
        finally:
            browser.close()


if __name__ == "__main__":
    result=run()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    assert all(result["checks"].values()), result
    assert result["sent"] == ["accepted message"], result
