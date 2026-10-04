@echo off
rem PartAudit - one scan of the systems set up in the app, for Windows Task Scheduler (the app may be closed).
rem The scan is compared with the one before it ("what changed" in the app), and an e-mail goes out when that is
rem turned on in the app's settings. Run PartAudit-Windows.bat once first: it installs PartAudit.
setlocal
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\PartAudit\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo PartAudit is not installed yet: run PartAudit-Windows.bat once first.
  exit /b 2
)
"%PY%" -m part_audit rescan %*
exit /b %errorlevel%
