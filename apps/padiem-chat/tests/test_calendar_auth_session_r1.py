"""R1: real Calendar module follows owner events without stale DOM resurrection."""
from functools import lru_cache
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_calendar_ui_work_log_create import _HARNESS, CALENDAR_JS_PATH, INDEX_PATH


@lru_cache(maxsize=1)
def _journey():
    # Reuse the existing real-index DOM stub; only the server and event bus differ.
    setup = _HARNESS.split("const requests = [];", 1)[0]
    dom = "const doc = {" + _HARNESS.split("const doc = {", 1)[1].split("const checks = {};", 1)[0]
    dom = dom.replace("sandbox.window.addEventListener = () => {};", """
const listeners = {};
sandbox.window.addEventListener = (type, fn) => (listeners[type] ||= []).push(fn);
sandbox.window.dispatchEvent = (event) => (listeners[event.type] || []).forEach(fn => fn(event));
sandbox.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init.detail; } };
""")
    script = setup + r"""
const pending = [];
function fetchImpl(url) {
  return new Promise(resolve => pending.push({url, resolve}));
}
const response = title => ({ok:true, status:200, json: async () => ({ok:true, projection:{items:[{
  calendar_item_id:'item_log_test', item_type:'work_log', title, date:'2026-11-08'
}]}})});
const flush = () => new Promise(resolve => setImmediate(resolve));
const contents = node => [node.textContent || '', ...(node.children || []).map(contents)].join(' ');
""" + dom + r"""
vm.runInContext(fs.readFileSync(process.argv[4], 'utf8'), sandbox, {filename:'auth-session.js'});
const status = owner => ({ready:true, authenticated:!!owner, project_files_ready:true,
  user:owner ? {email:owner, name:'Shared name'} : null});
let generation = 0;
const login = owner => sandbox.PadiemAuthSession.update(status(owner), ++generation);
login('owner-a@example.test');
vm.runInContext(CALENDAR_JS, sandbox, {filename:'calendar.js'});
(async () => {
  const checks = {};
  byId.calendarNavButton.click();
  pending[0].resolve(response('OWNER_A'));
  await flush();
  checks.initial = contents(byId.calendarList).includes('OWNER_A') && pending.length === 1;
  login('owner-a@example.test');
  sandbox.PadiemAuthSession.update({...status('owner-a@example.test'), user:{email:'owner-a@example.test', name:'Renamed'}}, ++generation);
  await flush();
  checks.same_owner = pending.length === 1 && contents(byId.calendarList).includes('OWNER_A');
  byId.calendarRefresh.click();
  const oldRead = pending[1];
  login('owner-b@example.test');
  checks.owner_change_clears = !contents(byId.calendarList).includes('OWNER_A') && pending.length === 3;
  pending[2].resolve(response('OWNER_B'));
  await flush();
  oldRead.resolve(response('STALE_OWNER_A'));
  await flush();
  checks.stale_read = contents(byId.calendarList).includes('OWNER_B') && !contents(byId.calendarList).includes('OWNER_A');
  login(null);
  sandbox.dispatchEvent({type:'padiem:localechange'});
  checks.logout_locale = byId.calendarList.children.length === 0 && !contents(byId.calendarPanel).includes('OWNER_B') && pending.length === 3;
  login('owner-c@example.test');
  checks.relogin = pending.length === 4;
  login(null);
  pending[3].resolve(response('STALE_OWNER_C'));
  await flush();
  sandbox.dispatchEvent({type:'padiem:localechange'});
  checks.logout_inflight = byId.calendarList.children.length === 0 && !contents(byId.calendarPanel).includes('OWNER_C');
  // The same real store drives Library without a capability event.
  shell.dataset.state = 'home';
  login('owner-a@example.test');
  vm.runInContext(fs.readFileSync(process.argv[5], 'utf8'), sandbox, {filename:'library.js'});
  const fileResponse = owner => ({ok:true, status:200, json:async () => ({files:[{
    id:'file-' + owner, name:owner, project_id:'project-1', media_type:'text/plain'
  }], has_more:false, next_cursor:null})});
  byId.filesNavButton.click();
  pending[4].resolve(fileResponse('FILE_OWNER_A'));
  await flush();
  checks.library_initial = sandbox.PadiemChatLibrary.getRowCount() === 1 && contents(byId.libraryFileList).includes('FILE_OWNER_A');
  const originalLibraryRow = byId.libraryFileList.children[0];
  login('owner-a@example.test');
  sandbox.PadiemAuthSession.update({...status('owner-a@example.test'), user:{email:'owner-a@example.test', name:'Renamed'}}, ++generation);
  sandbox.dispatchEvent({type:'padiem:capabilitychange', detail:{auth:{
    loaded:true, authenticated:true, projectFilesReady:true,
    ownerKey:'owner-a@example.test', displayName:'Shared name'
  }}});
  await flush();
  checks.library_same = pending.length === 5 && sandbox.PadiemChatLibrary.getRowCount() === 1
    && byId.libraryFileList.children[0] === originalLibraryRow;
  login('owner-b@example.test');
  checks.library_switch = pending.length === 6 && sandbox.PadiemChatLibrary.getRowCount() === 0;
  pending[5].resolve(fileResponse('FILE_OWNER_B'));
  await flush();
  checks.library_switch = checks.library_switch && contents(byId.libraryFileList).includes('FILE_OWNER_B') && !contents(byId.libraryFileList).includes('FILE_OWNER_A');
  login('owner-c@example.test');
  const staleFileRead = pending[6];
  login('owner-d@example.test');
  pending[7].resolve(fileResponse('FILE_OWNER_D'));
  await flush();
  staleFileRead.resolve(fileResponse('STALE_FILE_OWNER_C'));
  await flush();
  checks.library_stale = sandbox.PadiemChatLibrary.getRowCount() === 1 && contents(byId.libraryFileList).includes('FILE_OWNER_D') && !contents(byId.libraryFileList).includes('FILE_OWNER_C');
  login(null);
  checks.library_logout = sandbox.PadiemChatLibrary.getRowCount() === 0 && byId.libraryFileList.children.length === 0;
  process.stdout.write(JSON.stringify(checks));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    node = shutil.which("node")
    assert node, "Node is required for the real-module harness"
    with tempfile.TemporaryDirectory(prefix="r1-calendar-") as directory:
        harness = Path(directory) / "journey.cjs"
        harness.write_text(script, encoding="utf-8")
        completed = subprocess.run(
            [node, str(harness), str(CALENDAR_JS_PATH), str(INDEX_PATH),
             str(CALENDAR_JS_PATH.with_name("auth-session.js")),
             str(CALENDAR_JS_PATH.with_name("library.js"))],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_same_owner_refresh_keeps_calendar_rows_without_reloading():
    result = _journey()
    assert result["initial"] and result["same_owner"], result


def test_owner_change_clears_rows_and_discards_inflight_previous_owner():
    result = _journey()
    assert result["owner_change_clears"] and result["stale_read"] and result["relogin"], result


def test_logout_and_locale_change_cannot_resurrect_calendar_rows():
    result = _journey()
    assert result["logout_locale"] and result["logout_inflight"], result


def test_library_session_event_keeps_same_owner_and_replaces_same_named_owner():
    result = _journey()
    assert result["library_initial"] and result["library_same"] and result["library_switch"], result


def test_library_session_event_discards_stale_owner_fetch_and_clears_logout():
    result = _journey()
    assert result["library_stale"] and result["library_logout"], result
