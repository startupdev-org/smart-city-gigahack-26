@echo off
cd /d "%~dp0.."
set PYTHONPATH=%CD%
set HF_HOME=D:\hf-cache
set TRANSFORMERS_CACHE=D:\hf-cache
set HUGGINGFACE_HUB_CACHE=D:\hf-cache
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
