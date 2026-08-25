@echo off
title Horizon — Installer
color 0A
cd /d "%~dp0"
cls
echo.
echo  ============================================================
echo     HORIZON  ·  Document Compression Agent
echo     One-Click Installer
echo  ============================================================
echo.

:: ── Python check ─────────────────────────────────────────────
echo  [1/4]  Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR]  Python 3.8+ not found.
    echo           Download: https://python.org/downloads
    echo           Tick "Add Python to PATH" during install.
    echo.
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo  [OK]   %%v
echo.

:: ── Python packages ──────────────────────────────────────────
echo  [2/4]  Installing packages...
echo         (flask · PyMuPDF · pikepdf · Pillow · pywebview · pdf2docx · python-docx)
echo         Please wait — this may take 3-5 minutes.
echo.
pip install --upgrade flask PyMuPDF pikepdf Pillow pywebview pdf2docx python-docx pytesseract >nul 2>&1
if %errorlevel% neq 0 (
    pip install --break-system-packages --upgrade flask PyMuPDF pikepdf Pillow pywebview pdf2docx python-docx pytesseract >nul 2>&1
)
python -c "import flask, fitz, pikepdf, PIL, webview" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [WARN]  Some packages may not have installed. Retrying...
    pip install flask PyMuPDF pikepdf Pillow pywebview pdf2docx python-docx pytesseract
) else (
    echo  [OK]   All Python packages installed.
)
echo         (pdf2docx + python-docx + pytesseract power the PDF-to-Word feature)
echo         (For OCR, also install Tesseract: https://github.com/UB-Mannheim/tesseract/wiki)
echo.

:: ── Ghostscript ───────────────────────────────────────────────
echo  [3/4]  Checking Ghostscript...
gswin64c --version >nul 2>&1
if %errorlevel% equ 0 ( echo  [OK]   Ghostscript 64-bit found. & goto :gs_ok )
gswin32c --version >nul 2>&1
if %errorlevel% equ 0 ( echo  [OK]   Ghostscript 32-bit found. & goto :gs_ok )
gs --version >nul 2>&1
if %errorlevel% equ 0 ( echo  [OK]   Ghostscript found. & goto :gs_ok )

echo.
echo  [INFO] Ghostscript not installed.
echo.
echo         For MAXIMUM compression power, install Ghostscript:
echo         https://www.ghostscript.com/releases/gsdnld.html
echo.
echo         Choose: "Ghostscript 10.x for Windows (64 bit) — AGPL Release"
echo.
echo         Horizon will still work without it via PyMuPDF fallback.
echo.
:gs_ok

:: ── Desktop shortcut ──────────────────────────────────────────
echo  [4/4]  Creating Desktop shortcut...
echo.

python make_shortcut.py
if %errorlevel% neq 0 (
    echo  [INFO] Run create_shortcut.bat as Administrator if the icon is missing.
)
echo.

:: ── Done ─────────────────────────────────────────────────────
echo  ============================================================
echo     INSTALLATION COMPLETE!
echo  ============================================================
echo.
echo     Double-click the HORIZON icon on your Desktop to launch.
echo     A native app window will open — no browser, no CMD window.
echo.
echo     To debug: run start.bat (shows console output).
echo.
pause
