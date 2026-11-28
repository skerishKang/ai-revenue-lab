"""One canonical composer behavior for Chat, Claw and B66, with adapters."""

# #8060: shipped reads live in _support; assertions stay here.
from _support.shared_conversation_source import app_js, b66_easy_mode_js, b66_index_html, index_html, read, read_static, scroll_source_text
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "apps/padiem-chat/static"
B66 = REPO / "reference/business-66-padiem-quote-v1"
CANONICAL = REPO / "packages/padiem-conversation-ui/composer-core.js"


def test_canonical_bytes_are_exactly_same_for_two_release_targets():
    content = CANONICAL.read_bytes()
    assert content
    for path in (STATIC / "shared-conversation-composer.js",
                 B66 / "shared-conversation-composer.js"):
        assert path.read_bytes() == content
    assert b"shouldSubmitOnEnter" in content
    assert b"resizeTextarea" in content


def test_all_three_load_canonical_before_product_adapters():
    chat = index_html()
    b66 = b66_index_html()
    assert chat.index('src="./shared-conversation-composer.js"') < chat.index('src="./app.js"')
    assert b66.index('src="shared-conversation-composer.js"') < b66.index('src="easy-mode.js"')
    assert 'window.PadiemConversationComposer || localHandoffModule' in read_static('chat-conversation-module.js')
    assert 'sharedComposer?.shouldSubmitOnEnter?.(event, compositionGuard)' in b66_easy_mode_js()


def test_product_server_boundaries_stay_distinct():
    chat = read_static("chat-conversation-module.js")
    b66 = b66_easy_mode_js()
    assert "submitPrompt(input.value)" in chat
    assert "submitComposer();" in b66
    assert "inputHandler(text)" in b66


def test_chat_composer_wired_keyboard_and_ime_behavior():
    import subprocess
    import shutil
    node = shutil.which("node")
    assert node
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const dir = process.argv[1];
function run(mode) {
  const order = [], submissions = [];
  let cancelled = 0, picks = 0, busy = false;
  function element(id) {
    const handlers = {};
    return {id, disabled: false, value: 'draft', files: [], handlers,
      addEventListener(type, cb) { order.push(id + ':' + type); handlers[type] = cb; },
      emit(type, extra = {}) {
        let prevented = false;
        handlers[type]({preventDefault() { prevented = true; }, ...extra});
        return prevented;
      }
    };
  }
  const input = element('input'), form = element('form'), sendButton = element('send');
  const cancelStreamButton = element('cancel'), attachmentButton = element('attachment');
  const attachmentFileInput = element('file'), documentStarterButton = element('starter');
  const toggle = element('formats'), panel = {hidden:true};
  attachmentFileInput.click = () => picks++;
  form.requestSubmit = () => form.emit('submit');
  const doc = {getElementById(id) { return {composerForm:form,documentFormatsToggle:toggle,documentFormatsPanel:panel}[id] || null; },
    addEventListener(type) { order.push('document:' + type); }};
  const win = {};
  const ctx = vm.createContext({window:win,document:doc});
  vm.runInContext(fs.readFileSync(dir+'/shared-conversation-composer.js','utf8'),ctx);
  const canonical = ctx.PadiemConversationComposer;
  if (mode === 'canonical') win.PadiemConversationComposer = canonical;
  if (mode === 'fallback') win.PadiemClawLocalHandoff = canonical;
  vm.runInContext(fs.readFileSync(dir+'/chat-conversation-module.js','utf8'),ctx);
  const mod = win.PadiemChatConversationModule.create({input,form,sendButton,cancelStreamButton,attachmentButton,attachmentFileInput,get inFlight(){return busy;}});
  assert.deepEqual(order, []);
  mod.wireComposerEvents({submitPrompt: text => submissions.push(text),cancelActiveStream:()=>cancelled++,documentStarterButton});
  assert.deepEqual(order,['input:input','input:compositionstart','input:compositionupdate','input:compositionend','input:keydown','form:submit','cancel:click','attachment:click','starter:click','formats:click','document:click','file:change','form:dragover','form:drop']);
  for (const extra of [{shiftKey:true},{ctrlKey:true},{altKey:true},{metaKey:true},{isComposing:true},{keyCode:229}]) assert.equal(input.emit('keydown',{key:'Enter',...extra}),false);
  input.emit('compositionstart');
  assert.equal(input.emit('keydown',{key:'Enter'}),false);
  input.emit('compositionupdate');
  assert.equal(input.emit('keydown',{key:'Enter'}),false);
  input.emit('compositionend');
  assert.equal(input.emit('keydown',{key:'Enter'}),mode !== 'missing');
  assert.equal(submissions.length,mode === 'missing'?0:1);
  sendButton.disabled = true;
  input.emit('keydown',{key:'Enter'});
  assert.equal(submissions.length,mode === 'missing'?0:1);
  input.value = 'next';
  assert.equal(form.emit('submit'),true);
  assert.equal(submissions.at(-1),'next');
  cancelStreamButton.emit('click'); assert.equal(cancelled,1);
  attachmentButton.emit('click'); documentStarterButton.emit('click'); assert.equal(picks,2);
  const dataTransfer = {files:[]};
  assert.equal(form.emit('dragover',{dataTransfer}),true); assert.equal(dataTransfer.dropEffect,'copy');
  assert.equal(form.emit('drop',{dataTransfer}),true);
  busy = true;
  attachmentButton.emit('click'); documentStarterButton.emit('click'); assert.equal(picks,2);
  assert.equal(form.emit('dragover',{dataTransfer}),false);
  assert.equal(form.emit('drop',{dataTransfer}),false);
}
for (const mode of ['canonical','fallback','missing']) run(mode);
"""
    result = subprocess.run([node, "-e", script, str(STATIC)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
