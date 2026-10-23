@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, yt_dlp, yt_dlp_ejs" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" start.py
if errorlevel 1 goto fail
exit /b
:fail
echo Uygulama baslatilamadi. Yukaridaki hatayi kontrol edin.
pause
