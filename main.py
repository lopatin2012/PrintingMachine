# main.py

import logging
import os
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

# Миграции.
from starlette.responses import JSONResponse

import models
from helper import BASE_DIR
from security import get_current_user

# Шаблоны.
from templates_config import templates

# Роутеры.
from routers import (
    auth, workshop, line, printer, product, template, preview_barcode,
    workshop_user, user, role, print_job
)
# База данных.
from database import init_db, engine, get_db

# Асинхронные сервисы/очереди.
from services.print_queue import PrinterQueue, PrintTask

# Логирование.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s -%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Режим работы.
IS_DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# Количество воркеров очереди печати (env PRINTER_WORKERS, по умолчанию 1).
# Больше 1 — задания на разные принтеры выполняются параллельно;
# задания на один и тот же принтер всегда строго последовательны (см. print_queue.py).
def _get_printer_workers() -> int:
    try:
        workers = int(os.getenv('PRINTER_WORKERS', '1'))
    except (TypeError, ValueError):
        workers = 1
    return max(1, workers)

favicon_path = 'favicon.ico'

# Очередь печати.
printer_queue = None

# Автоматические миграции.
@asynccontextmanager
async def lifespan(app: FastAPI):
    global printer_queue

    logger.info('Запуск сервиса печати...')

    printer_workers = _get_printer_workers()
    printer_queue = PrinterQueue(
        db_getter=get_db,
        max_concurrent_printers=printer_workers,
    )
    await printer_queue.start()
    logger.info('Очередь печати запущена: %d воркер(а/ов)', printer_workers)

    app.state.printer_queue = printer_queue

    # try:
    #     logger.info('Применение миграций...')
    #     alembic_cfg = Config(str(BASE_DIR / "alembic.ini"))
    #     command.upgrade(alembic_cfg, "head")
    #     logger.info('Миграции успешно применены!')
    # except Exception as e:
    #     logger.error(f"Ошибка во время применения миграций: {e}")
    #     raise

    try:
        # Инициализация базовых данных.
        logger.info('Инициализация базы данных...')
        await init_db(engine)
        logger.info('База данных инициализирована!')
    except Exception as e:
        logger.error(f'Ошибка при инициализации базы данных: {e}')
        raise

    logger.info('Сервис готов к работе!')
    yield

    # Остановка.
    logger.info('Остановка сервиса печати...')
    await printer_queue.stop()
    await engine.dispose()
    logger.info('Подключение к базе данных закрыто')

    logger.info('Сервис печати остановлен!')

# FastAPI.
app = FastAPI(
    title='PrintingMachine',
    description='Микросервис печати',
    version='0.0.1',
    lifespan=lifespan,
    docs_url='/api/docs',
    redoc_url='/api/redoc',
    openapi_url='/api/openapi.json'
)

# Middleware.
from fastapi.middleware.cors import CORSMiddleware

# Разрешённые домены для CORS (переменная ALLOWED_ORIGINS, через запятую).
# По умолчанию список пуст — CORS отключён, работают только same-origin запросы
# (веб-интерфейс на том же домене CORS не требует).
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv('ALLOWED_ORIGINS', '').split(',')
    if origin.strip()
]

if ALLOWED_ORIGINS:
    allow_credentials = '*' not in ALLOWED_ORIGINS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=allow_credentials,
        allow_methods=['*'],
        allow_headers=['*'],
    )
    logger.info(
        'CORS: разрешённые домены: %s (credentials: %s)',
        ALLOWED_ORIGINS, allow_credentials,
    )
else:
    logger.info('CORS не настроен (ALLOWED_ORIGINS пуст) — только same-origin запросы')

if not IS_DEBUG:
    from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
    app.add_middleware(HTTPSRedirectMiddleware)

# Статика.
app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')

# Роутеры.
app.include_router(workshop.router)
app.include_router(line.router)
app.include_router(printer.router)
app.include_router(product.router)
app.include_router(template.router)
app.include_router(preview_barcode.router)
app.include_router(auth.router)
app.include_router(user.router)
app.include_router(workshop_user.router)
app.include_router(print_job.router)
app.include_router(role.router)

@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return FileResponse(favicon_path)

# Эндпроинты.
@app.get('/', response_class=HTMLResponse, include_in_schema=False)
async def home(
        request: Request,
        current_user: models.User = Depends(get_current_user)
):
    """Главная страница"""
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            'user': current_user
        }
    )

@app.get('/api/health', tags=['System'])
async def health_check():
    """Проверка работоспособности сервиса"""
    return {
        'status': 'OK',
        'service': 'printing_machine',
        'timestamp': datetime.now().isoformat()
    }

@app.get('/api/info', tags=['System'])
async def api_info():
    """Информация о сервисе"""
    return {
        'title': app.title,
        'description': app.description,
        'version': app.version,
        'docs': {
            'swagger': '/api/docs',
            'redoc': '/api/redoc'
        }
    }

# Обработчики ошибок.
@app.exception_handler(status.HTTP_404_NOT_FOUND)
async def not_found_exception_handler(request: Request, exc: Exception):
    """Обработка 404"""
    logger.warning(f'404 - Ресурс не найден: {request.method} {request.url}')
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={'detail': 'Запрошенный ресурс не найден!'}
    )

@app.exception_handler(status.HTTP_500_INTERNAL_SERVER_ERROR)
async def internal_exception_handler(request: Request, exc: Exception):
    """Обработка 500"""
    logger.error(f'500 - Внутренняя ошибка: {request.method} {request.url}', exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={'detail': 'Внутренняя ошибка сервера'}
    )

if __name__ == '__main__':
    import uvicorn

    HOST = os.getenv('SERVICE_HOST', '0.0.0.0')
    PORT = os.getenv('SERVICE_PORT', 8000)

    logger.info(f'Запуск сервера на http://{HOST}:{PORT}')
    logger.info(f'Документация: http://{HOST}:{PORT}/api/docs')

    uvicorn.run(
        app=app,
        host=HOST,
        port=PORT,
        log_level='info',
        reload=True # В режиме разработки True, иначе False
    )
