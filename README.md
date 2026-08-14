# PrintingMachine

Микросервис централизованного управления промышленной печатью **групповых этикеток** (GTIN групповой упаковки) на термопринтерах Zebra/TSC, поддерживающих язык **ZPL**, построенный на FastAPI.

Проект автоматизирует процесс маркировки продукции на производственных и складских линиях: от регистрации цехов, линий и принтеров до формирования заданий на печать партии коробок со штрихкодами GS1-128, асинхронной отправки этикеток на принтеры и ведения журнала заданий.

---

## Возможности

**Производственная структура**

* иерархия «Цеха → Линии → Принтеры»;
* привязка пользователей к цехам и линиям (`WorkshopUser`), спец-цех «Все цеха» — доступ ко всем принтерам.

**Принтеры**

* регистрация по `IP:порт` (по умолчанию TCP 9100);
* проверка доступности и статуса принтера (команда `~HS`: пауза, ошибки, бумага/риббон).

**Продукты и шаблоны**

* продукты: код 1С, GTIN групповой упаковки, срок годности в днях;
* ZPL-шаблоны этикеток с плейсхолдерами GS1-128, привязка «продукт + принтер», активация/деактивация;
* предпросмотр этикетки до печати.

**Печать**

* задание на печать: партия, дата маркировки, диапазон номеров коробок; срок годности вычисляется автоматически;
* асинхронная очередь печати: повторные попытки с экспоненциальной задержкой, ожидание снятия паузы принтера, остановка задания, докачка с места остановки;
* журнал и история заданий, счётчик напечатанных этикеток;
* статусы задания: `pending → processing → completed | failed | cancelled`.

**Пользователи и безопасность**

* JWT-аутентификация (токен в cookie), пароли — Argon2;
* роли Admin / Editor / User, защита административных разделов;
* CORS через `ALLOWED_ORIGINS`, HTTPS-редирект вне режима DEBUG.

---

## Технологический стек

| Слой | Технологии |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2.x (async), Pydantic v2 |
| База данных | PostgreSQL + asyncpg, Alembic |
| Аутентификация | JWT (python-jose), passlib + Argon2 |
| Печать | ZPL, TCP Socket (порт 9100), asyncio-очередь |
| Превью | Labelary API, бинарник zebrash, zebrafy, Pillow |
| Интерфейс | Jinja2, HTML/CSS/JS (jsbarcode, qrcode) |

---

## Структура проекта

```text
PrintingMachine/
├── main.py                  # Точка входа: FastAPI, lifespan (очередь, init_db), CORS
├── config.py                # Настройки рендера превью (zebrash)
├── models.py                # ORM-модели
├── schemas.py               # Pydantic-схемы
├── database.py              # Подключение к БД + init_db (роли, админ)
├── security.py              # JWT, get_current_user / get_current_admin
├── auth_utils.py            # Argon2-хеширование паролей
├── helper.py                # BASE_DIR, набор кириллических символов
├── templates_config.py      # Jinja2Templates + фильтры дат
├── init_db.py               # Скрипт ручной инициализации БД
├── alembic.ini / alembic/   # Миграции БД
├── routers/                 # HTTP-маршруты
│   ├── auth.py              # Вход, регистрация, выход
│   ├── workshop.py          # Цеха
│   ├── line.py              # Линии
│   ├── printer.py           # Принтеры
│   ├── product.py           # Продукты (пагинация, фильтры)
│   ├── template.py          # ZPL-шаблоны + предпросмотр
│   ├── print_job.py         # Задания на печать, очередь, история
│   ├── preview_barcode.py   # Превью этикетки (Labelary / офлайн)
│   ├── user.py / role.py / workshop_user.py  # Пользователи, роли, привязки
├── crud/                    # CRUD-слои (base + по сущностям)
├── services/
│   ├── print_queue.py       # Асинхронная очередь печати (воркеры, повторы, отмена)
│   └── zpl_renderer.py      # Рендер ZPL → PNG (zebrash / zebrafy)
├── helpers/
│   ├── printers.py          # Подстановка плейсхолдеров, статус ~HS, отправка по TCP
│   ├── responses.py         # AJAX / redirect ответы
│   └── pagination.py        # Константы пагинации
├── templates/               # Jinja2-шаблоны страниц
├── static/                  # CSS/JS, документация по ZPL/TSC
└── requirements.txt
```

---

## Модель данных

```text
Workshop (цех)
 └── Line (линия)
     └── Printer (IP, порт 9100)
         ├── CodeTemplate (ZPL-шаблон)
         └── PrintJob (задание печати)

Product (код 1С, GTIN, срок годности в днях)
 ├── CodeTemplate
 └── PrintJob

User ── Role (admin / editor / user)
User ── WorkshopUser (цех, линия, роль в цеху, активность)
User ── PrintJob
```

Ключевая сущность — **PrintJob**:

| Поле | Описание |
|---|---|
| `batch_number` | Номер партии |
| `marking_date` | Дата маркировки |
| `expiration_date` | Дата окончания срока годности |
| `first_box` / `last_box` | Диапазон номеров коробок |
| `boxes_count` | Количество коробок (`last_box - first_box + 1`) |
| `status` | `pending` / `processing` / `completed` / `failed` / `cancelled` |
| `printed_count` | Количество отправленных этикеток |
| `error_message` | Сообщение об ошибке (при `failed`) |
| `completed_at` | Дата завершения |

Срок годности вычисляется автоматически: `expiration_date = marking_date + product.date_expiration`.

---

## Сценарий печати

1. Пользователь открывает страницу **«Печать этикеток»** (`/printing`) — видны продукты, для которых есть активные шаблоны на доступных пользователю принтерах.
2. Выбирает продукт, шаблон и принтер; указывает партию, дату маркировки и диапазон коробок.
3. Сервер создаёт `PrintJob` (статус `pending`) и помещает `PrintTask` в очередь печати.
4. Воркер очереди:
   * переводит задание в `processing`;
   * проверяет статус принтера (`~HS`); при паузе — ждёт снятия (до 4 часов), при недоступности — повторяет с экспоненциальной задержкой;
   * для каждой коробки подставляет плейсхолдеры в ZPL-шаблон, заменяет кириллицу на HEX-представление и отправляет код на принтер по TCP (частями, с `TCP_NODELAY`);
   * после каждой этикетки фиксирует `printed_count` — при сбое печать продолжится с места остановки;
   * по завершении — статус `completed` и `completed_at`.
5. Остановка задания: на принтер отправляется `~JA` (сброс его очереди), задание получает статус `cancelled`.

---

## Плейсхолдеры шаблона

Подстановка выполняется в `helpers/printers.py` (функция `substitute_placeholders`) — единая для предпросмотра и реальной печати.

| Плейсхолдер | Значение |
|---|---|
| `{gs1_128_marking_date}` | Дата маркировки, `YYMMDD` |
| `{gs1_128_expiry_date}` / `{gs1_128_expiration_date}` | Срок годности, `YYMMDD` |
| `{gs1_128_batch}` / `{gs1_128_batch_number}` | Партия = дата маркировки, `ДДММГГ` |
| `{gs1_128_current_box}` / `{current_box}` | Номер коробки, 5 знаков (`00001`) |
| `{gs1_gtin}` | GTIN как введён; `{gs1_gtin_short}` — без первого символа |
| `{gs1_gs}` | Символ-разделитель GS (ASCII 29) |
| `{marking_date_str}` / `{expiration_date_str}` | Даты в формате `ДД.ММ.ГГ` |
| `{batch_number_str}` | `партия(ДДММГГ)` |
| `{batch_number}` | Номер партии как есть |

Дополнительно:

* если шаблон не заканчивается на `^XZ`, команда завершения этикетки добавляется автоматически;
* кириллические символы преобразуются в HEX-представление (`_XX`) для совместимости со шрифтами принтера.

---

## Предпросмотр этикетки

* `POST /templates/preview/render` — онлайн-рендер через Labelary API (даты в формате `YYMMDD`);
* `POST /templates/preview/render_local` — полностью офлайн: бинарник **zebrash** (или **zebrafy** для графики `^GF`);
* `POST /zpl_render_labelary` — рендер с автоматическим fallback на локальную генерацию при недоступности API или при `OFFLINE_MODE=true`.

---

## Очередь печати

Реализация — `services/print_queue.py`.

* число воркеров задаётся env-переменной `PRINTER_WORKERS` (по умолчанию `1`); увеличьте до числа принтеров, чтобы задания на разные принтеры печатались параллельно;
* задания на один и тот же принтер всегда выполняются строго последовательно (блокировка на принтер) — этикетки разных заданий не перемешиваются;
* повторы: до `max_retries` попыток (у задания печати — 3), задержка `2^attempt` секунд;
* при паузе принтера — ожидание снятия до 4 часов (проверка каждые 2 секунды);
* отмена: `~JA` + статус `cancelled`, остановка после текущей этикетки;
* прогресс `printed_count` сохраняется в БД после каждой этикетки — докачка после сбоя начинается с сохранённого счётчика.

---

## API и страницы

**Служебные:** `GET /api/health`, `GET /api/info`, Swagger UI — `/api/docs`, ReDoc — `/api/redoc`, OpenAPI — `/api/openapi.json`.

**Страницы:** `/` (главная), `/printing` (печать этикеток), `/printing/history` (история), `/workshops`, `/lines`, `/printers`, `/products`, `/templates`, `/users`, `/roles`, `/workshop-users`.

**API печати:** `POST /printing/start`, `POST /api/printing/jobs/{job_id}/stop`, `GET /api/printing/jobs/user`, `GET /api/printing/jobs/active`, `GET /api/printing/template/{product_id}`, `GET /api/printing/printers`, `GET /api/printing/templates`.

---

## Установка и запуск

```bash
git clone <repository-url>
cd PrintingMachine
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

### Настройка окружения (`.env`)

```env
# База данных (PostgreSQL)
DB_USER=postgres
DB_PASSWORD=password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=printing_machine
# DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/printing_machine

# Администратор (создаётся при первой инициализации БД)
ADMIN_LOGIN=admin
ADMIN_PASSWORD=admin
ADMIN_EMAIL=admin@example.com

# Приложение
DEBUG=True
SERVICE_HOST=0.0.0.0
SERVICE_PORT=8000
SECRET_KEY=change-me
# ALLOWED_ORIGINS=https://print.example.com,https://admin.example.com

# Очередь печати: число воркеров (по умолчанию 1 — строго последовательная печать)
# PRINTER_WORKERS=2

# Предпросмотр
# ZEBRASH_BINARY=/path/to/zebrash-render
# OFFLINE_MODE=True
```

> **Важно:** перед боевым использованием смените пароль администратора по умолчанию и `SECRET_KEY`.

### База данных и миграции

* миграции: `alembic upgrade head` (готовые миграции в `alembic/versions/`);
* при старте приложения таблицы также создаются автоматически (`Base.metadata.create_all`), а при отсутствии — роли (`admin`, `editor`, `user`) и администратор;
* ручная инициализация: `python init_db.py`.

### Запуск

```bash
uvicorn main:app --reload
```

После запуска: Swagger UI — `http://localhost:8000/api/docs`.

---

## Безопасность

* JWT (HS256), токен в cookie `access_token`, срок действия — 25 часов по умолчанию (`ACCESS_TOKEN_EXPIRE_MINUTES` в `routers/auth.py`);
* пароли — Argon2 (passlib);
* роли: Admin (полный доступ), Editor (шаблоны и печать), User (только печать);
* CORS: `ALLOWED_ORIGINS` — список доменов через запятую; пусто = только same-origin запросы; `*` допустим только без credentials;
* вне режима DEBUG включается редирект на HTTPS;
* при первом входе используйте стандартный пароль администратора с осторожностью (в логах выводится предупреждение).

---

## Логирование

* запуск и остановка сервиса и очереди печати;
* инициализация БД;
* события печати: создание задания, отправка этикеток, ошибки сети, повторные попытки, отмена.
