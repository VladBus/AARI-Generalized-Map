@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "MAIN_SCRIPT=%PROJECT_DIR%\main.py"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Не найден Python: %PYTHON_EXE%
    echo Создайте .venv и установите requirements.txt.
    exit /b 2
)
if not exist "%MAIN_SCRIPT%" (
    echo [ERROR] Не найден скрипт: %MAIN_SCRIPT%
    exit /b 2
)

cd /d "%PROJECT_DIR%"
rem Без параметров — безопасная проверка без копирования и отправки.
if "%~1"=="" (
    "%PYTHON_EXE%" "%MAIN_SCRIPT%" --stage auto
) else (
    "%PYTHON_EXE%" "%MAIN_SCRIPT%" %*
)
set "EXIT_CODE=%ERRORLEVEL%"
echo [%date% %time%] AARI-Generalized-Map завершён, код=%EXIT_CODE%
exit /b %EXIT_CODE%
