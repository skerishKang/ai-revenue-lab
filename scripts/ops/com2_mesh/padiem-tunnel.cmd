@echo off
setlocal
rem COM1 SSH forward worker. The wrapper calls this file and forwards the exit
rem code to Task Scheduler, so this file must return the real ssh exit code.
rem
rem Note: %ERRORLEVEL% inside a parenthesised block is expanded when the block is
rem parsed, not when it runs. The branches below therefore use labels, and the
rem ssh launch uses `call` so a .cmd/.exe stand-in both return control here.
set "BASE=%~dp0"
if not defined PADIEM_SSH_EXE set "PADIEM_SSH_EXE=G:\Program Files\Git\usr\bin\ssh.exe"
if not defined PADIEM_SSH_KEY set "PADIEM_SSH_KEY=C:/Users/limone/.ssh/id_rsa"
set "SSH=%PADIEM_SSH_EXE%"
set "TARGET_FILE=%BASE%padiem-tunnel-target.txt"
if not exist "%TARGET_FILE%" exit /b 2
set /p TARGET=<"%TARGET_FILE%"
if /i "%TARGET%"=="comp2" goto comp2
if /i "%TARGET%"=="oracle" goto oracle
exit /b 2

:comp2
call "%SSH%" -N -T -i %PADIEM_SSH_KEY% -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -L 127.0.0.1:4443:127.0.0.1:4443 user@192.168.0.101
exit /b %ERRORLEVEL%

:oracle
call "%SSH%" -F none -N -T -i C:/Users/limone/.ssh-oracle-only/id_oracle -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -L 127.0.0.1:4443:127.0.0.1:4443 ubuntu@168.138.200.12
exit /b %ERRORLEVEL%
