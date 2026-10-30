@echo off
cd /d "%~dp0"
set "PY=D:\anaconda\envs\watermask\python.exe"
if not exist "%PY%" (
    echo Cannot find conda env watermask: %PY%
    pause
    exit /b 1
)
"%PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failed
"%PY%" -m pip install pyinstaller
if errorlevel 1 goto failed
set "PYTHONPATH=%~dp0src"
"%PY%" -m PyInstaller --noconfirm --clean --windowed --name PhotoWatermarkStudio --paths src --collect-all PySide6 --add-data "src\photo_watermark_studio\resources;photo_watermark_studio\resources" src\photo_watermark_studio\main.py
if errorlevel 1 goto failed
echo Build finished: dist\PhotoWatermarkStudio\PhotoWatermarkStudio.exe
pause
exit /b 0
:failed
echo Build failed.
pause
exit /b 1