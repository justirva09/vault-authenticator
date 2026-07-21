@echo off
REM Builds Vault Authenticator into a double-clickable Windows app.
REM Run from inside the totp-desktop folder in Command Prompt:
REM   build_windows_app.bat

cd /d "%~dp0"

if not exist venv (
  echo Creating virtual environment...
  python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -q -r requirements.txt
if errorlevel 1 goto :error

echo Building app...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
pyinstaller vault_windows.spec
if errorlevel 1 goto :error

echo.
echo Done. Your app is at:
echo   %cd%\dist\Vault Authenticator\Vault Authenticator.exe
echo.
echo Create a shortcut to that .exe (right-click it -^> Create shortcut) and
echo pin it to Start / Taskbar, or move the whole "Vault Authenticator"
echo folder wherever you like - just keep the .exe together with its folder.
goto :eof

:error
echo.
echo Build failed - see the error above.
exit /b 1
