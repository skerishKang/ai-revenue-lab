from datetime import datetime, timezone
import os
import sys
import time
import uuid
import pytest
from claw_connect.background_jobs import BackgroundJobs
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalCommandRequest, LocalRoot
from kagent.windows_local_executor import (WindowsSubprocessLocalAgentRuntime, WindowsExecutableProfile, DeterministicFakeWindowsExecutionAuthorizationPort)

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='canonical executor uses Windows Job Objects')

def setup(tmp_path, *, timeout=10, limit=2):
    device=LocalAgentDeviceProfile(device_id='device_1',workspace_ref='workspace_1',platform=LocalAgentPlatform.WINDOWS,roots=(LocalRoot(root_ref='repo',windows_path=str(tmp_path)),))
    profile=WindowsExecutableProfile(profile_ref='python',executable_path=sys.executable)
    auth=DeterministicFakeWindowsExecutionAuthorizationPort(capability_refs=('process.execute',))
    runtime=WindowsSubprocessLocalAgentRuntime(device=device,executable_profiles=(profile,),authorization_port=auth)
    return BackgroundJobs(tmp_path/'jobs',runtime=runtime,max_concurrent=limit,max_seconds=timeout),runtime

def command(code):
    return LocalCommandRequest(request_id='req_'+uuid.uuid4().hex,run_id='run_1',device_id='device_1',root_ref='repo',argv=(sys.executable,'-c',code),cwd_relative='.',requested_at=datetime.now(timezone.utc),timeout_seconds=20)

def await_state(manager,jid, expected, timeout=12):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        state=manager.status(jid)
        if state['state'] in expected and state['exit_code'] is not None: return state
        time.sleep(.05)
    raise AssertionError(manager.status(jid))

def test_start_output_recovery(tmp_path):
    manager,runtime=setup(tmp_path)
    item=manager.start(command("print('hello world', flush=True)"),job_owner='alice')
    jid=item['job_id']
    state=await_state(manager,jid,{'done'})
    assert state['exit_code']==0 and state['output_size']>=11
    assert manager.output(jid,0,5)=='hello'
    assert manager.list('bob')==[]
    recovered=BackgroundJobs(tmp_path/'jobs',runtime=runtime)
    assert recovered.list('alice')[0]['job_id']==jid
    assert recovered.output(jid,0,5)=='hello'

def test_concurrency_and_kill(tmp_path):
    manager,_=setup(tmp_path,limit=1)
    jid=manager.start(command('import time;time.sleep(10)'),job_owner='alice')['job_id']
    with pytest.raises(RuntimeError): manager.start(command("print('x')"),job_owner='alice')
    assert manager.kill(jid)
    assert await_state(manager,jid,{'killed'})['state']=='killed'
    assert manager.kill(jid) is False

def test_timeout_kills(tmp_path):
    manager,_=setup(tmp_path,timeout=.2)
    jid=manager.start(command('import time;time.sleep(10)'),job_owner='alice')['job_id']
    assert await_state(manager,jid,{'killed'})['state']=='killed'

def test_untrusted_command_rejected(tmp_path):
    manager,_=setup(tmp_path)
    request=LocalCommandRequest(request_id='request_2',run_id='run_1',device_id='device_1',root_ref='repo',argv=(r'C:\\Windows\\System32\\cmd.exe',),cwd_relative='.',requested_at=datetime.now(timezone.utc),timeout_seconds=5)
    with pytest.raises(Exception): manager.start(request,job_owner='alice')
    assert manager.list('alice') == []


def test_output_appears_while_process_runs(tmp_path):
    manager, _ = setup(tmp_path)
    jid = manager.start(command("import time;print('live',flush=True);time.sleep(4)"),job_owner='alice')['job_id']
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and manager.status(jid)['output_size'] < 4:
        time.sleep(.05)
    assert manager.status(jid)['state'] == 'running'
    assert manager.output(jid, 0, 4) == 'live'
    assert manager.kill(jid)
    await_state(manager, jid, {'killed'})


def test_failed_exit_record_survives_restart(tmp_path):
    manager, runtime = setup(tmp_path)
    jid = manager.start(command('import sys;sys.exit(7)'),job_owner='alice')['job_id']
    assert await_state(manager, jid, {'failed'})['exit_code'] == 7
    restored = BackgroundJobs(tmp_path/'jobs',runtime=runtime)
    assert restored.status(jid)['exit_code'] == 7


def test_interrupted_receipt_is_not_replayed(tmp_path):
    manager, runtime = setup(tmp_path)
    jid = manager.start(command("print('done')"), job_owner='alice')['job_id']
    await_state(manager, jid, {'done'})
    record = manager._load(jid)
    record.update(state='running', finished_at=None, exit_code=None)
    manager._save(record)
    restored = BackgroundJobs(tmp_path/'jobs', runtime=runtime)
    assert restored.status(jid)['state'] == 'failed'
    assert restored.list('alice')[0]['job_id'] == jid


def test_duplicate_active_request_is_rejected(tmp_path):
    manager, _ = setup(tmp_path)
    req = command('import time;time.sleep(5)')
    jid = manager.start(req, job_owner='alice')['job_id']
    with pytest.raises(RuntimeError):
        manager.start(req, job_owner='alice')
    assert manager.kill(jid)
    await_state(manager, jid, {'killed'})
