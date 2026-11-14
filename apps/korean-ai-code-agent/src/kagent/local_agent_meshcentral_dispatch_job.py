"""#7646 — the process tree a PC command creates, named so it can always be ended.

A queued PC command is one PowerShell console the agent started. The command body may
start children of its own, and those children may start children. Two things went wrong
before this module:

* the owner's stop ended the *recorded* pid with ``taskkill /T``. ``/T`` walks the parent
  chain from that pid, so it reaches a descendant only while the chain is intact. A
  command whose own wrapper had already exited left its children reparented to nothing,
  and no later sweep could find them from the recorded number;
* a user-session command's stop ended through the helper's pipe instead, so the
  executor's own tree end was never asked for at all.

The fix is one Windows primitive used as an identity, not as a second kill path: the
command's wrapper creates a **named Job Object** with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``
and assigns itself to it before it runs the body. Every descendant it starts is a member
of that job by inheritance, whatever happens to the parent chain afterwards. The job is
destroyed when its last handle closes, and that destruction ends every member — so:

* the wrapper exiting normally, being killed, or crashing all end the tree it started;
* a stop can end the tree by opening the job **by name** and terminating it, which needs
  no parent chain and no live pid at all;
* a sweep can do the same for a command whose wrapper is long gone, which is exactly the
  reparented-grandchild case this issue is about.

The name is derived from the dispatch id, which is already the identity every other part
of this lane uses (marker file, staged script, envelope tag). A name is therefore never
guessed from a process name, a window title or output text, and a job this lane did not
create cannot be addressed by accident: a command that never created one simply has no
job, ``OpenJobObjectW`` fails, and the caller keeps the behaviour it had before.

Backward compatibility is a consequence of that, not a special case: markers written
before this change name no job, so the stop and the sweep fall through to the recorded
pid exactly as they always did.

One measured detail decides how the limit is set. ``JOBOBJECT_EXTENDED_LIMIT_INFORMATION``
is 144 bytes on x64 and ``LimitFlags`` is a DWORD at offset 16 (after the two
``LARGE_INTEGER`` time limits). Building that structure as a PowerShell object and
marshalling it with ``StructureToPtr`` does **not** carry the nested value: the call
succeeds, ``QueryInformationJobObject`` reads the flags back as 0, and the job ends
nothing. Measured here on 2026-11-15 — a child in such a job survived its parent's death.
The buffer is therefore written field by field, and the module's own test reads the flags
back from the kernel to prove the limit is really on.
"""
from __future__ import annotations

import re

from .contracts import ContractError

#: The job's own name prefix. The dispatch id follows it, so one dispatch has exactly one
#: job and the name is as unique as the dispatch id already is.
DISPATCH_JOB_PREFIX = "padiem-dispatch-job-"

#: A job name is a kernel object name, not a path: it may not carry a separator, and the
#: whole name is bounded so a malformed caller cannot stretch a PowerShell literal.
_JOB_NAME = re.compile(r"padiem-dispatch-job-[A-Za-z0-9_.-]{1,96}\Z")

#: The dispatch id grammar this lane already enforces. Repeated here as the only thing
#: that may reach a job name, so this module is safe to call on its own.
_DISPATCH_ID = re.compile(r"dsp_[0-9a-f]{16,64}\Z")

#: ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``: closing the last handle ends every member.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
#: ``JobObjectExtendedLimitInformation``.
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
#: The x64 size of ``JOBOBJECT_EXTENDED_LIMIT_INFORMATION``: 2 * 8 (time limits) + 4
#: (LimitFlags) + 4 (padding) + 4 * 8 (working set) + 4 (ActiveProcessLimit) + 4 (padding)
#: + 8 (Affinity) + 4 + 4 (PriorityClass, SchedulingClass) + 6 * 8 (I/O counters) + 4 * 8
#: (memory limits). The kernel validates this length, so it is a fact, not a guess.
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_SIZE = 144
#: ``LimitFlags`` inside that structure: after the two 8-byte time limits.
JOB_OBJECT_LIMIT_FLAGS_OFFSET = 16
#: ``JOB_OBJECT_TERMINATE | JOB_OBJECT_QUERY`` plus the standard rights a stop needs to
#: open a job it did not create. Deliberately not ``JOB_OBJECT_ALL_ACCESS``: a stop only
#: terminates and reads, and asking for less is what keeps this from being a general
#: handle on another process's container.
JOB_OBJECT_TERMINATE_ACCESS = 0x0001 | 0x0004 | 0x0008 | 0x00100000


def checked_dispatch_id(dispatch_id: str) -> str:
    """The dispatch id, or a refusal. Never a caller-supplied string in a literal."""
    if not isinstance(dispatch_id, str) or _DISPATCH_ID.fullmatch(dispatch_id) is None:
        raise ContractError("the dispatch id is not one this lane issues")
    return dispatch_id


def job_name(dispatch_id: str) -> str:
    """The one job name this dispatch's command creates, and that a stop addresses."""
    name = DISPATCH_JOB_PREFIX + checked_dispatch_id(dispatch_id)
    if _JOB_NAME.fullmatch(name) is None:
        raise ContractError("the dispatch job name is not a kernel object name")
    return name


def checked_job_name(name: str) -> str:
    """A job name read back from the PC, accepted only on this module's own grammar."""
    if not isinstance(name, str) or _JOB_NAME.fullmatch(name) is None:
        raise ContractError("the job name is not one this lane creates")
    return name


def job_name_of(name: str) -> str | None:
    """The dispatch id a job name carries, or ``None`` when it carries none."""
    if not isinstance(name, str) or not name.startswith(DISPATCH_JOB_PREFIX):
        return None
    tail = name[len(DISPATCH_JOB_PREFIX):]
    return tail if _DISPATCH_ID.fullmatch(tail) is not None else None


#: The declarations the *command* needs: create a job, set kill-on-close, assign itself.
#: ``CharSet.Unicode`` is what makes ``CreateJobObjectW``/``OpenJobObjectW`` bind to the
#: wide entry points rather than the ANSI ones, so a name is never narrowed through a
#: code page (the same reason every reply in this lane is Base64 of UTF-8).
DISPATCH_JOB_DECLARATIONS_PS = (
    "[DllImport(\"kernel32.dll\",SetLastError=true,CharSet=CharSet.Unicode)]"
    " public static extern IntPtr CreateJobObjectW(IntPtr a,string n);"
    "[DllImport(\"kernel32.dll\",SetLastError=true)]"
    " public static extern bool SetInformationJobObject(IntPtr j,int c,IntPtr b,uint l);"
    "[DllImport(\"kernel32.dll\",SetLastError=true)]"
    " public static extern bool AssignProcessToJobObject(IntPtr j,IntPtr p);"
    "[DllImport(\"kernel32.dll\",SetLastError=true)]"
    " public static extern bool CloseHandle(IntPtr h);"
)

#: The type name the declarations compile to. One namespace, so a command that already
#: compiled it in this PowerShell session reuses it instead of compiling twice.
DISPATCH_JOB_TYPE = "PadiemDispatch7646.Job"


def dispatch_job_create_ps(dispatch_id: str) -> str:
    """The statements that put this command's wrapper inside its own kill-on-close job.

    Run *before* the body, so every process the body starts is a member by inheritance.
    A failure here never refuses the command: the job is how a stop reaches descendants,
    and a PC that cannot create one is still a PC whose command must run. The variable
    ``$__padiem_job`` is left zero on failure and the caller carries on.

    ``Add-Type`` compiles once per PowerShell session (measured 340-650 ms cold, ~12 ms
    warm), which is why the type is named and reused rather than emitted per statement.

    The handle stays in ``$__padiem_job`` for the life of this wrapper. That is what
    makes the containment hold: when the wrapper ends - normally, by a stop, or by a
    crash - the last handle closes, the job is destroyed, and every member with it.
    """
    name = job_name(dispatch_id)
    size = str(JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_SIZE)
    offset = str(JOB_OBJECT_LIMIT_FLAGS_OFFSET)
    return (
        "$__padiem_job=[IntPtr]::Zero;"
        "try{"
        "if(-not ('" + DISPATCH_JOB_TYPE + "' -as [type])){"
        "Add-Type -Namespace PadiemDispatch7646 -Name Job -MemberDefinition '"
        + DISPATCH_JOB_DECLARATIONS_PS.replace("'", "''") + "'|Out-Null};"
        "$__padiem_jh=[" + DISPATCH_JOB_TYPE + "]::CreateJobObjectW([IntPtr]::Zero,'"
        + name + "');"
        "if($__padiem_jh -and $__padiem_jh -ne [IntPtr]::Zero){"
        # The buffer is written field by field on purpose: a marshalled PowerShell
        # object does not carry the nested LimitFlags, and the limit then silently
        # reads back as 0 (measured 2026-11-15).
        "$__padiem_buf=[Runtime.InteropServices.Marshal]::AllocHGlobal(" + size + ");"
        "try{"
        "for($__padiem_i=0;$__padiem_i -lt " + size + ";$__padiem_i++){"
        "[Runtime.InteropServices.Marshal]::WriteByte($__padiem_buf,$__padiem_i,0)};"
        "[Runtime.InteropServices.Marshal]::WriteInt32($__padiem_buf," + offset + ","
        + str(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) + ");"
        "$__padiem_ok=[" + DISPATCH_JOB_TYPE + "]::SetInformationJobObject("
        "$__padiem_jh," + str(JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS)
        + ",$__padiem_buf," + size + ")"
        "}finally{[Runtime.InteropServices.Marshal]::FreeHGlobal($__padiem_buf)};"
        "if($__padiem_ok){"
        "$__padiem_me=Get-Process -Id $PID;"
        "if([" + DISPATCH_JOB_TYPE + "]::AssignProcessToJobObject("
        "$__padiem_jh,$__padiem_me.Handle)){$__padiem_job=$__padiem_jh}"
        "}"
        "}"
        "}catch{$__padiem_job=[IntPtr]::Zero};"
    )


#: The declarations a *stop* needs, and only those: open a job by name, end it, close it.
#: A stop never creates a job and never sets a limit, so it does not carry the calls that
#: would let it. That is also what keeps the stop script inside the terminal lane's
#: prequeue budget, which is the bound every script on that channel obeys.
DISPATCH_JOB_STOP_DECLARATIONS_PS = (
    "[DllImport(\"kernel32.dll\",CharSet=CharSet.Unicode)]"
    " public static extern IntPtr OpenJobObjectW(uint a,bool i,string n);"
    "[DllImport(\"kernel32.dll\")]"
    " public static extern bool TerminateJobObject(IntPtr j,uint c);"
    "[DllImport(\"kernel32.dll\")]"
    " public static extern bool CloseHandle(IntPtr h);"
)

DISPATCH_JOB_STOP_TYPE = "P7646.S"


def dispatch_job_stop_ps(dispatch_id: str) -> str:
    """The statements that end this dispatch's job, if it has one.

    Addresses the job by the name derived from the dispatch id and nothing else, so it
    cannot reach a job this lane did not create. ``$__padiem_jobended`` is ``$true`` only
    when the kernel accepted the termination; a dispatch whose command never created a
    job (every command from before this change) leaves it ``$false`` and the caller keeps
    the recorded-pid behaviour it had.
    """
    name = job_name(dispatch_id)
    return (
        "$__padiem_jobended=$false;"
        "try{"
        "if(-not ('" + DISPATCH_JOB_STOP_TYPE + "' -as [type])){"
        "Add-Type -Namespace P7646 -Name S -MemberDefinition '"
        + DISPATCH_JOB_STOP_DECLARATIONS_PS.replace("'", "''") + "'|Out-Null};"
        "$__padiem_jh=[" + DISPATCH_JOB_STOP_TYPE + "]::OpenJobObjectW("
        + str(JOB_OBJECT_TERMINATE_ACCESS) + ",$false,'" + name + "');"
        "if($__padiem_jh -and $__padiem_jh -ne [IntPtr]::Zero){"
        "try{$__padiem_jobended=[" + DISPATCH_JOB_STOP_TYPE + "]::TerminateJobObject("
        "$__padiem_jh,1)}"
        "finally{[" + DISPATCH_JOB_STOP_TYPE + "]::CloseHandle($__padiem_jh)|Out-Null}"
        "}"
        "}catch{$__padiem_jobended=$false};"
    )
