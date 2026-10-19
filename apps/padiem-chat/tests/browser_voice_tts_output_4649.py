"""Deterministic browser SpeechSynthesis mock for #4649 TTS output primitive.

Tests static/voice-tts-output.js in Chromium with speechSynthesis stubbed out,
so no real audio is produced and no microphone/provider is involved. Verifies:
explicit user start gate, Korean voice selection, 180-char chunking, bounded
8-utterance queue, cancel clears queue, stale late callbacks ignored, no
auto-resume after native error, queue-full rejection, oversize text rejection.
"""

from __future__ import absolute_import, division, print_function

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

MODULE = Path(__file__).resolve().parents[1] / "static" / "voice-tts-output.js"

KO_VOICE = {"name": "한국어", "lang": "ko-KR"}
EN_VOICE = {"name": "English", "lang": "en-US"}


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content("<!doctype html><html><body></body></html>")
            page.evaluate(
                """() => {
              window.nativeUtterances = [];
              window.nativeCancels = 0;
              window.nativeVoices = [%(ko)s, %(en)s];
              Object.defineProperty(window, 'SpeechSynthesisUtterance', {
                configurable: true,
                value: function (text) { this.text = text; }
              });
              Object.defineProperty(window, 'speechSynthesis', {
                configurable: true,
                value: {
                  speaking: false,
                  getVoices: function () { return window.nativeVoices; },
                  speak: function (u) { window.nativeUtterances.push(u); },
                  cancel: function () { window.nativeCancels += 1; }
                }
              });
            }"""
                % {"ko": json.dumps(KO_VOICE), "en": json.dumps(EN_VOICE)}
            )
            page.add_script_tag(path=str(MODULE))
            return page.evaluate(
                """() => {
              const lib = window.PadiemVoiceTTSOutput;
              let starts = 0, ends = 0;
              const errors = [], statuses = [];
              const t = lib.create({
                lang: 'ko-KR',
                onStart: function () { starts += 1; },
                onEnd: function () { ends += 1; },
                onError: function (e) { errors.push(e.reason); },
                onStatus: function (s) { statuses.push(s.status); }
              });
              const checks = {};
              checks.constructor_no_start = t.getState().userStartSatisfied === false;
              checks.no_speak_before_start = (t.speakText('hello') === false &&
                window.nativeUtterances.length === 0);
              checks.no_start_callback_before_native = starts === 0;
              t.start();
              checks.works_after_explicit_start = (t.speakText('안녕하세요') === true &&
                window.nativeUtterances.length === 1);
              checks.no_early_onStart = starts === 0;
              window.nativeUtterances[0].onstart();
              checks.native_start = starts === 1;
              const longWord = '가'.repeat(390);
              checks.long_korean_split = (t.speakText(longWord) === true &&
                t.getState().queued === 3);
              checks.chunk_max_180 = (window.nativeUtterances[0].text.length <= 180 &&
                t.getState().queued === 3);
              const old = window.nativeUtterances[0];
              t.cancel();
              checks.cancel_clears = (t.getState().queued === 0 &&
                t.getState().busy === false && window.nativeCancels === 1);
              old.onend();
              old.onerror({ error: 'late' });
              checks.late_callback_ignored = (ends === 0 && starts === 1 &&
                window.nativeUtterances.length === 1);
              const secondOk = t.speakText('다시 시작');
              const second = window.nativeUtterances[1];
              second.onstart(); second.onend();
              checks.after_cancel_reusable = (secondOk === true && ends === 1 &&
                starts === 2);
              checks.exact_korean_voice = second.voice.lang === 'ko-KR';
              t.stopOutput();
              checks.stop_disarms = (t.getState().userStartSatisfied === false &&
                t.speakText('after stop') === false);
              t.start();
              window.nativeVoices = [%(en)s];
              checks.no_english_for_korean = (t.speakText('한국어') === false &&
                window.nativeUtterances.length === 2 &&
                errors.indexOf('no-matching-voice') !== -1);
              window.nativeVoices = [%(ko)s];
              checks.oversize_rejected = (t.speakText('가'.repeat(1450)) === false &&
                errors.indexOf('text-too-long') !== -1);
              const queueOk = t.speakText('가'.repeat(1300));
              checks.bounded_queue = (queueOk === true &&
                t.getState().queued <= 7 &&
                window.nativeUtterances[window.nativeUtterances.length - 1].text.length <= 180);
              checks.queue_overflow_rejected = (t.speakText('추가') === false &&
                errors.indexOf('queue-full') !== -1);
              const failed = window.nativeUtterances[window.nativeUtterances.length - 1];
              failed.onerror({ error: 'native-fail' });
              checks.error_does_not_resume = (ends === 1 &&
                t.getState().queued === 0 &&
                t.getState().busy === false &&
                errors.indexOf('native-fail') !== -1);
              failed.onend();
              checks.late_end_after_error_ignored = (ends === 1 &&
                t.getState().queued === 0);
              t.cancel();
              checks.no_public_setter = typeof t.setUserStartSeen === 'undefined';
              return { checks, starts, ends, errors, statuses };
            }"""
                % {"ko": json.dumps(KO_VOICE), "en": json.dumps(EN_VOICE)}
            )
        finally:
            browser.close()


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    assert all(result["checks"].values()), result
