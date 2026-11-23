"""#7987 — say whether a linked PC can take a user-mode command, before one is sent.

A PC can be connected (its Mesh agent answers) while the user-session helper is
not installed, nobody is signed in to Windows, or the helper is not listening.
The server could only learn that from a command that had already failed. This
module observes it instead, on the round that already reads the drive list
(#6460): the same authenticated Mesh agent connection, the same 30-second
cadence, one more fixed expression per PC, and the same queue channel upward.

Nothing new is opened. There is no PC command, no dispatch, no console window,
no new credential and no new port, and the helper itself is not changed - it
is looked at from outside, so a PC with an old helper or with none at all is
answered for too.

The expression only reads:

* whether the helper's scheduled-task file and its install folder exist;
* the names in the pipe namespace (a pipe is never opened or connected);
* the Windows session table, reduced on the PC to one boolean;
* the installed build's SHA-256 from the helper's own install record, of which
  the first twelve hex digits travel.

It creates no child process, file, task, timer or agent state, and it never
touches the helper's secret file. A value it could not read is ``None``; the
server treats that as "not known", never as "not ready".
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from padiem_ai_core.pc_helper_ready import (
    HELPER_READY_KEYS, HELPER_READY_OPTIONAL_KEYS, HELPER_UPDATE_RESULTS,
    REGISTRATION_ERRORS, HelperReadyError, validate_helper_ready,
)

HELPER_READY_PATH = "/api/claw/connector/mesh-reads/helper-ready"
HELPER_READY_PROTOCOL = "padiem-helper-ready-v1"
#: Off unless the deployment sets this to 1/true/on. Unset keeps the drive
#: round byte-for-byte what it was.
HELPER_READY_SWITCH = "ORACLE_MESH_HELPER_READY_REPORT"

# MeshAgent embeds Duktape, so this deliberately uses ES5. It is evaluated by
# the agent console's own ``eval`` and returns one object. It keeps no state:
# every evaluation reads the PC again and leaves nothing behind.
AGENT_HELPER_READY_JS = r"""
(function(rid){
var out={protocol: 'padiem-helper-ready-v1',request_id: rid,ok: false,
task_present: null,install_dir_present: null,pipe_open: null,
interactive_session: null,helper_build: null};
if(process.platform!=='win32') return out;
try{
var versions=process.versions||{};
var date=new Date(versions.commitDate||versions.meshAgent);
if(!isNaN(date.getTime())) out.mesh_agent_version=date.toISOString();
}catch(e){}
var fs;
function sha256(data){ return require('SHA256Stream').create().syncHash(data).toString('hex'); }
try{ fs=require('fs'); }catch(e){ return out; }
function env(ns,fallback){
try{
for(var i=0; i<ns.length; i++){
var v=process.env[ns[i]];
if(typeof v==='string'&&v) return v;
}
}catch(e){}
return fallback;
}
function exists(path){
var v=fs.existsSync(path);
if(v===true||v===false) return v;
if(typeof v==='number') return v!==0;
throw new Error('existence unavailable');
}
var windows=env(['windir','SystemRoot','WINDIR','SYSTEMROOT'],'C:\\Windows');
var folder=env(['ProgramData','PROGRAMDATA','ALLUSERSPROFILE'],'C:\\ProgramData') + '\\Padiem';
var task='\\Tasks\\Padiem\\PadiemUserSessionHelper';
try{
out.task_present=exists(windows+'\\System32'+task) ||
exists(windows+'\\Sysnative'+task);
}catch(e){ out.task_present=null; }
try{ out.install_dir_present=exists(folder); }
catch(e){ out.install_dir_present=null; }
try{
var ns=fs.readdirSync('\\\\.\\pipe\\*');
if(Array.isArray(ns)&&ns.length>0){
var open=false;
for(var n=0; n<ns.length; n++){
if(typeof ns[n]==='string' &&
ns[n].toLowerCase().indexOf('padiem-user-helper-dev_') === 0){
open=true;
break;
}
}
out.pipe_open=open;
}
}catch(e){ out.pipe_open=null; }
try{
var sessions=require('user-sessions').Current();
var counted=0,active=false;
for(var id in sessions){
var session=sessions[id];
if(!session||typeof session.State!=='string') continue;
counted++;
if(session.State==='Active'&&Number(session.SessionId)!==0) active=true;
}
if(counted>0) out.interactive_session=active;
}catch(e){ out.interactive_session=null; }
try{
var record=folder+'\\helper-status.json';
out.helper_status_present=exists(record);
if(out.helper_status_present&&fs.statSync(record).size<=4096){
var text=fs.readFileSync(record).toString();
if(text.charCodeAt(0)===0xFEFF) text=text.substring(1);
var status=JSON.parse(text),sha=status&&status.sha256;
if(status&&status.status==='installed'&&typeof sha==='string' &&
/^[0-9a-fA-F]{64}$/.test(sha)){
out.helper_sha256=sha.toLowerCase();
out.helper_build=out.helper_sha256.substring(0,12);
try{
var installId=status.device_id;
if(typeof installId==='string'&&/^[0-9a-fA-F]{32}$|^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$/.test(installId))
out.helper_install_ref_sha256=sha256(Buffer.from(installId.toLowerCase()));
}catch(e){}
var ver=status.version,r=status.update_result,err=status.update_registration_error,target=status.update_target_sha256;
if(typeof ver==='string'&&/^[0-9][0-9A-Za-z._-]{0,63}$/.test(ver)) out.helper_version=ver;
if(typeof r==='string' &&
/^(current|pending|success|hash_mismatch|signature_mismatch|manifest_rejected|download_failed|deferred|rollback|registration_failed|available)$/.test(r)) out.update_result=r;
if(typeof target==='string'&&/^[0-9a-f]{64}$/.test(target)) out.update_target_sha256=target;
if(typeof status.auto_update==='boolean') out.auto_update=status.auto_update;
if(r==='registration_failed'&&typeof err==='string' &&
/^(updater_running|excluded_computer|missing_fixed_source|invalid_install_record|installed_digest_mismatch|task_registration_failed|task_registration_timeout|task_process_start_failed|version_unavailable)$/.test(err)) out.update_registration_error=err;
}
}
}catch(e){out.helper_build=null;}
try{
var up=folder+'HelperUpdater\\update.ps1',ut='\\Tasks\\Padiem\\PadiemUserHelperUpdater';
out.updater_task_present=exists(windows+'\\System32'+ut)||exists(windows+'\\Sysnative'+ut);
out.updater_source_present=exists(up);
if(out.updater_source_present&&fs.statSync(up).size<=131072)
out.updater_source_sha256=sha256(fs.readFileSync(up));
}catch(e){}
try{
var st='\\Tasks\\Padiem\\PadiemPcSelfHeal';
out.self_heal_task_present=exists(windows+'\\System32'+st)||exists(windows+'\\Sysnative'+st);
}catch(e){}
out.ok=true;
return out;
})(__PADIEM_REQUEST_ID__)
"""


def helper_ready_enabled(env: Any) -> bool:
    """Whether this deployment turned the observation on."""
    getter = getattr(env, "get", None)
    value = getter(HELPER_READY_SWITCH, "") if callable(getter) else ""
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "on"}


def _pc_suffix(node: str) -> str:
    # The full routing reference is used only on the authenticated wire.
    return re.sub(r"[^A-Za-z0-9_$@+.-]", "_", node.rsplit("/", 1)[-1][-6:])


def _targets(targets: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(node for node in targets
                              if isinstance(node, str) and node))


def _console_states(rows: Any, targets: list[str]) -> dict[str, dict[str, Any]]:
    states = {}
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or set(row) != {"device_id", "helper"}:
            continue
        node = row["device_id"]
        if not isinstance(node, str) or node not in targets or node in states:
            continue
        try:
            states[node] = validate_helper_ready(row["helper"])
        except HelperReadyError:
            print(f"oracle-mesh-executor helper_ready_console pc={_pc_suffix(node)} "
                  "read=failed reason=invalid_observation", flush=True)
    return states


class MeshHelperReadyReporter:
    """Submit one closed observation per PC per round, including repeats."""

    def __init__(self, *, post: Callable[[str, dict[str, Any]], tuple[int, Any]]) -> None:
        if not callable(post):
            raise ValueError("a channel post is required")
        self._post = post
        self._agent_version_diagnostics: dict[str, float] = {}

    def report(self, node: str, state: dict[str, Any], *, source: str,
               read: str, reason: str, attempts: int = 0) -> bool:
        status = "-"
        result = "rejected"
        try:
            state = validate_helper_ready(state)
            code, ack = self._post(HELPER_READY_PATH, {"device_id": node, "helper": state})
            if type(code) is int and 100 <= code <= 599:
                status = str(code)
            if code == 200 and isinstance(ack, dict) and ack.get("ok") is True:
                result = "accepted"
            elif code == 200:
                result = "invalid_ack"
        except HelperReadyError:
            result = "invalid_observation"
        except Exception:
            result = "post_error"
        print(f"oracle-mesh-executor helper_ready_node pc={_pc_suffix(node)} "
              f"source={source} attempts={attempts} read={read} reason={reason} "
              f"report={result} status={status}", flush=True)
        return result == "accepted"

    def observe(self, rows: Any, targets: Iterable[str]) -> int:
        try:
            nodes = _targets(targets)
            if not nodes:
                _agent_version_diagnostic(self._agent_version_diagnostics, "-", "not_target")
            states = _console_states(rows, nodes)
            reported = 0
            for node in nodes:
                _agent_version_diagnostic(
                    self._agent_version_diagnostics, _node_ref(node), "no_read_port")
                state = states.get(node)
                if state is None:
                    print(f"oracle-mesh-executor helper_ready_node pc={_pc_suffix(node)} "
                          "source=console attempts=0 read=unavailable reason=no_valid_reply "
                          "report=not_attempted status=-", flush=True)
                    continue
                reported += self.report(node, state, source="console", read="ok",
                                        reason=_state_reason(state))
            return reported
        except Exception:
            return 0


HELPER_STATUS_READ_PATH = "C:\\ProgramData\\Padiem\\helper-status.json"
_UPDATER_SOURCE_READ_PATH = r"C:\ProgramData\PadiemHelperUpdater\update.ps1"
_UPDATER_TASK_READ_PATH = r"C:\Windows\System32\Tasks\Padiem\PadiemUserHelperUpdater"
_WATCHER_TASK_READ_PATH = r"C:\Windows\System32\Tasks\Padiem\PadiemPcSelfHeal"
# #8204: the Mesh Agent's own executable carries its build date in the Windows
# version resource. The private read port already fetches fixed files from the
# same PC; this adds no command and no write. The installed agent's durable
# folder is the one the installer uses, with the historic x86 folder as a
# fallback. Only the bounded build timestamp travels up, never the binary.
_MESH_AGENT_VERSION_READ_PATHS = (
    r"C:\Program Files\PADIEM\MeshAgent.exe",
    r"C:\Program Files (x86)\PADIEM\MeshAgent.exe",
)
_MESH_AGENT_VERSION_READ_LIMIT = 8_000_000
_MESH_AGENT_VERSION_CACHE_SECONDS = 3600
_STATUS_SHA = re.compile(r"[0-9a-fA-F]{64}\Z")
_STATUS_VERSION = re.compile(r"[0-9][0-9A-Za-z._-]{0,63}\Z")
_VERSION_RESOURCE_KEY = "VS_VERSION_INFO".encode("utf-16-le") + b"\x00\x00"
_BUILD_STAMP = re.compile(
    r"(20[0-9]{2})-([A-Z][a-z]{2})-([0-9]{2}) "
    r"([0-9]{2}):([0-9]{2}):([0-9]{2})([+-])([0-9]{2})([0-9]{2})")
_MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def _state_reason(state: dict[str, Any]) -> str:
    if state.get("helper_status_present") is False:
        return "file_missing"
    if state.get("helper_sha256") and not state.get("helper_version"):
        return "version_unknown"
    if state.get("helper_status_present") is True and not state.get("helper_sha256"):
        return "release_unknown"
    return "observed"


_VERSION_REASON_PRECEDENCE = (
    "observed", "too_large", "permission_denied", "request_refused",
    "no_staged_read", "timeout", "port_refused", "local_file_not_found",
    "read_error", "invalid_read_body", "empty_body", "truncated_resource",
    "malformed_resource", "no_version_resource", "no_build_stamp",
    "ambiguous", "format_mismatch", "unavailable",
)


def _prefer_version_reason(reasons: list[str]) -> str:
    """Pick one stage code from two path attempts, most decisive first."""
    for code in _VERSION_REASON_PRECEDENCE:
        if code in reasons:
            return code
    return reasons[0] if reasons else "unavailable"


def _file_state(raw: Any) -> tuple[dict[str, Any], str]:
    # Reading a file proves its presence, not installation or readiness.
    state = dict.fromkeys(HELPER_READY_KEYS)
    state.update(install_dir_present=True, helper_status_present=True)
    try:
        text = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError, RecursionError):
        return state, "invalid_json"
    if not isinstance(text, dict) or text.get("status") != "installed":
        return state, "not_installed_record"
    sha, version = text.get("sha256"), text.get("version")
    if not isinstance(sha, str) or _STATUS_SHA.fullmatch(sha) is None:
        return state, "invalid_digest"
    state.update(helper_build=sha[:12].lower(), helper_sha256=sha.lower())
    install_id = text.get("device_id")
    if isinstance(install_id, str) and re.fullmatch(
            r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", install_id):
        state["helper_install_ref_sha256"] = hashlib.sha256(install_id.lower().encode("ascii")).hexdigest()
    # Older installed records have a digest but no version. The wire explicitly
    # permits this; retain the observed digest instead of discarding the PC.
    if isinstance(version, str) and _STATUS_VERSION.fullmatch(version):
        state["helper_version"] = version
    reason = "observed" if "helper_version" in state else "version_unknown"
    result = text.get("update_result")
    if isinstance(result, str) and result in HELPER_UPDATE_RESULTS:
        state["update_result"] = result
        error = text.get("update_registration_error")
        if result == "registration_failed" and isinstance(error, str) and error in REGISTRATION_ERRORS:
            state["update_registration_error"] = error
    target = text.get("update_target_sha256")
    if isinstance(target, str) and re.fullmatch(r"[0-9a-f]{64}", target):
        state["update_target_sha256"] = target
    if type(text.get("auto_update")) is bool:
        state["auto_update"] = text["auto_update"]
    return state, reason


def _read_failure(exc: Exception) -> str:
    # Never print exception text: the CLI may include paths, credentials or IDs.
    from .local_agent_meshcentral_private_reader import (
        MeshCentralReadRequestRefused, MeshCentralReadTooLarge, MeshCentralReadRefused,
    )
    if isinstance(exc, MeshCentralReadRequestRefused):
        return "request_refused"
    if isinstance(exc, MeshCentralReadTooLarge):
        return "too_large"
    if isinstance(exc, FileNotFoundError):
        return "local_file_not_found"
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, MeshCentralReadRefused):
        message = str(exc).lower()
        if "exceeded the read timeout" in message:
            return "timeout"
        if "wrote no staged read" in message:
            return "no_staged_read"
        if "access denied" in message or "permission denied" in message:
            return "permission_denied"
        return "port_refused"
    return "read_error"


#: Codes are deliberately value-free: no path, node reference, file content or
#: exception text may appear in the diagnostic line.
_VERSION_REASON_CODES = frozenset({
    "unavailable", "observed", "invalid_read_body", "empty_body", "too_large",
    "no_version_resource", "malformed_resource", "truncated_resource",
    "no_build_stamp", "ambiguous", "format_mismatch", "no_candidate_path",
    "no_read_port", "not_target", "console_path_only", "cached", "already_present",
})


def _node_ref(node: str) -> str:
    # The private read port accepts a bare ID, not a node/domain/id envelope.
    return node.rsplit("/", 1)[-1] if node.startswith("node/") else node


def _agent_version_diagnostic(store: dict[str, float], ref: str, reason: str,
                              now: float | None = None) -> None:
    """One value-free reason line per ref per one-hour cache unit."""
    if now is None:
        now = time.monotonic()
    last = store.get(ref)
    if last is not None and now - last < _MESH_AGENT_VERSION_CACHE_SECONDS:
        return
    store[ref] = now
    print(f"oracle-mesh-executor helper_ready_agent_version read={reason}", flush=True)


def _mesh_agent_version_reason(raw: Any) -> tuple[str | None, str]:
    """Return the bounded build timestamp and a code-only failure reason.

    Every ``None`` has a distinct stage code so an operator can tell a refused
    read from an oversized binary or a version resource that parsed to nothing,
    without any value leaving this module.
    """
    if not isinstance(raw, (bytes, bytearray)):
        return None, "invalid_read_body"
    data = bytes(raw)
    if not data:
        return None, "empty_body"
    if len(data) > _MESH_AGENT_VERSION_READ_LIMIT:
        return None, "too_large"
    marker = data.find(_VERSION_RESOURCE_KEY)
    if marker < 0:
        return None, "no_version_resource"
    # A VS_VERSIONINFO header is six bytes before the UTF-16 key. The key must
    # be even-aligned or the surrounding block is not UTF-16 text.
    if marker < 6 or marker % 2:
        return None, "malformed_resource"
    start = marker - 6
    length = struct.unpack_from("<H", data, start)[0]
    if length < 32 or start + length > len(data):
        return None, "truncated_resource"
    block = data[start:start + length].decode("utf-16-le", "ignore")
    stamps = {match.group(0) for match in _BUILD_STAMP.finditer(block)}
    if not stamps:
        return None, "no_build_stamp"
    if len(stamps) != 1:
        return None, "ambiguous"
    try:
        year, month, day, hour, minute, second, sign, offset_hour, offset_minute = \
            _BUILD_STAMP.fullmatch(stamps.pop()).groups()
        if month not in _MONTHS:
            return None, "format_mismatch"
        offset = timedelta(hours=int(offset_hour), minutes=int(offset_minute))
        if sign == "-":
            offset = -offset
        built = datetime(int(year), _MONTHS[month], int(day), int(hour), int(minute),
                         int(second), tzinfo=timezone(offset))
        utc = built.astimezone(timezone.utc)
    except (ValueError, TypeError, struct.error, OverflowError):
        return None, "format_mismatch"
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z", "observed"


def mesh_agent_version_from_executable(raw: Any) -> str | None:
    """Return the agent's bounded UTC build timestamp, or ``None``.

    The console reads ``process.versions.commitDate``; the same value is the
    ``FileVersion`` of the installed MeshAgent.exe (verified against the local
    installer). Only a single, strictly formatted build date inside a version
    resource is accepted. A path, identifier, arbitrary text, a truncated or
    oversized binary, and any parse failure produce ``None`` - never a value
    that could be shown to a user. No exception text leaves this function; the
    matching code-only reason is available from ``_mesh_agent_version_reason``.
    """
    return _mesh_agent_version_reason(raw)[0]


class HelperStatusReadFallback:
    """Use console evidence first, then the existing fixed-path private read.

    Every target gets one report attempt, even if both sources fail: in that
    case all facts are unknown. A missing or inaccessible file is not a claim
    that the PC is uninstalled. Never invent a version or forward file content.
    """

    def __init__(self, *, post: Any, read_port: Any,
                 reporter: MeshHelperReadyReporter | None = None) -> None:
        if not callable(post) or read_port is None:
            raise ValueError("a channel post and a private read port are required")
        self._reporter = reporter if reporter is not None else MeshHelperReadyReporter(post=post)
        self._read_port = read_port
        self._agent_versions: dict[str, tuple[str, float]] = {}
        self._agent_version_diagnostics: dict[str, float] = {}

    def _complete_mesh_agent_version(self, node: str, ref: str, state: dict[str, Any]) -> None:
        """Fill the one version the console never supplied, if the binary can prove it.

        Uses the same private read port as the status file. A PC without a
        helper-status record still owns its Mesh Agent, so this runs on both
        read-success and read-refusal paths. Cached per node because a bounded
        executable read is far too large to repeat on every drive round.
        """
        now = time.monotonic()
        if state.get("mesh_agent_version") is not None:
            _agent_version_diagnostic(
                self._agent_version_diagnostics, ref, "already_present", now)
            return
        cached = self._agent_versions.get(ref)
        if cached is not None and now - cached[1] < _MESH_AGENT_VERSION_CACHE_SECONDS:
            if cached[0] is not None:
                state["mesh_agent_version"] = cached[0]
            _agent_version_diagnostic(self._agent_version_diagnostics, ref, "cached", now)
            return
        value, reasons = None, []
        for path in _MESH_AGENT_VERSION_READ_PATHS:
            try:
                raw = self._read_port.read_bytes(
                    node_ref=ref, file_path=path, timeout_seconds=15,
                    max_bytes=_MESH_AGENT_VERSION_READ_LIMIT,
                )
            except Exception as exc:
                reasons.append(_read_failure(exc))
                continue
            value, reason = _mesh_agent_version_reason(raw)
            reasons.append(reason)
            if value is not None:
                break
        # The outcome, including a failure, is cached for the same hour as a
        # success, so the one-line diagnostic is emitted once per cache unit.
        self._agent_versions[ref] = (value, now)
        if value is not None:
            state["mesh_agent_version"] = value
        reason = _prefer_version_reason(reasons) if reasons else "no_candidate_path"
        _agent_version_diagnostic(self._agent_version_diagnostics, ref, reason, now)

    def _complete_updater_evidence(self, node, state):
        """Read only fixed files when the console lacks independent evidence.

        A refused read never proves absence. Report only source bytes' digest
        and positive task-file presence; never forward file content. The
        bounded independent reads run together rather than adding three
        serial timeouts to each PC's already time-sensitive observation.
        """
        if state.get("helper_status_present") is not True or not state.get("helper_sha256"):
            return
        probes = []
        if state.get("updater_source_present") is not False and not state.get("updater_source_sha256"):
            probes.append(("updater_source", _UPDATER_SOURCE_READ_PATH, 131072))
        if state.get("updater_task_present") is None:
            probes.append(("updater_task", _UPDATER_TASK_READ_PATH, 32768))
        if state.get("self_heal_task_present") is None:
            probes.append(("self_heal_task", _WATCHER_TASK_READ_PATH, 32768))
        if not probes:
            return
        ref = node.rsplit("/", 1)[-1] if node.startswith("node/") else node

        def read(probe):
            field, path, limit = probe
            # The Windows file transport may run in a 32-bit process and
            # redirect System32 to SysWOW64. Match the existing console's
            # two fixed task paths, with one total bounded read budget.
            paths = (path,) if field == "updater_source" else (
                path, path.replace(r"\System32\Tasks", r"\Sysnative\Tasks", 1))
            deadline = time.monotonic() + 15
            for attempt, candidate in enumerate(paths, 1):
                remaining = 15 if attempt == 1 else int(deadline - time.monotonic())
                if remaining < 1:
                    return field, None, "no_staged_read", attempt - 1
                try:
                    raw = self._read_port.read_bytes(
                        node_ref=ref, file_path=candidate,
                        timeout_seconds=remaining,
                        max_bytes=limit)
                    if not isinstance(raw, (bytes, bytearray)) or len(raw) > limit:
                        return field, None, "invalid_read_body", attempt
                    if field == "updater_source":
                        return field, hashlib.sha256(raw).hexdigest(), "observed", attempt
                    # An empty task file does not establish a usable task.
                    return (field, True, "observed", attempt) if raw else (
                        field, None, "empty_file", attempt)
                except Exception as exc:
                    reason = _read_failure(exc)
                    if (attempt < len(paths)
                            and reason in ("no_staged_read", "local_file_not_found")):
                        continue
                    # Missing/canceled/access denied is UNKNOWN, never false.
                    return field, None, reason, attempt

        try:
            with ThreadPoolExecutor(max_workers=len(probes)) as pool:
                for field, value, reason, attempts in pool.map(read, probes):
                    if value is not None:
                        if field == "updater_source":
                            state.update(updater_source_present=True, updater_source_sha256=value)
                        else:
                            state[field + "_present"] = value
                    print(f"oracle-mesh-executor helper_ready_probe field={field} "
                          f"reason={reason} attempts={attempts}", flush=True)
        except Exception:
            # The primary authenticated status report must still be delivered.
            print("oracle-mesh-executor helper_ready_probe reason=probe_unavailable", flush=True)

    def observe(self, rows: Any, targets: Any) -> int:
        reported = file_attempts = read_ok = console_ok = 0
        nodes = _targets(targets) if isinstance(targets, (list, tuple, set)) else []
        if not nodes:
            _agent_version_diagnostic(self._agent_version_diagnostics, "-", "not_target")
        states = _console_states(rows, nodes)
        for node in nodes:
            state = states.get(node)
            if state is not None and (state.get("helper_status_present") is False
                                      or state.get("helper_sha256")):
                console_ok += 1
                self._complete_updater_evidence(node, state)
                # The console path is not an excuse to skip the installed
                # executable: it cannot supply the Mesh build version. Use the
                # same private read port as the file path, then report.
                self._complete_mesh_agent_version(node, _node_ref(node), state)
                reported += self._reporter.report(
                    node, state, source="console", read="ok", reason=_state_reason(state))
                continue
            file_attempts += 1
            # Strip only the known node/ envelope, never a character inside
            # the opaque node identifier.
            refs = [_node_ref(node)]
            attempts = 0
            reason = "read_error"
            for ref in dict.fromkeys(refs):
                attempts += 1
                try:
                    raw = self._read_port.read_bytes(
                        node_ref=ref, file_path=HELPER_STATUS_READ_PATH,
                        timeout_seconds=15, max_bytes=8192,
                    )
                except Exception as exc:
                    reason = _read_failure(exc)
                    print(f"oracle-mesh-executor helper_ready_read pc={_pc_suffix(node)} "
                          f"attempt={attempts} read=failed reason={reason}", flush=True)
                    continue
                if not isinstance(raw, (bytes, bytearray)):
                    reason = "invalid_read_body"
                    print(f"oracle-mesh-executor helper_ready_read pc={_pc_suffix(node)} "
                          f"attempt={attempts} read=failed reason={reason}", flush=True)
                    continue
                read_ok += 1
                file_state, reason = _file_state(raw)
                if state is not None:
                    # Preserve independent console facts, not older release
                    # fields whose dependencies (digest, update result) may
                    # disagree with the freshly read file.
                    for key in ("task_present", "pipe_open", "interactive_session",
                                "mesh_agent_version", "updater_task_present",
                                "updater_source_present", "updater_source_sha256",
                                "self_heal_task_present"):
                        if key in state:
                            file_state[key] = state[key]
                self._complete_updater_evidence(node, file_state)
                self._complete_mesh_agent_version(node, ref, file_state)
                reported += self._reporter.report(
                    node, file_state, source="file", read="ok", reason=reason, attempts=attempts)
                break
            else:
                # A transport refusal/no staged file is ambiguous. Do not
                # mislabel it as absence or reuse stale success as fresh data.
                unknown = state if state is not None else dict.fromkeys(HELPER_READY_KEYS)
                self._complete_mesh_agent_version(node, refs[0], unknown)
                reported += self._reporter.report(
                    node, unknown, source="console" if state is not None else "file",
                    read="partial" if state is not None else "unavailable",
                    reason=reason, attempts=attempts)
        print(f"oracle-mesh-executor helper_ready_round targets={len(nodes)} "
              f"file_attempts={file_attempts} read_ok={read_ok} console_ok={console_ok} "
              f"reports={reported} report_failed={len(nodes) - reported}", flush=True)
        return reported


def attach_helper_ready(source: Any, env: Any, *, post: Any,
                        read_port: Any = None) -> MeshHelperReadyReporter | None:
    """Ride the drive round when the deployment asks for it; otherwise change nothing."""
    if not helper_ready_enabled(env):
        return None
    observe = getattr(source, "observe_helper_ready", None)
    if not callable(observe) or not callable(post):
        return None
    reporter = MeshHelperReadyReporter(post=post)
    if read_port is not None:
        fallback = HelperStatusReadFallback(
            post=post, read_port=read_port, reporter=reporter,
        )
        observer = fallback.observe
    else:
        observer = reporter.observe
    observe(observer, source=AGENT_HELPER_READY_JS,
            protocol=HELPER_READY_PROTOCOL, keys=sorted(HELPER_READY_KEYS | HELPER_READY_OPTIONAL_KEYS))
    return reporter


__all__ = [
    "AGENT_HELPER_READY_JS", "HELPER_READY_PATH",
    "HELPER_READY_PROTOCOL", "HELPER_READY_SWITCH",
    "MeshHelperReadyReporter", "attach_helper_ready", "helper_ready_enabled",
    "mesh_agent_version_from_executable",
]
