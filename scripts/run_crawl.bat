@echo off
cd /d "%~dp0.."
set PYTHONPATH=%CD%
set HF_HOME=D:\hf-cache
set TRANSFORMERS_CACHE=D:\hf-cache
set HUGGINGFACE_HUB_CACHE=D:\hf-cache
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
REM Maximal crawl from Annex 1 — HTML + PDF + DOCX + XLSX + auto-discovered sources
python -m backend.crawler.pipeline %*
