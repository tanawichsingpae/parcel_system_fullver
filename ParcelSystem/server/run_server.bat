@echo off
REM Activate venv if exists then run
set VENV_DIR=%~dp0\venv
if exist "%VENV_DIR%\Scripts\activate.bat" (
    call "%VENV_DIR%\Scripts\activate.bat"
)
python -m server.app.main