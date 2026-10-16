@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  python orchestrator.py --stop
) else (
  py -3 orchestrator.py --stop
)
