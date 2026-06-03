@echo off
cd /d F:\PythonProject\easy-langent
for /f "delims=" %%i in ('.venv\Scripts\python.exe -c "import certifi; print(certifi.where())"') do set SSL_CERT_FILE=%%i
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe scripts\local_dev_server.py >> logs\local_dev.out.log 2>> logs\local_dev.err.log
