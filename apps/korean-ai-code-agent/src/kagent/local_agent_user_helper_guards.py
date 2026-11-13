"""User-helper runtime constants the executor and its Windows scripts share.

Extracted from ``local_agent_oracle_mesh_executor`` so that file stays under its
size cap (#7216): these are the task registration, pipe name and the two
PowerShell guards the SYSTEM-side client runs before it trusts a pipe.
"""
from __future__ import annotations

USER_SESSION_UNAVAILABLE = "user_session_unavailable"
USER_HELPER_PIPE_PREFIX = "padiem-user-helper-"
#: #7182b: ``Get-ScheduledTask -TaskPath`` matches the folder's own path exactly,
#: trailing separator included. The installer registers the task under
#: ``\\Padiem\\`` (``claw_connect.user_helper_registration.TASK_FOLDER``), so a
#: path without the separator selects nothing and the client stopped at its very
#: first step with "helper task is not registered" - before any pipe connect.
#: Measured on 컴1 2026-11-08: the deployed client returned that message in 1s
#: while the task was Running, and the same script with ``\\Padiem\\`` returned
#: the command's output in 1.6s.
USER_HELPER_TASK_PATH = "\\Padiem\\"
USER_HELPER_TASK_NAME = "PadiemUserSessionHelper"
#: #7564: the folder the installer is allowed to point the helper secret at. The
#: scheduled task's ``--secret-file`` argument travels into a path the SYSTEM
#: client reads, so the client reads it only when it resolves inside this one
#: folder. The file's owner is deliberately NOT checked here: on the PCs already
#: installed the file may be owned by the account that ran the installer, and a
#: check on it would refuse machines that are set up correctly.
USER_HELPER_SECRET_FOLDER = "Padiem"
#: #7564: the OS check the SYSTEM pipe client runs before its first write. The
#: pipe namespace is machine-global, so the process answering a connect is
#: whatever instance listened first, not necessarily the session helper; the
#: client therefore asks the OS which process owns the server side of its own
#: connection (``GetNamedPipeServerProcessId``) and compares that process's
#: token session and user with the machine's active console session and its
#: user (``WTSGetActiveConsoleSessionId`` + ``WTSQueryUserToken``). Anything the
#: far end reports about itself is never evidence. The expected identity is a
#: parameter, so a test can demand an impossible one and walk the refusal path
#: against a real pipe.
USER_HELPER_PIPE_GUARD_PS = r"""
try{
  Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public static class PadiemPipeGuard{[DllImport("kernel32.dll",SetLastError=true)]public static extern bool GetNamedPipeServerProcessId(IntPtr pipe,out uint serverProcessId);[DllImport("kernel32.dll")]public static extern uint WTSGetActiveConsoleSessionId();[DllImport("wtsapi32.dll",SetLastError=true)]public static extern bool WTSQueryUserToken(uint sessionId,out IntPtr token);[DllImport("kernel32.dll",SetLastError=true)]public static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);[DllImport("advapi32.dll",SetLastError=true)]public static extern bool OpenProcessToken(IntPtr process,uint desiredAccess,out IntPtr token);[DllImport("advapi32.dll",SetLastError=true)]public static extern bool GetTokenInformation(IntPtr TokenHandle,int TokenInformationClass,IntPtr TokenInformation,uint TokenInformationLength,out uint ReturnLength);[DllImport("kernel32.dll")]public static extern bool CloseHandle(IntPtr h);public static string TokenUserSid(IntPtr token){IntPtr buf=Marshal.AllocHGlobal(72);try{uint ret;if(!GetTokenInformation(token,1,buf,72,out ret)){return "";}IntPtr sid=Marshal.ReadIntPtr(buf);return sid==IntPtr.Zero?"":new System.Security.Principal.SecurityIdentifier(sid).Value;}finally{Marshal.FreeHGlobal(buf);}}public static uint TokenSessionId(IntPtr token){IntPtr b2=Marshal.AllocHGlobal(8);try{uint ret;if(!GetTokenInformation(token,12,b2,4,out ret)){return 4294967295u;}return (uint)Marshal.ReadInt32(b2);}finally{Marshal.FreeHGlobal(b2);}}}'
}catch{}
function __PadiemPipeServerOk($client,$expSession,$expUser){
  $__p=[uint32]0
  try{ if(-not [PadiemPipeGuard]::GetNamedPipeServerProcessId($client.SafePipeHandle.DangerousGetHandle(),[ref]$__p)){ return $false } }catch{ return $false }
  $__ph=[IntPtr]::Zero
  try{
    $__ph=[PadiemPipeGuard]::OpenProcess(4096,0,$__p)
    if($__ph -eq [IntPtr]::Zero){ return $false }
    $__th=[IntPtr]::Zero
    if(-not [PadiemPipeGuard]::OpenProcessToken($__ph,8,[ref]$__th)){ return $false }
    try{
      if($expSession -ge 0){
        $__ss=[PadiemPipeGuard]::TokenSessionId($__th)
        if($__ss -eq 4294967295 -or $__ss -ne $expSession){ return $false }
      }
      if($expUser){
        $__u=[PadiemPipeGuard]::TokenUserSid($__th)
        if(-not $__u -or $__u -ne $expUser){ return $false }
      }
      return $true
    }finally{ [void][PadiemPipeGuard]::CloseHandle($__th) }
  }catch{ return $false }
  finally{ if($__ph -ne [IntPtr]::Zero){ [void][PadiemPipeGuard]::CloseHandle($__ph) } }
}
function __PadiemConsoleIdentity(){
  $__s=-1;$__u=''
  try{
    $__s=[int][PadiemPipeGuard]::WTSGetActiveConsoleSessionId()
    $__ct=[IntPtr]::Zero
    if([PadiemPipeGuard]::WTSQueryUserToken($__s,[ref]$__ct)){ $__u=[PadiemPipeGuard]::TokenUserSid($__ct); [void][PadiemPipeGuard]::CloseHandle($__ct) }
  }catch{}
  return @($__s,$__u)
}""".strip()
#: The secret-path guard as its own function text, so the boundary it enforces
#: is testable against real PowerShell without touching the installed folder.
#: The expected root is a parameter; the generated client binds it to the
#: installer's folder at the call site below, and only there.
USER_HELPER_SECRET_PATH_GUARD_PS = (
    "function __PadiemSecretPathOk($p,$root){"
    "try{"
    "$__root=[IO.Path]::GetFullPath($root+'\\');"
    "$__full=[IO.Path]::GetFullPath($p);"
    "return $__full.StartsWith($__root,[StringComparison]::OrdinalIgnoreCase)"
    "}catch{ return $false } }"
)
