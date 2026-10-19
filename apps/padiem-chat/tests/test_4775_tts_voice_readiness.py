"""TTS first-click voice readiness and cancellation under delayed browser voices."""
import json
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_first_click_waits_for_voices_and_stop_cancels_pending():
    javascript = r"""
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const begin = source.indexOf('  function stopArticleTts(article) {');
const end = source.indexOf('  async function shareArticleText(', begin);
if (begin < 0 || end < 0) throw Error('TTS functions missing');
const lifecycle = source.slice(begin, end);
let ready = false, speaks = 0, cancels = 0, starts = 0;
const handlers = new Set();
const synth = {
  addEventListener: (name, fn) => { if (name === 'voiceschanged') handlers.add(fn); },
  removeEventListener: (name, fn) => { if (name === 'voiceschanged') handlers.delete(fn); },
};
const fake = {
  create: () => ({
    start: () => { starts += 1; },
    availableVoices: () => ready ? [{lang:'ko-KR'}] : [],
    speakText: (t) => { if (!ready) throw Error('spoke before voice ready'); speaks += 1; return true; },
    stopOutput: () => { cancels += 1; },
  }),
};
const button = { title: '', labels: {}, setAttribute(k,v){ this.labels[k]=v; } };
const article = { querySelector: () => button };
const context = {
  window: {speechSynthesis:synth}, document:{documentElement:{lang:'ko'}},
  ttsApi: () => fake, localeText: (k,f) => f, flashTitle:()=>{},
  setTimeout,clearTimeout,
};
const api=vm.runInNewContext(lifecycle + '\n({toggleArticleTts,stopArticleTts})',context);
api.toggleArticleTts(article,button,'??');
if (speaks !== 0 || button.labels['aria-pressed'] !== 'false' || handlers.size !== 1)
  throw Error('incorrect waiting behavior');
ready=true;
[...handlers].forEach(fn=>fn());
if (speaks !== 1 || button.labels['aria-pressed'] !== 'true' || handlers.size !== 0)
  throw Error('voice-ready playback failed');
api.toggleArticleTts(article,button,'??');
if (cancels !== 1 || button.labels['aria-pressed'] !== 'false' || article._ttsPlayer !== null)
  throw Error('stop action failed');
ready=false;
api.toggleArticleTts(article,button,'??');
api.toggleArticleTts(article,button,'??'); // explicit user cancel during wait
ready=true;[...handlers].forEach(fn=>fn());
if (speaks !== 1 || cancels !== 2 || handlers.size !== 0)
  throw Error('stale pending audio was played');
console.log(JSON.stringify({starts,speaks,cancels,queuedListeners:handlers.size,stopped:true}));
"""
    result = subprocess.run(
        ["node", "-e", javascript, str(STATIC / "outputs.js")],
        text=True, capture_output=True, timeout=12, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {"starts": 2, "speaks": 1, "cancels": 2,
                        "queuedListeners": 0, "stopped": True}
