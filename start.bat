@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  python orchestrator.py
) else (
  py -3 orchestrator.py
)
if errorlevel 1 pause
