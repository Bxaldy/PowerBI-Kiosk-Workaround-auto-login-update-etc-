@echo off
REM ============================================================================
REM POWERBI AUTO-SIGNIN KIOSK - SETUP BATCH SCRIPT
REM ============================================================================
REM This script installs Python dependencies for the PowerBI Auto-Signin Kiosk.
REM Run as Administrator for best results.
REM ============================================================================

setlocal enabledelayedexpansion

echo.
echo ================================
echo PBI Kiosk - Setup Script
echo ================================
echo.

REM Check Python
echo [1/3] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python first.
    pause
    exit /b 1
)
echo [OK] Python found
python --version

REM Install requirements
echo.
echo [2/3] Installing Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install packages.
    pause
    exit /b 1
)
echo [OK] Packages installed

REM Verify
echo.
echo [3/3] Verifying installations...
python -c "import selenium; print('Selenium: OK')"
python -c "import webdriver_manager; print('webdriver-manager: OK')"

echo.
echo ================================
echo Setup Complete!
echo ================================
echo.
echo Next: Run the script with:
echo python auto_signIn_kiosk_v2.8.py
echo.
pause
