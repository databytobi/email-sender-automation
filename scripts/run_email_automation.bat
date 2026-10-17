@echo off
setlocal

rem Change to the project root (one level above this script's folder),
rem so the automation works no matter where it is launched from.
cd /d "%~dp0.."

rem Use the project's virtual environment Python directly (no activation
rem needed). Fall back to the system Python if the venv is missing.
set "PYTHON=my_venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

rem Extra arguments are passed through, e.g.:
rem   run_email_automation.bat --dry-run
rem   run_email_automation.bat --type invoice --yes
"%PYTHON%" main.py %*

rem Propagate the exit code so Task Scheduler can detect failures
rem (0 = success, 1 = failed sends or bad input, 2 = SMTP problem,
rem  130 = aborted by user).
exit /b %ERRORLEVEL%
