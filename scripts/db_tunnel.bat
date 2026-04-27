@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM SSH tunnel manager for local development (background mode).
REM Usage:
REM   scripts\db_tunnel.bat up
REM   scripts\db_tunnel.bat down
REM   scripts\db_tunnel.bat restart
REM   scripts\db_tunnel.bat status
REM   scripts\db_tunnel.bat test

set "SSH_ALIAS=ali99"
set "LOCAL_PORT=3307"
set "REMOTE_HOST=127.0.0.1"
set "REMOTE_PORT=3306"

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=up"

if /I "%ACTION%"=="up" goto :up
if /I "%ACTION%"=="down" goto :down
if /I "%ACTION%"=="restart" goto :restart
if /I "%ACTION%"=="status" goto :status
if /I "%ACTION%"=="test" goto :test

echo [ERROR] Unknown action: %ACTION%
echo.
echo Usage: scripts\db_tunnel.bat [up^|down^|restart^|status^|test]
exit /b 1

:up
call :is_listening_stable
if %errorlevel%==0 goto :already_up

where ssh >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] ssh not found. Install OpenSSH client first.
    exit /b 1
)
echo [INFO] Starting tunnel...
echo [INFO] Local: 127.0.0.1:%LOCAL_PORT%  ->  Remote: %REMOTE_HOST%:%REMOTE_PORT%
echo [INFO] SSH Alias: %SSH_ALIAS%
echo [INFO] Keep this window open while developing. Press Ctrl+C to stop.
echo [INFO] After connected, use: mysql -h127.0.0.1 -P%LOCAL_PORT% -uqinrs -p
echo.
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -N -L %LOCAL_PORT%:%REMOTE_HOST%:%REMOTE_PORT% %SSH_ALIAS%
exit /b %errorlevel%

:already_up
echo [OK] Tunnel already running on 127.0.0.1:%LOCAL_PORT%
exit /b 0

:down
set "FOUND=0"
for /f %%P in ('powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort %LOCAL_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach($id in $p){Write-Output $id}"') do (
    taskkill /PID %%P /F >nul 2>&1
    set "FOUND=1"
)
if "!FOUND!"=="1" (
    echo [OK] Port %LOCAL_PORT% has been released.
) else (
    echo [INFO] No tunnel process found for port %LOCAL_PORT%.
)
exit /b 0

:restart
call :down
call :up
exit /b %errorlevel%

:status
call :is_listening_stable
if %errorlevel%==0 (
    echo [OK] Tunnel status: RUNNING
    echo [OK] Local endpoint: 127.0.0.1:%LOCAL_PORT%
    echo [INFO] SSH alias: %SSH_ALIAS%
    exit /b 0
)
echo [INFO] Tunnel status: STOPPED
echo [INFO] Expected endpoint: 127.0.0.1:%LOCAL_PORT%
exit /b 1

:test
call :is_listening_stable
if %errorlevel%==0 (
    echo [OK] Tunnel test passed: 127.0.0.1:%LOCAL_PORT% is reachable
    exit /b 0
)
echo [ERROR] Tunnel test failed: 127.0.0.1:%LOCAL_PORT% is not reachable
echo [INFO] Try: scripts\db_tunnel.bat up
exit /b 1

:is_listening
powershell -NoProfile -Command "$r=Test-NetConnection 127.0.0.1 -Port %LOCAL_PORT% -WarningAction SilentlyContinue; if ($r.TcpTestSucceeded) { exit 0 } else { exit 1 }"
exit /b %errorlevel%

:is_listening_stable
call :is_listening
if %errorlevel% neq 0 exit /b 1
timeout /t 1 /nobreak >nul
call :is_listening
exit /b %errorlevel%
