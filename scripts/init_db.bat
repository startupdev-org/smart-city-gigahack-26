@echo off
cd /d "%~dp0.."
set PYTHONPATH=%CD%
"D:\civic-ai-venv\Scripts\python.exe" -m backend.scripts.init_db
