@echo off
cd /d "%~dp0"
set "PY=D:\anaconda\envs\watermask\python.exe"
set "PYW=D:\anaconda\envs\watermask\pythonw.exe"
if not exist "%PY%" (
    echo Cannot find conda env watermask: %PY%
    pause
    exit /b 1
)
"%PY%" -c "import PySide6, PIL" >nul 2>&1
if errorlevel 1 (
    "%PY%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo Dependency install failed.
        pause
        exit /b 1
    )
)
set "PYTHONPATH=%~dp0src"
cd /d "%~dp0src"
if exist "%PYW%" (
    start "" "%PYW%" -m photo_watermark_studio.main
) else (
    start "" "%PY%" -m photo_watermark_studio.main
)
cd ..
exit /b 0
