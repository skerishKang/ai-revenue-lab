@echo off
setlocal
rem COM1 SSH forward launcher.
rem
rem Lifetime contract: the caller MUST wait for this script (background-tunnel.vbs
rem passes bWaitOnReturn=True) so that the scheduled task instance lives exactly
rem as long as the ssh process. Only then can Task Scheduler
rem MultipleInstances=IgnoreNew prevent a duplicate forward, RestartCount retry a
rem failed forward, and LastTaskResult carry the ssh exit code.
rem
rem Earlier versions returned immediately from wscript, so the task finished in
rem well under a second while ssh kept running. IgnoreNew, RestartCount and
rem LastTaskResult were therefore inert, and a dead forward stayed invisible
rem until the next 5 minute health check.
set "BASE=%~dp0"
if not defined PADIEM_TUNNEL_LOG set "PADIEM_TUNNEL_LOG=%BASE%padiem-tunnel.log"
set "LOG=%PADIEM_TUNNEL_LOG%"
set "LOCK=%BASE%padiem-tunnel.lock.d"

rem Secondary single-instance guard. The scheduler task is the primary guard;
rem this covers a manual start, or a start that races the scheduler, which would
rem otherwise leave two competing forwards on the same loopback port.
if exist "%LOCK%" (
  echo %DATE% %TIME% TUNNEL SKIP rc=already-running >> "%LOG%"
  exit /b 3
)
mkdir "%LOCK%" 2>nul
if errorlevel 1 (
  echo %DATE% %TIME% TUNNEL SKIP rc=already-running >> "%LOG%"
  exit /b 3
)

echo %DATE% %TIME% TUNNEL START >> "%LOG%"
call "%BASE%padiem-tunnel.cmd"
set "RC=%ERRORLEVEL%"
rmdir "%LOCK%" 2>nul
echo %DATE% %TIME% TUNNEL EXIT=%RC% >> "%LOG%"
endlocal & exit /b %RC%
