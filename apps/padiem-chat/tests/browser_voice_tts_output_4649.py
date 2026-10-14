"""Deterministic browser SpeechSynthesis mock: start, queue, stale events, KO voice."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

MODULE = Path(__file__).resolve().parents[1] / "static" / "voice-tts-output.js"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content("<!doctype html><html><body><button id='start'>Start voice</button></body></html>")
            page.evaluate("""() => {
              window.nativeUtterances = [];
              window.nativeCancels = 0;
              window.nativeVoices = [{name:'한국어',lang:'ko-KR'},{name:'English',lang:'en-US'}];
              Object.defineProperty(window,'SpeechSynthesisUtterance',{configurable:true,
                value:function(text){ this.text=text; }});
              Object.defineProperty(window,'speechSynthesis',{configurable:true,
                value:{
                  speaking:false,
                  getVoices:()=>window.nativeVoices,
                  speak:u=>window.nativeUtterances.push(u),
                  cancel:()=>{window.nativeCancels++;}
                }
              });
            }""")
            page.add_script_tag(path=str(MODULE))
            return page.evaluate("""() => {
              const lib = window.PadiemVoiceTTSOutput;
              let starts = 0, ends = 0;
              const errors = [],statuses = [];
              const t = lib.create({lang:'ko-KR',onStart:()=>starts++,
                onEnd:()=>ends++,onError:e=>errors.push(e.reason),
                onStatus:s=>statuses.push(s.status),userGestureSeen:true});
              const checks = {};
              checks.constructor_no_start = !t.getState().userStartSatisfied;
              checks.no_speak_before_start = !t.speakText('hello') && nativeUtterances.length===0;
              checks.no_start_callback_before_native = starts===0;
              t.start();
              checks.works_after_explicit_start = t.speakText('안녕하세요') && nativeUtterances.length===1;
              checks.no_early_onStart = starts === 0;
              nativeUtterances[0].onstart();
              checks.native_start = starts===1;
              const longWord = '가'.repeat(390);
              checks.long_korean_split = t.speakText(longWord) &&
                t.getState().queued===3;
              checks.chunk_max_180 = nativeUtterances[0].text.length<=180 && t.getState().queued===3;
              const old = nativeUtterances[0];
              t.cancel();
              checks.cancel_clears = t.getState().queued===0 && !t.getState().busy &&
                nativeCancels===1;
              old.onend();
              old.onerror({error:'late'});
              checks.late_callback_ignored = ends===0 && starts===1 && nativeUtterances.length===1;
              const secondOk = t.speakText('다시 시작');
              const second = nativeUtterances[1];
              second.onstart();second.onend();
              checks.after_cancel_reusable = secondOk && ends===1 && starts===2;
              checks.exact_korean_voice = second.voice.lang==='ko-KR';
              t.stopOutput();
              checks.stop_disarms = !t.getState().userStartSatisfied && !t.speakText('after stop');
              t.start();
              nativeVoices = [{name:'English',lang:'en-US'}];
              checks.no_english_for_korean = !t.speakText('한국어') && nativeUtterances.length===2 &&
                errors.includes('no-matching-voice');
              nativeVoices = [{name:'한국어',lang:'ko-KR'}];
              checks.oversize_rejected = !t.speakText('가'.repeat(1450)) && errors.includes('text-too-long');
              const queue = t.speakText('가'.repeat(1300));
              checks.bounded_queue = queue && t.getState().queued<=7 &&
                nativeUtterances[nativeUtterances.length-1].text.length<=180;
              checks.queue_overflow_rejected = !t.speakText('추가') && errors.includes('queue-full');
              const failed = nativeUtterances[nativeUtterances.length-1];
              failed.onerror({error:'native-fail'});
              checks.error_does_not_resume = ends===1 && t.getState().queued===0 &&
                !t.getState().busy && errors.includes('native-fail');
              failed.onend();
              checks.late_end_after_error_ignored = ends===1 && t.getState().queued===0;
              t.cancel();
              checks.no_public_setter = typeof t.setUserStartSeen==='undefined';
              return {checks,starts,ends,errors,statuses};
            }""")
        finally:
            browser.close()

if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(result["checks"].values()), result
