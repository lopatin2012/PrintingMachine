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
:: Хост и порт берём из .env (SERVICE_HOST / SERVICE_PORT — те же имена, что
:: читает main.py), чтобы не хардкодить их в скрипте. По умолчанию — 0.0.0.0:8111.
set "SERVICE_HOST=0.0.0.0"
set "SERVICE_PORT=8111"
if exist "%~dp0.env" (
    for /f "usebackq eol=# tokens=1,* delims== " %%A in ("%~dp0.env") do (
        if /i "%%A"=="SERVICE_HOST" if not "%%~B"=="" set "SERVICE_HOST=%%~B"
        if /i "%%A"=="SERVICE_PORT" if not "%%~B"=="" set "SERVICE_PORT=%%~B"
    )
)
:: В .env значения могут быть в кавычках и с пробелами — снимаем их.
if defined SERVICE_HOST set "SERVICE_HOST=%SERVICE_HOST:'=%"
if defined SERVICE_PORT set "SERVICE_PORT=%SERVICE_PORT:'=%"
if defined SERVICE_HOST set "SERVICE_HOST=%SERVICE_HOST: =%"
if defined SERVICE_PORT set "SERVICE_PORT=%SERVICE_PORT: =%"

echo [2/2] Запуск сервиса печати на %SERVICE_HOST%:%SERVICE_PORT%...
python -m uvicorn main:app --host %SERVICE_HOST% --port %SERVICE_PORT%

:: Если сервис остановился или упал — окно не закрываем, чтобы был виден текст
:: ошибки (иначе консоль схлопывается и причину не видно).
echo.
echo Сервис остановлен. Код возврата: %errorlevel%
pause
endlocal
