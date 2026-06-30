@echo off
setlocal EnableExtensions
echo =========================================
echo    Argos - Web Dashboard Launcher    
echo =========================================
echo.

REM Locate project root (one level up from scripts/)
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

REM --- 1) Ensure venv and dependencies ----------------------------------
set "PYTHON_EXE="
where py > nul 2>&1
if not errorlevel 1 set "PYTHON_EXE=py -3"
if "%PYTHON_EXE%"=="" (
    where python > nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
)
if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python 3.11+ not found. Please install Python first.
    pause
    exit /b 1
)

if not exist "%PROJECT_ROOT%\venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment...
    %PYTHON_EXE% -m venv "%PROJECT_ROOT%\venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

if not exist "%PROJECT_ROOT%\venv\Scripts\uvicorn.exe" (
    echo [INFO] Installing dependencies. This may take a few minutes on first run...
    "%PROJECT_ROOT%\venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 (
        echo [ERROR] Failed to upgrade pip.
        pause
        exit /b 1
    )
    "%PROJECT_ROOT%\venv\Scripts\python.exe" -m pip install -r "%PROJECT_ROOT%\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Failed to install requirements.
        pause
        exit /b 1
    )
)

REM --- 2) Auto-generate .env if missing ---------------------------------
if not exist "%PROJECT_ROOT%\.env" (
    echo [WARN] .env file not found.
    copy "%PROJECT_ROOT%\.env.template" "%PROJECT_ROOT%\.env" > nul
    set /p "ARGOS_FIRST_RUN_LLM_API_KEY=LLM_API_KEY (blank to edit .env later): "
    if not "%ARGOS_FIRST_RUN_LLM_API_KEY%"=="" (
        powershell.exe -NoProfile -Command "$p = '%PROJECT_ROOT%\.env'; $key = $env:ARGOS_FIRST_RUN_LLM_API_KEY; $text = Get-Content -Raw -Path $p; $text = $text.Replace('# LLM_API_KEY=\"sk-your-api-key-here\"', ('LLM_API_KEY=\"' + $key + '\"')); Set-Content -Path $p -Value $text -NoNewline"
        echo [OK] .env created with your API key.
    ) else (
        echo [WARN] .env created from template. Please edit it to add your LLM_API_KEY.
    )
)

REM --- 3) Optional RAG dependencies -------------------------------------
set "RAG_ENABLED_EFFECTIVE=false"
for /f "delims=" %%R in ('"%PROJECT_ROOT%\venv\Scripts\python.exe" "%PROJECT_ROOT%\scripts\resolve_rag_enabled.py"') do set "RAG_ENABLED_EFFECTIVE=%%R"

if /i "%RAG_ENABLED_EFFECTIVE%"=="true" (
    "%PROJECT_ROOT%\venv\Scripts\python.exe" -c "import sentence_transformers" > nul 2>&1
    if errorlevel 1 (
        echo [INFO] Installing RAG dependencies...
        "%PROJECT_ROOT%\venv\Scripts\python.exe" -m pip install -r "%PROJECT_ROOT%\requirements-rag.txt"
        if errorlevel 1 (
            echo [ERROR] Failed to install RAG dependencies.
            pause
            exit /b 1
        )
    )
    echo [INFO] Checking RAG model cache...
    "%PROJECT_ROOT%\venv\Scripts\python.exe" "%PROJECT_ROOT%\scripts\download_models.py"
) else (
    echo [INFO] RAG_ENABLED=false; skipping RAG dependencies and embedding model download.
)

REM --- 4) port-in-use shortcut ------------------------------------------
netstat -ano | findstr /r /c:":8000 .*LISTENING" > nul 2>&1
if not errorlevel 1 (
    echo [INFO] Port 8000 is already in use. Opening the existing dashboard...
    start "" http://127.0.0.1:8000
    echo.
    pause
    exit /b 0
)

REM --- 5) Check Redis only; cache is optional ----------------------------
where redis-cli > nul 2>&1
if not errorlevel 1 (
    redis-cli ping > nul 2>&1
    if errorlevel 1 (
        echo [WARN] Redis is installed but not running. Caching will be disabled.
    ) else (
        echo [OK] Redis is running.
    )
) else (
    echo [INFO] Redis not found. Caching will be disabled.
)

REM --- 6) Start backend in a visible window -----------------------------
set "UVICORN_RELOAD_ARG="
if /i "%ARGOS_RELOAD%"=="true" set "UVICORN_RELOAD_ARG=--reload"

echo Starting Argos backend...
start "Argos Backend" powershell.exe -NoExit -ExecutionPolicy Bypass -Command ^
    "& '%PROJECT_ROOT%\venv\Scripts\Activate.ps1'; Set-Location '%PROJECT_ROOT%'; uvicorn main:app %UVICORN_RELOAD_ARG%"

REM --- 7) Poll /api/v1/ping until healthy (max ~30s) --------------------
echo Waiting for server to become healthy...
set /a _tries=0
:WAIT_LOOP
set /a _tries+=1
powershell.exe -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/v1/ping' -TimeoutSec 2 -UseBasicParsing; if ($r.StatusCode -ne 200) { exit 1 } } catch { exit 1 }" > nul 2>&1
if not errorlevel 1 goto :READY
if %_tries% GEQ 30 goto :TIMEOUT
timeout /t 1 /nobreak > nul
goto :WAIT_LOOP

:TIMEOUT
echo [WARN] Server did not respond within 30 seconds. Opening the URL anyway.
goto :LAUNCH

:READY
echo Server is ready.

:LAUNCH
echo Opening dashboard in your browser...
start "" http://127.0.0.1:8000

echo.
echo Dashboard: http://127.0.0.1:8000
echo Close the "Argos Backend" window to stop the server.
echo.
pause
endlocal
