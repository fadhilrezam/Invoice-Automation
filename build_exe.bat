@echo off
cd /d "%~dp0"
echo Memasang dependensi...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error
echo Membersihkan build lama...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo Membangun EXE...
python -m PyInstaller --noconfirm --clean invoice_automation.spec
if errorlevel 1 goto :error
echo.
echo Selesai. File EXE ada di dist\InvoiceAutomation.exe
pause
exit /b 0

:error
echo.
echo Build gagal. Periksa pesan error di atas.
pause
exit /b 1
