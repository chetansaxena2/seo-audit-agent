@echo off
title SEO Audit Agent
cd /d "%~dp0"
echo ============================================
echo   SEO Audit Agent
echo ============================================
echo.

REM --- is Python there at all? ---
python --version >nul 2>&1
if errorlevel 1 (
  echo [X] Python is not installed, or "Add python.exe to PATH" was not ticked.
  echo     Get it from https://www.python.org/downloads/release/python-3129/
  echo.
  pause
  exit /b
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Using Python %PYVER%
echo.

REM --- install into a private folder so nothing else on your PC is touched ---
if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python environment...
  python -m venv .venv
  if errorlevel 1 (
    echo [X] Could not create the environment. Try reinstalling Python.
    pause
    exit /b
  )
)
set PY=.venv\Scripts\python.exe

REM --- do we already have everything? ---
%PY% -c "import uvicorn, fastapi, lxml, httpx, reportlab" >nul 2>&1
if not errorlevel 1 goto :run

echo Installing components. First run only - takes 5 to 8 minutes.
echo.
%PY% -m pip install --upgrade pip --quiet
%PY% -m pip install -r requirements.txt
%PY% -c "import uvicorn, fastapi, lxml, httpx, reportlab" >nul 2>&1
if not errorlevel 1 goto :browser

echo.
echo Standard install did not work on Python %PYVER%. Trying flexible versions...
echo.
%PY% -m pip install -r requirements-flexible.txt
%PY% -c "import uvicorn, fastapi, lxml, httpx, reportlab" >nul 2>&1
if not errorlevel 1 goto :browser

echo.
echo ============================================
echo  [X] Install failed.
echo.
echo  Most likely cause: Python %PYVER% is too new and some
echo  components have no build for it yet.
echo.
echo  Fix: install Python 3.12 from
echo  https://www.python.org/downloads/release/python-3129/
echo  (tick "Add python.exe to PATH"), delete the .venv folder,
echo  then run this file again.
echo ============================================
pause
exit /b

:browser
echo.
echo Downloading the browser used for screenshots...
%PY% -m playwright install chromium
if errorlevel 1 (
  echo.
  echo NOTE: the browser could not be downloaded ^(network or firewall^).
  echo The agent still works - reports just come without screenshots.
)
echo.
echo Setup complete.
echo.

:run
echo.
echo   Open your browser at:  http://localhost:8000
echo   Press Ctrl+C here to stop it.
echo.
%PY% -m uvicorn app.api:app --host 127.0.0.1 --port 8000
pause
