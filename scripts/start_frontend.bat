@echo off
cd /d F:\PythonProject\easy-langent\frontend
..\.venv\Scripts\python.exe -m http.server 5173 --bind 127.0.0.1 >> ..\logs\frontend.out.log 2>> ..\logs\frontend.err.log
