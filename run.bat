@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Membuat virtual environment...
    python -m venv .venv
)
".venv\Scripts\python.exe" -c "import PySide6, openpyxl" >nul 2>&1
if errorlevel 1 (
    echo Memasang dependensi...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0

:error
echo.
echo Gagal memasang dependensi. Periksa koneksi internet dan coba lagi.
pause
exit /b 1
