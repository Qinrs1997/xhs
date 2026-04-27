@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM ###############################################################################
REM FastAPI Dev Server Startup Script (Windows)
REM
REM Features:
REM 1. Auto-detect and activate virtual environment (Conda or venv)
REM 2. Load config from config/settings.toml
REM 3. Start dev server with uvicorn
REM
REM Note: All settings are managed in config/settings.toml
REM ###############################################################################

REM Default Conda environment name (overridable: set DEFAULT_CONDA_ENV=xxx before running)
if not defined DEFAULT_CONDA_ENV set "DEFAULT_CONDA_ENV=fastapi_env"

REM Switch to project root directory
cd /d "%~dp0\.."

echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   FastAPI Dev Server (Windows)
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REM ============================================================================
REM 1. Detect and activate virtual environment
REM ============================================================================

echo [INFO] Detecting virtual environment...

REM Check if already in a Conda environment (not base)
if defined CONDA_DEFAULT_ENV (
    if not "%CONDA_DEFAULT_ENV%"=="base" (
        echo [OK] Already in Conda env: %CONDA_DEFAULT_ENV%
        goto :env_ready
    )
)

REM Check if already in venv
if defined VIRTUAL_ENV (
    echo [OK] Already in venv: %VIRTUAL_ENV%
    goto :env_ready
)

REM Try to find and activate Conda environment by resolving its path
set "CONDA_ENV_PATH="

REM Method 1: Use 'conda info --envs' to find the env path
where conda >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%L in ('conda env list 2^>nul ^| findstr /B "%DEFAULT_CONDA_ENV% "') do (
        for %%P in (%%L) do set "CONDA_ENV_PATH=%%P"
    )
)

REM Method 2: Check common conda env locations
if not defined CONDA_ENV_PATH (
    if exist "%USERPROFILE%\.conda\envs\%DEFAULT_CONDA_ENV%\python.exe" (
        set "CONDA_ENV_PATH=%USERPROFILE%\.conda\envs\%DEFAULT_CONDA_ENV%"
    )
)
if not defined CONDA_ENV_PATH (
    if exist "E:\miniconda\envs\%DEFAULT_CONDA_ENV%\python.exe" (
        set "CONDA_ENV_PATH=E:\miniconda\envs\%DEFAULT_CONDA_ENV%"
    )
)
if not defined CONDA_ENV_PATH (
    if exist "%USERPROFILE%\anaconda3\envs\%DEFAULT_CONDA_ENV%\python.exe" (
        set "CONDA_ENV_PATH=%USERPROFILE%\anaconda3\envs\%DEFAULT_CONDA_ENV%"
    )
)
if not defined CONDA_ENV_PATH (
    if exist "%USERPROFILE%\miniconda3\envs\%DEFAULT_CONDA_ENV%\python.exe" (
        set "CONDA_ENV_PATH=%USERPROFILE%\miniconda3\envs\%DEFAULT_CONDA_ENV%"
    )
)
if not defined CONDA_ENV_PATH (
    if exist "C:\ProgramData\miniconda3\envs\%DEFAULT_CONDA_ENV%\python.exe" (
        set "CONDA_ENV_PATH=C:\ProgramData\miniconda3\envs\%DEFAULT_CONDA_ENV%"
    )
)
if not defined CONDA_ENV_PATH (
    if exist "C:\ProgramData\Anaconda3\envs\%DEFAULT_CONDA_ENV%\python.exe" (
        set "CONDA_ENV_PATH=C:\ProgramData\Anaconda3\envs\%DEFAULT_CONDA_ENV%"
    )
)

REM If Conda env path found, inject it into PATH directly
if defined CONDA_ENV_PATH (
    echo [INFO] Found Conda env: %CONDA_ENV_PATH%
    set "PATH=%CONDA_ENV_PATH%;%CONDA_ENV_PATH%\Scripts;%CONDA_ENV_PATH%\Library\bin;%PATH%"
    echo [OK] Conda env PATH configured
    goto :env_ready
)

REM Try to activate venv
if exist "venv\Scripts\activate.bat" (
    echo [INFO] Activating venv...
    call venv\Scripts\activate.bat
    echo [OK] venv activated
    goto :env_ready
)

REM Try to activate .venv
if exist ".venv\Scripts\activate.bat" (
    echo [INFO] Activating .venv...
    call .venv\Scripts\activate.bat
    echo [OK] .venv activated
    goto :env_ready
)

echo [FAIL] No virtual environment detected!
echo.
echo Please create one first:
echo   conda create -n %DEFAULT_CONDA_ENV% python=3.10 -y
echo   or: python -m venv venv
exit /b 1

:env_ready

REM ============================================================================
REM 2. Check dependencies
REM ============================================================================

echo [INFO] Checking dependencies...

python -c "import uvicorn" >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] uvicorn not installed!
    echo.
    echo Please install dependencies:
    echo   pip install -r requirements.txt
    exit /b 1
)

python -c "import pydantic, sqlalchemy, alembic" >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Missing critical Python dependencies!
    echo.
    echo Please install dependencies:
    echo   pip install -r requirements.txt
    exit /b 1
)

echo [OK] Dependencies check passed

REM ============================================================================
REM 3. Check config file
REM ============================================================================

echo [INFO] Checking config file...

if not exist "config\settings.toml" (
    echo [FAIL] Config file config\settings.toml not found!
    exit /b 1
)

echo [OK] Config file check passed

REM ============================================================================
REM 4. Load config
REM ============================================================================

echo [INFO] Loading config...

REM Set PYTHONPATH
set "PYTHONPATH=%cd%;%PYTHONPATH%"

REM Read config via Python
for /f "tokens=1,* delims==" %%a in ('python -c "import sys; sys.path.insert(0, '.'); from app.core.config import settings; print(f'APP_HOST={settings.APP_HOST}'); print(f'APP_PORT={settings.APP_PORT}'); print(f'APP_WORKERS={settings.APP_WORKERS}'); print(f'DEBUG={settings.DEBUG}'); print(f'DOCS_URL={settings.DOCS_URL}'); print(f'PROJECT_NAME={settings.PROJECT_NAME}'); print(f'APP_ENV={settings.APP_ENV}')" 2^>nul') do (
    set "%%a=%%b"
)

if not defined APP_PORT (
    echo [FAIL] Config loading failed!
    echo Please check app/core/config.py or config/settings.toml
    exit /b 1
)

echo [OK] Config loaded

REM ============================================================================
REM 5. Database migration (handled automatically by init_db at startup)
REM ============================================================================

echo [INFO] Checking alembic availability...

python -c "import alembic" >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] alembic not installed!
    echo.
    echo Please install dependencies:
    echo   pip install -r requirements.txt
    exit /b 1
)

echo [OK] Alembic available (auto-migration runs at app startup)

REM ============================================================================
REM 6. Check port
REM ============================================================================

echo [INFO] Checking port %APP_PORT% ...

netstat -ano | findstr ":%APP_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [WARN] Port %APP_PORT% is in use, killing occupying process...
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%APP_PORT% " ^| findstr "LISTENING"') do (
        if not "%%P"=="0" (
            echo [INFO] Killing PID: %%P
            taskkill /F /PID %%P >nul 2>&1
        )
    )
    REM 同时清理残留的 uvicorn 父/子进程（reload 模式下可能产生）
    for /f "tokens=2" %%P in ('tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *uvicorn*" /NH 2^>nul ^| findstr /I "python"') do (
        echo [INFO] Killing residual python PID: %%P
        taskkill /F /PID %%P >nul 2>&1
    )
    timeout /t 2 /nobreak >nul
    echo [OK] Port %APP_PORT% freed
) else (
    echo [OK] Port %APP_PORT% available
)

REM 清理 __pycache__ 确保加载最新代码
echo [INFO] Cleaning __pycache__...
for /d /r "%cd%\app" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d"
)
echo [OK] Cache cleaned

REM ============================================================================
REM 7. Display startup info
REM ============================================================================

echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   Server Config
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
echo   Project:  %PROJECT_NAME%
echo   Env:      %APP_ENV%
echo   Debug:    %DEBUG%
echo   Workers:  %APP_WORKERS%
echo.

REM ============================================================================
REM 8. Start server
REM ============================================================================

echo [OK] Starting dev server...
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   URL:  http://%APP_HOST%:%APP_PORT%
if not "%DOCS_URL%"=="None" if not "%DOCS_URL%"=="" (
    echo   Docs: http://%APP_HOST%:%APP_PORT%%DOCS_URL%
)
echo   Press Ctrl+C to stop
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.

REM Decide --reload based on DEBUG mode
set "RELOAD_FLAG="
if "%DEBUG%"=="True" set "RELOAD_FLAG=--reload"
if "%DEBUG%"=="true" set "RELOAD_FLAG=--reload"

REM Start server (Windows: workers>1 incompatible with reload, use single process in dev)
if defined RELOAD_FLAG (
    python -m uvicorn app.main:app --host %APP_HOST% --port %APP_PORT% %RELOAD_FLAG%
) else (
    python -m uvicorn app.main:app --host %APP_HOST% --port %APP_PORT% --workers %APP_WORKERS%
)

endlocal
