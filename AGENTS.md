# AGENTS.md

## Quick Start

```bash
# Activate venv, install deps
.venv\Scripts\activate
pip install -r requirements.txt

# Run dev server (auto-applies DB migrations, then creates tables + admin user on startup)
uvicorn main:app --reload
# Swagger UI at http://localhost:8000/api/docs
```

## Database

- PostgreSQL + asyncpg (async driver) + psycopg2 (sync, for Alembic)
- Config in `.env`: `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` (no `.env.example` — it's gitignored; see README for the full env reference). `.env` is auto-loaded by `load_dotenv()` inside `database.py` and `migrate.py`, not at app import
- Admin user created on startup from `ADMIN_LOGIN`/`ADMIN_PASSWORD`/`ADMIN_EMAIL` (defaults `admin`/`admin`)
- The service will not start without a reachable PostgreSQL: migrations run inside `lifespan` (before any request is served) and fail startup
- Migrations run automatically at service startup (subprocess `python migrate.py` in `main.py:lifespan`), then `database.py:init_db()` creates roles + admin
- Manual commands: `python -m alembic revision --autogenerate -m "..."` (create), `python -m alembic upgrade head` (apply), or `python migrate.py` (smart rollback-aware)
- `migrate.py` handles empty DBs, dump-restores, and normal upgrades

## Architecture

Single-package FastAPI app — no monorepo, no separate packages.

| Directory | Purpose |
|---|---|
| `routers/` | HTTP route handlers |
| `crud/` | Database CRUD operations |
| `services/` | Async print queue (`print_queue.py`), ZPL rendering (`zpl_renderer.py`), external DataMatrix client (`datamatrix_service.py`) |
| `helpers/` | Printer drivers registry, printer TCP comms, response helpers, pagination |
| `templates/` | Jinja2 HTML templates |
| `static/` | CSS/JS assets |
| `alembic/versions/` | DB migration scripts |

**Key files:**
- `main.py` — FastAPI app, lifespan (queue + DB init), CORS, HTTPS redirect
- `security.py` — JWT auth, `get_current_user`/`get_current_admin` dependencies
- `database.py` — SQLAlchemy async engine, session factory, `init_db()`
- `models.py` — ORM models (Workshop > Line > Printer, Product, PrintJob, User, etc.)
- `services/print_queue.py` — Async print queue with retries and printer locking
- `helpers/printers.py` — Placeholder substitution, cyrillic→HEX conversion, TCP send/status helpers (shared by queue + preview)
- `helpers/printer_drivers.py` — Printer type registry (driver per type: status/clear/restart, batch send, mileage gate, buffer control)

## Code Conventions

- **Language:** All comments, docstrings, log messages, UI text, and README are in **Russian**
- **Auth:** JWT tokens in cookies, Argon2 password hashing, 3 roles: admin/editor/user
- **DB:** SQLAlchemy 2.x async (`AsyncSession`, `async_sessionmaker`), all DB access via `get_db()` dependency
- **Naming:** Russian variable names in UI/logic, English in DB schemas; files use English names
- **Templates:** Jinja2 with custom date filters in `templates_config.py`
- **No linting/formatting/type-checking tools** are configured — no ruff, mypy, flake8, black, or pytest
- **No CI/CD** — no GitHub Actions, no Docker setup
- **Testing convention:** any new functionality must be covered by tests to catch regressions. When a function's expected behavior changes significantly, update its tests accordingly. Bug fixes must add a test that reproduces the bug and verifies it's gone (no regression). pytest is in requirements.txt; see existing `test_*.py` / `__pycache__` files for the style

## Gotchas

- **Cyrillic in ZPL:** Converted to HEX (`_XX`) by `helpers/printers.py:replace_cyrillic_in_zpl()`, applied **only at print time** (`services/print_queue.py:260`). `substitute_placeholders()` (same file) does placeholder substitution and is shared by preview + printing. The Labelary preview does NOT apply the cyrillic conversion — it sends raw UTF-8
- **Preview rendering:** Two endpoints — Labelary API (`/templates/preview/render`) and local zebrash binary (`/templates/preview/render_local`). The binary is committed at `bin/zebrash-renderer` and is the default `ZEBRASH_BINARY` (`config.py`), so `render_local` works offline without setup
- **Print queue:** `PRINTER_WORKERS` env var (default 1); same printer = sequential execution, different printers = parallel
- **Batch sending:** Labels are sent in batches of `batch_size` for all driver types (TSC and ZPL); at most `buffer_limit` labels are kept "ahead" of actual printing — TSC gates by mileage (`~!@`), ZPL by formats-in-buffer (`~HS eee`)
- **Progress persistence:** `printed_count` is committed once per batch for batch drivers, every `PROGRESS_COMMIT_EVERY` (25) labels for continuous — resume after a failure starts from that saved counter, not from the first label
- **Alembic revision names:** use ASCII-only in `-m "..."` on Windows — Cyrillic mangles the generated filename (see the garbled `1805bce1d329_убрано...` revision in `alembic/versions/`); all newer revisions are ASCII
- **Timezones:** all ORM timestamp columns use the `MoscowDateTime` TypeDecorator (`datetime_types.py`) — the DB stores UTC, reads come back converted to Europe/Moscow (naive values are assumed UTC). Don't compare ORM timestamps against naive `datetime.now()`; reuse the decorator for new timestamp columns
- **Queue is in-memory only:** tasks live in an `asyncio.Queue` inside `PrinterQueue` — a service restart drops queued/in-flight tasks and **nothing re-enqueues** `pending`/`processing` rows from the DB, so they stay stuck. External DataMatrix codes are fetched at job creation and held only on the in-memory `PrintTask` (`routers/print_job.py`), not persisted
- **Printer command references:** Zebra ZPL and TSC datasheets are committed as PDFs under `static/documents/` — check them before changing driver commands in `helpers/printers.py` / `helpers/printer_drivers.py`
- **Access control:** a user's reachable printers are derived from `WorkshopUser` bindings (workshop/line); the special workshop literally named `Все цеха` grants access to all printers (matched by name in `routers/print_job.py`)
- **Expiration date:** Computed automatically as `marking_date + product.date_expiration` — don't set manually
- **Template `^XZ`:** Appended automatically if missing from ZPL template
- **UIP (DataMatrix):** Always 32 chars: GTIN(14) + date(6) + article + serial(12); `uip_include_batch` flag on template controls batch vs zeros
- **External DataMatrix codes:** template flag `is_print_gtin_unit` — before printing, codes are fetched from `DATAMATRIX_SERVICE_URL` (see `services/datamatrix_service.py`), substituted into `{datamatrix}` placeholder; print is cancelled with an error if codes are missing/insufficient
