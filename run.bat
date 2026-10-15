@echo off
set PYTHON=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe
set PYTHONIOENCODING=utf-8

echo ============================================
echo  Exaskisi Anagnosis - Ekkinisi...
echo ============================================
echo.

start /min "ReadingPracticeServer" "%PYTHON%" -m uvicorn main:app --host 127.0.0.1 --port 8000

echo  Fortosi Whisper model, perimene...
echo.

:wait
timeout /t 2 /nobreak >nul
"%PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000')" >nul 2>&1
if errorlevel 1 goto wait

start http://localhost:8000
echo  Etoimo! http://localhost:8000
echo.
echo  Gia na stamatisei: kleise to parathyro ReadingPracticeServer
echo.
pause
