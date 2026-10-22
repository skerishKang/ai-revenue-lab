Option Explicit
' COM1 SSH forward launcher.
Dim sh, fso, dir, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = """" & dir & "\padiem-tunnel-wrapper.cmd"""
' bWaitOnReturn MUST stay True. The task instance then lives exactly as long as
' the ssh forward, so MultipleInstances=IgnoreNew and RestartCount in Task
' Scheduler actually apply, and LastTaskResult carries the ssh exit code.
sh.Run cmd, 0, True
