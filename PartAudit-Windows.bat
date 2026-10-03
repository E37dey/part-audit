@echo off
rem PartAudit - start (Windows). First run installs a private Python environment (internet, a few minutes).
setlocal
cd /d "%~dp0"
title PartAudit
set "VENV=%LOCALAPPDATA%\PartAudit\venv"
set "PY=%VENV%\Scripts\python.exe"

where uv >nul 2>nul
if errorlevel 1 if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo First run: installing uv, a small Python installer from astral.sh ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" || goto fail
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

if not exist "%PY%" (
  echo Creating the PartAudit environment in %VENV% ...
  uv venv --clear "%VENV%" --python 3.12 || uv venv "%VENV%" --python 3.12 || uv venv "%VENV%" || goto fail
)
fc /b requirements.txt "%VENV%\requirements.installed" >nul 2>nul
if errorlevel 1 (
  echo Installing PartAudit components - about 150 MB, only on the first run ...
  uv pip install --python "%PY%" -r requirements.txt || goto fail
  copy /y requirements.txt "%VENV%\requirements.installed" >nul
)

echo.
echo PartAudit is starting. The browser opens by itself.
echo Keep this window open while you work; close it to stop PartAudit.
"%PY%" -m part_audit app %*
goto end

:fail
echo.
echo The installation did not finish. Check the internet connection (or the proxy) and run this file again.
pause
:end
endlocal
