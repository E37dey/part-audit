@echo off
rem PartAudit - team server (Windows): the app for everyone on the network; each person signs in with a user.
rem The first time it asks for the first admin account. Windows may ask to allow Python on the network: allow it
rem on private networks only.
setlocal
cd /d "%~dp0"
title PartAudit - team server
call "%~dp0PartAudit-Windows.bat" --setup-only || goto fail
set "PY=%LOCALAPPDATA%\PartAudit\venv\Scripts\python.exe"
if not exist "%PY%" goto fail

:serve
"%PY%" -m part_audit serve %*
if errorlevel 3 if not errorlevel 4 goto admin
goto end

:admin
echo.
echo The team server needs a first admin account (it can add the other users in the app, under Settings).
set "ADMIN="
set /p ADMIN=Admin user name (for example: dana.levi): 
if "%ADMIN%"=="" goto end
"%PY%" -m part_audit users add "%ADMIN%" --role admin || goto admin
goto serve

:fail
echo.
echo PartAudit could not be prepared. Run PartAudit-Windows.bat once and check the internet connection.
pause
:end
endlocal