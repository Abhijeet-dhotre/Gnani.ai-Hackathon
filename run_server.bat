@echo off
REM SafeToy Gnani pipeline — one click on Windows.
REM No second tts_server.py anymore. Timbre is called directly from server.py.
cd /d %~dp0
if not exist venv (
  echo Creating venv...
  python -m venv venv
)
call venv\Scripts\activate
pip install -q -r requirements.txt
if not exist .env (
  echo.
  echo *** Copy .env.example to .env and paste GNANI_API_KEY + GROQ_API_KEY first ***
  echo *** Or run with MOCK_GNANI=1 for a no-key test: set MOCK_GNANI=1 ^&^& python server.py ***
  pause
  exit /b 1
)
python server.py
pause
