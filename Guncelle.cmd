@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Once Baslat.cmd dosyasini calistirin.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" stop.py
".venv\Scripts\python.exe" -m pip install -U "yt-dlp[default]"
if errorlevel 1 (
  echo Guncelleme basarisiz oldu.
  pause
  exit /b 1
)
start "" wscript.exe "%~dp0Baslat.vbs"
echo Guncelleme tamamlandi. Uygulama yeniden aciliyor.
pause
