"""#4816 four-mode voice integration (mocked recognizer + browser TTS)."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
SCRIPTS = (
    # #4643: the shared voice turn authority loads first. voice-stt-input.js
    # reads the merge and turn-boundary rules from it and fails closed when it
    # is absent, exactly like index.html orders it.
    "voice-live-transcript-turn.js",
    "voice-stt-input.js", "voice-composer.js",
    "voice-live-turn-controller.js", "voice-tts-output.js",
    "voice-ui-menu.js", "voice-answer-ui.js", "voice-call-ui.js",
    # #5559: the single answer playback control lives in the answer action row
    # rendered by outputs.js, not in the voice module.
    "outputs.js",
)


def test_voice_labels_come_from_the_locale_catalogue():
    """Chat/Claw separation: the Korean voice copy came from corrupted inline escape sequences.

    Every voice label now reads the existing locale catalogue, and the
    catalogue owns the new ``voice-mode`` key that the waveform button binds.
    """
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    expected = {
        "voice-mode": "음성 모드",
        "voice-mode-text": "문자로 답변",
        "voice-mode-tts": "문자 + 음성 함께",
        "voice-mode-call": "음성 통화",
        "voice-speech-unavailable": "음성 재생 불가",
        "voice-call-listening": "듣는 중",
        "voice-call-transcribing": "변환 중",
        "voice-call-final": "최종 전사",
        "voice-call-stopped": "중지됨",
        "voice-call-error": "오류",
        "voice-call-idle": "대기",
        "voice-call-mute": "음소거",
        "voice-call-end": "통화 종료",
        "voice-call-transcript": "대화 내용 보기",
    }
    for key, ko in expected.items():
        assert f'"{key}": "{ko}"' in locale, f"missing locale key {key}"
    # The already existing answer-listen keys are reused, not duplicated.
    assert '"answer-listen": "음성 듣기"' in locale
    assert '"answer-listen-stop": "음성 정지"' in locale
    for name in ("voice-answer-ui.js", "voice-ui-menu.js", "voice-call-ui.js"):
        source = (STATIC / name).read_text(encoding="utf-8")
        # The corrupted Korean escapes that rendered "의식의발 통한".
        for broken in ("\\uc758\\uc2dd", "\\ubc1c", "\\ud5c8", "\\ubb5c\\uc9e5", "\\ud504", "\\ub17c\\ubb3c"):
            assert broken not in source, f"{name} still carries {broken}"
        assert "localeText(" in source, f"{name} must read the locale catalogue"


def test_voice_four_modes():
    with sync_playwright() as tool:
        browser = tool.chromium.launch()
        page = browser.new_page()
        page.set_content("""<!doctype html><html lang="ko"><body>
          <div class="app-shell" data-state="chat">
            <form id="composerForm">
              <div class="composer-actions">
                <button id="sendButton" type="submit">
                  <svg class="send-arrow-icon" aria-hidden="true"></svg>
                  <svg class="send-waveform-icon" aria-hidden="true" hidden></svg>
                </button>
              </div>
              <textarea id="messageInput"></textarea>
            </form>
            <main id="messageList"></main>
          </div>
          <!-- outputs.js mounts the answer action row only when its saved-output
               dialog exists; the dialog itself is not under test here. -->
          <dialog id="savedOutputDialog">
            <button id="savedOutputClose" type="button">x</button>
            <input id="savedOutputTitleInput">
            <div id="savedOutputContent"></div>
            <div id="savedOutputStatus"></div>
            <button id="savedOutputCopy" type="button">c</button>
            <button id="savedOutputDownload" type="button">d</button>
            <button id="savedOutputRename" type="button">r</button>
            <button id="savedOutputDelete" type="button">x</button>
          </dialog>
        </body></html>""")
        page.evaluate("""() => {
          window.__voices = [{name:'Korean',lang:'ko-KR'}];
          window.__ttsSpoken = [];
          window.__ttsCancelled = 0;
          Object.defineProperty(window, 'speechSynthesis', {configurable:true,value:{
            getVoices:()=>window.__voices,
            speak:u=>window.__ttsSpoken.push(u.text),
            cancel:()=>{window.__ttsCancelled++;},
            get speaking(){return false;}
          }});
          window.SpeechSynthesisUtterance = function(text){this.text=text;};
        }""")
        for script in SCRIPTS:
            page.add_script_tag(path=str(STATIC / script))
        page.evaluate("""() => {
          const input = document.getElementById('messageInput');
          const form = document.getElementById('composerForm');
          window.__test = {sent:[]};
          // #5561: the primary slot is not disabled by an empty composer. It
          // becomes the voice picker, so the empty state stays clickable.
          // outputs.js renders the answer action row only for a completed
          // turn; this harness has no lifecycle module.
          window.PadiemChatLifecycle = {isCompleted: () => true};
          form.addEventListener('submit',e=>{
            e.preventDefault();
            window.__test.sent.push(input.value);
            input.disabled=true;
            setTimeout(()=>{
              input.disabled=false;
              input.value='';
              input.dispatchEvent(new Event('input',{bubbles:true}));
            },0);
          });
          window.PadiemVoiceComposer.registerRecognizerFactory((cb)=>{
            window.__test.callbacks=cb;
            return {stop:()=>{}};
          });
          window.dispatchEvent(new CustomEvent('padiem:auth-state',{
            detail:{authenticated:true,identityKey:'account-one'}}
          ));
        }""")
        page.wait_for_timeout(100)

        def mic(text, fid):
            page.evaluate("""(args) => {
              const c = window.__test.callbacks;
              c.onFinal({text: args.text, utteranceId: args.fid, stopped: false});
            }""", {"text": text, "fid": fid})

        def clear_input():
            page.evaluate("""() => {
              const input = document.getElementById('messageInput');
              input.value = '';
              input.dispatchEvent(new Event('input',{bubbles:true}));
            }""")
            page.wait_for_timeout(20)

        checks = {}

        # --- M1: microphone draft is manual, never auto-sent ---
        page.evaluate("""() => document.getElementById('voiceMicButton').click()""")
        page.wait_for_timeout(50)
        mic("draft manual", "m1-1")
        page.wait_for_timeout(50)
        checks["m1_draft_in_input"] = page.evaluate("""() =>
          document.getElementById('messageInput').value.trim() === 'draft manual'""")
        checks["m1_no_auto_send"] = page.evaluate("""() =>
          window.__test.sent.length === 0""")
        page.evaluate("""() => {
          const input = document.getElementById('messageInput');
          input.value = input.value.trim() + ' edited';
          input.dispatchEvent(new Event('input',{bubbles:true}));
        }""")
        page.wait_for_timeout(30)
        checks["m1_edit_preserved"] = page.evaluate("""() =>
          document.getElementById('messageInput').value.includes('edited')""")

        # Stop M1 run before switching modes
        page.evaluate("""() => window.PadiemVoiceComposer.getController().stop('user-stopped')""")
        page.wait_for_timeout(50)
        clear_input()

        # --- M2: "문자로 답변" arms exactly one auto-send per turn ---
        page.evaluate("""() => document.getElementById('sendButton').click()""")
        page.wait_for_timeout(50)
        checks["m2_menu_opened"] = page.evaluate("""() =>
          !document.getElementById('voiceModeMenu').hidden""")
        page.evaluate("""() => {
          const items = document.querySelectorAll('.voice-mode-menu-item');
          for (const it of items) {
            if (it.textContent.includes('문자로 답변')) {
              it.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
              break;
            }
          }
        }""")
        page.wait_for_timeout(50)
        checks["m2_text_selected"] = page.evaluate("""() => {
          const sel = document.querySelector('.voice-mode-menu-item[data-active="true"]');
          return !!sel && sel.textContent.includes('문자로 답변');
        }""")
        # First utterance
        clear_input()
        page.evaluate("""() => document.getElementById('voiceMicButton').click()""")
        page.wait_for_timeout(50)
        page.evaluate("""() => window.__test.callbacks.onInterim({
          accountKey:'account-one', sessionGeneration:1, isInterim:true, text:'partial'})""")
        page.wait_for_timeout(30)
        checks["m2_interim_no_send"] = page.evaluate("""() =>
          window.__test.sent.length === 0""")
        mic("auto message", "m2-1")
        page.wait_for_timeout(30)
        page.evaluate("""() => window.__test.callbacks.onAutoStopRequested()""")
        page.wait_for_timeout(50)
        page.evaluate("""() => window.__test.callbacks.onTurnComplete({
          accepted: true, endOfTurn: true, finalId: 'm2-1'})""")
        page.wait_for_timeout(100)
        checks["m2_exactly_once"] = page.evaluate("""() =>
          window.__test.sent.length === 1 &&
          window.__test.sent[0] === 'auto message'""")
        # same finalId must not resend
        page.evaluate("""() => window.__test.callbacks.onTurnComplete({
          accepted: true, endOfTurn: true, finalId: 'm2-1'})""")
        page.wait_for_timeout(50)
        checks["m2_no_duplicate"] = page.evaluate("""() =>
          window.__test.sent.length === 1""")
        # a new utterance in the same live session sends once more
        clear_input()
        page.wait_for_timeout(200)  # let setTimeout clear input
        page.evaluate("""() => document.getElementById('voiceMicButton').click()""")
        page.wait_for_timeout(50)
        mic("auto message again", "m2-2")
        page.wait_for_timeout(30)
        page.evaluate("""() => window.__test.callbacks.onAutoStopRequested()""")
        page.wait_for_timeout(50)
        page.evaluate("""() => window.__test.callbacks.onTurnComplete({
          accepted: true, endOfTurn: true, finalId: 'm2-2'})""")
        page.wait_for_timeout(100)
        checks["m2_new_utterance_sends_once"] = page.evaluate("""() =>
          window.__test.sent.length === 2 &&
          window.__test.sent[1] === 'auto message again'""")
        # busy input blocks
        clear_input()
        page.wait_for_timeout(200)
        page.evaluate("""() => document.getElementById('messageInput').disabled = true""")
        page.evaluate("""() => document.getElementById('voiceMicButton').click()""")
        page.wait_for_timeout(50)
        mic("while busy", "m2-3")
        page.wait_for_timeout(30)
        page.evaluate("""() => window.__test.callbacks.onAutoStopRequested()""")
        page.wait_for_timeout(50)
        page.evaluate("""() => window.__test.callbacks.onTurnComplete({
          accepted: true, endOfTurn: true, finalId: 'm2-3'})""")
        page.wait_for_timeout(100)
        checks["m2_busy_blocked"] = page.evaluate("""() =>
          window.__test.sent.length === 2""")
        page.evaluate("""() => document.getElementById('messageInput').disabled = false""")

        # --- M3: "문자 + 음성 함께" auto-sends and speaks answers ---
        clear_input()
        page.wait_for_timeout(200)
        page.evaluate("""() => {
          document.querySelector('.voice-mode-menu-item[data-mode="tts"]')
            .dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        }""")
        page.wait_for_timeout(50)
        page.evaluate("""() => document.getElementById('voiceMicButton').click()""")
        page.wait_for_timeout(50)
        mic("auto tts message", "m3-1")
        page.wait_for_timeout(30)
        page.evaluate("""() => window.__test.callbacks.onAutoStopRequested()""")
        page.wait_for_timeout(50)
        page.evaluate("""() => window.__test.callbacks.onTurnComplete({
          accepted: true, endOfTurn: true, finalId: 'm3-1'})""")
        page.wait_for_timeout(100)
        checks["m3_auto_sent_once"] = page.evaluate("""() =>
          window.__test.sent.filter(s => s === 'auto tts message').length === 1""")
        page.evaluate("""() => {
          const main = document.getElementById('messageList');
          const article = document.createElement('article');
          article.className = 'assistant-message';
          article.innerHTML = '<div class="assistant-meta">Padiem Chat</div>' +
            '<div class="assistant-body"><div class="assistant-content">' +
            '<p>\\uc544\\ub514\\uc744 \\ub54c\\uc774\\ub958\\uc774\\ub294\\ubc88\\uc6d0.</p>' +
            '</div></div>';
          main.appendChild(article);
        }""")
        page.wait_for_timeout(120)
        checks["m3_tts_spoke_once"] = page.evaluate("""() =>
          window.__ttsSpoken.length === 1 &&
          window.__ttsSpoken[0] === '\\uc544\\ub514\\uc744 \\ub54c\\uc774\\ub958\\uc774\\ub294\\ubc88\\uc6d0.'""")
        checks["m3_listen_button"] = page.evaluate("""() =>
          !!document.querySelector('.answer-action.answer-listen')""")
        # Voice copy: the answer listen button used corrupted Korean escape
        # sequences and rendered as "의식의발 통한". The label now comes from
        # the locale catalogue (the fallback copy when no catalogue is loaded).
        checks["m3_listen_label"] = page.evaluate("""() => {
          const b = document.querySelector('.answer-action.answer-listen');
          if (!b) return false;
          const label = (b.getAttribute('aria-label') || '').trim();
          return label === '음성 듣기'
            && b.getAttribute('data-padiem-tooltip') === '음성 듣기';
        }""")
        checks["voice_menu_labels"] = page.evaluate("""() => {
          const items = Array.from(document.querySelectorAll('.voice-mode-menu-item'));
          const labels = items.map((i) => (i.textContent || '').trim());
          return labels.length === 3
            && labels[0] === '문자로 답변'
            && labels[1] === '문자 + 음성 함께'
            && labels[2] === '음성 통화';
        }""")
        # #5561: the waveform and the arrow share one slot, so the voice label
        # rides on the send button rather than a separate control.
        checks["voice_wave_label"] = page.evaluate("""() => {
          const slot = document.getElementById('sendButton');
          const wave = slot.querySelector('.send-waveform-icon');
          return slot.dataset.primaryAction === 'voice'
            && slot.getAttribute('title') === '음성 모드'
            && slot.getAttribute('aria-label') === '음성 모드'
            && !!wave && wave.hidden === false;
        }""")

        # --- M4: "음성 통화" shows call panel, end returns to chat ---
        page.evaluate("""() => {
          document.querySelector('.voice-mode-menu-item[data-mode="call"]')
            .dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        }""")
        page.wait_for_timeout(80)
        checks["m4_panel_visible"] = page.evaluate("""() =>
          !document.getElementById('voiceCallPanel').hidden""")
        checks["m4_call_selected"] = page.evaluate("""() =>
          !!document.querySelector('.voice-mode-menu-item[data-mode="call"][data-active="true"]')""")
        checks["m4_mute_toggle"] = page.evaluate("""() => {
          const b = document.getElementById('voiceCallMute');
          b.click();
          return b.getAttribute('aria-pressed') === 'true';
        }""")
        page.evaluate("""() => document.getElementById('voiceCallEnd').click()""")
        page.wait_for_timeout(50)
        checks["m4_end_returns"] = page.evaluate("""() =>
          document.getElementById('voiceCallPanel').hidden""")
        # Voice copy: the call panel copy was corrupted inline Korean escape
        # sequences as well ("의식 통한", "있용금", "논물 본기").
        checks["m4_call_labels"] = page.evaluate("""() => {
          const panel = document.getElementById('voiceCallPanel');
          if (!panel) return false;
          const mute = document.getElementById('voiceCallMute');
          const end = document.getElementById('voiceCallEnd');
          const summary = panel.querySelector('summary');
          return panel.getAttribute('aria-label') === '음성 통화'
            && (mute.textContent || '').trim() === '음소거'
            && (end.textContent || '').trim() === '통화 종료'
            && !!summary && (summary.textContent || '').trim() === '대화 내용 보기';
        }""")

        result = {"checks": checks, "sent": page.evaluate("() => Array.from(window.__test.sent)"),
                  "spoken": page.evaluate("() => Array.from(window.__ttsSpoken)")}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        assert all(result["checks"].values()), result["checks"]
        browser.close()


if __name__ == "__main__":
    test_voice_four_modes()