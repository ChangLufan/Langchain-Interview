@echo off
cd /d F:\PythonProject\easy-langent
for /f "delims=" %%i in ('.venv\Scripts\python.exe -c "import certifi; print(certifi.where())"') do set SSL_CERT_FILE=%%i
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe scripts\simple_api_server.py >> logs\api.out.log 2>> logs\api.err.log
