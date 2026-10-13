@echo off
chcp 65001 >nul
setlocal

:: Служба печати — запуск с обновлением зависимостей.
:: Скрипт лежит в корне проекта, поэтому путь берём от самого скрипта,
:: а не хардкодим диск (на сервере можно положить куда угодно).
cd /d "%~dp0"

:: Виртуальное окружение проекта.
set "VENV=%~dp0.venv"
if not exist "%VENV%\Scripts\python.exe" (
    echo [ОШИБКА] Не найдено виртуальное окружение: %VENV%
    echo          Создайте его: python -m venv .venv
    pause
    exit /b 1
)
call "%VENV%\Scripts\activate.bat"

:: UTF-8, чтобы русский текст в логах читался (не в cp866).
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:: 1. Обновляем зависимости: requirements.txt мог измениться. Например, без
::    python-barcode / pylibdmtx / setuptools падает импорт при старте.
echo [1/2] Обновление зависимостей (requirements.txt)...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [ВНИМАНИЕ] Не удалось обновить зависимости ^(нет сети?^).
    echo            Продолжаем запуск с уже установленными библиотеками.
    timeout /T 5 /NOBREAK >nul
)

:: 2. Запуск сервиса.
echo [2/2] Запуск сервиса печати на 0.0.0.0:8111...
python -m uvicorn main:app --host 0.0.0.0 --port 8111

:: Если сервис остановился или упал — окно не закрываем, чтобы был виден текст
:: ошибки (иначе консоль схлопывается и причину не видно).
echo.
echo Сервис остановлен. Код возврата: %errorlevel%
pause
endlocal
