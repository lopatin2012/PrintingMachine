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
- Config in `.env`: `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`
- Migrations run automatically at service startup (subprocess `python migrate.py` in `main.py:lifespan`), then `database.py:init_db()` creates roles + admin
- Manual commands: `python -m alembic revision --autogenerate -m "..."` (create), `python -m alembic upgrade head` (apply), or `python migrate.py` (smart rollback-aware)
- `migrate.py` handles empty DBs, dump-restores, and normal upgrades

## Architecture

Single-package FastAPI app — no monorepo, no separate packages.

| Directory | Purpose |
|---|---|
| `routers/` | HTTP route handlers |
| `crud/` | Database CRUD operations |
| `services/` | Async print queue (`print_queue.py`) and ZPL rendering (`zpl_renderer.py`) |
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
- `helpers/printer_drivers.py` — Printer type registry (driver per type: status/clear/restart, batch send, mileage gate, buffer control)

## Code Conventions

- **Language:** All comments, docstrings, log messages, UI text, and README are in **Russian**
- **Auth:** JWT tokens in cookies, Argon2 password hashing, 3 roles: admin/editor/user
- **DB:** SQLAlchemy 2.x async (`AsyncSession`, `async_sessionmaker`), all DB access via `get_db()` dependency
- **Naming:** Russian variable names in UI/logic, English in DB schemas; files use English names
- **Templates:** Jinja2 with custom date filters in `templates_config.py`
- **No linting/formatting/type-checking tools** are configured — no ruff, mypy, flake8, black, or pytest
- **No CI/CD** — no GitHub Actions, no Docker setup
- **No test suite** — pytest is in requirements.txt but no tests exist

## Gotchas

- **Cyrillic in ZPL:** Converted to HEX (`_XX`) in `helpers/printers.py:substitute_placeholders()` — used by both preview and actual printing
- **Preview rendering:** Two endpoints — Labelary API (`/templates/preview/render`) and local zebrash binary (`/templates/preview/render_local`); controlled by `OFFLINE_MODE` env var and `ZEBRASH_BINARY` path
- **Print queue:** `PRINTER_WORKERS` env var (default 1); same printer = sequential execution, different printers = parallel
- **Batch sending:** Labels are sent in batches of `batch_size` for all driver types (TSC and ZPL); at most `buffer_limit` labels are kept "ahead" of actual printing — TSC gates by mileage (`~!@`), ZPL by formats-in-buffer (`~HS eee`)
- **Expiration date:** Computed automatically as `marking_date + product.date_expiration` — don't set manually
- **Template `^XZ`:** Appended automatically if missing from ZPL template
- **UIP (DataMatrix):** Always 32 chars: GTIN(14) + date(6) + article + serial(12); `uip_include_batch` flag on template controls batch vs zeros
