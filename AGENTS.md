# AGENTS.md

## Quick Start

```bash
# Activate venv, install deps
.venv\Scripts\activate
pip install -r requirements.txt

# Run dev server (auto-applies DB migrations, then creates roles + admin on startup)
uvicorn main:app --reload
# Swagger UI at http://localhost:8000/api/docs
# Windows-сервер: `run.bat` в корне — сам обновляет зависимости (pip install -r requirements.txt), UTF-8 в логах, порт 8111, не закрывает окно при падении

# Run tests (pure unit tests — no DB, .env, or printer needed; ~90 tests, ~3 s)
python -m pytest
# Один файл/папка:
python -m pytest tests/services/test_datamatrix_renderer.py -v
# Ниже — без активации venv:
.venv\Scripts\python.exe -m pytest
```

## Database

- PostgreSQL + asyncpg (async driver) + psycopg2 (sync, for Alembic/fixture scripts)
- Config in `.env`: `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` (no `.env.example` — `.env` is gitignored; see README for the full env reference). `.env` is auto-loaded by `load_dotenv()` inside `database.py`, `migrate.py`, `export_fixtures.py`, `load_fixtures.py` — not at app import
- Admin user created on startup from `ADMIN_LOGIN`/`ADMIN_PASSWORD`/`ADMIN_EMAIL` (defaults `admin`/`admin`)
- The service will not start without a reachable PostgreSQL: migrations run inside `lifespan` (before any request is served) and fail startup
- Migrations run automatically at service startup (subprocess `python migrate.py` in `main.py:lifespan`), then `database.py:init_db()` creates roles + admin
- Manual commands: `python -m alembic revision --autogenerate -m "..."` (create), `python -m alembic upgrade head` (apply). For a robust apply against any DB state use `python migrate.py`
- `migrate.py` covers 3 cases: (1) empty DB → builds the full schema via `init_db()` and stamps `head`; (2) DB with tables but no `alembic_version` (dump-restore) → detects the matching revision from schema markers, stamps it, then applies the rest; (3) normal DB → plain `alembic upgrade head`

## Architecture

Single-package FastAPI app — no monorepo, no separate packages.

| Directory | Purpose |
|---|---|
| `routers/` | HTTP route handlers |
| `crud/` | DB CRUD operations (per entity) |
| `services/` | Async print queue (`print_queue.py`), preview chain (`preview_renderer.py`), local ZPL→PNG renderer (`zpl_pil_renderer.py`), own DataMatrix renderer (`datamatrix_renderer.py`), external codes client (`datamatrix_service.py`), DataMatrix→PDF/TXT exports (`codes_pdf.py`, `codes_text.py`), legacy `zpl_renderer.py` |
| `helpers/` | `printers.py` (placeholder substitution, cyrillic→HEX, TCP send), `printer_drivers.py` (per-type driver registry), `responses.py`, `pagination.py` |
| `templates/` | Jinja2 HTML templates |
| `static/` | CSS/JS assets + Zebra/TSC datasheet PDFs under `static/documents/` |
| `alembic/versions/` | DB migration scripts |

**Key files:**
- `main.py` — FastAPI app, lifespan (migrations + queue + DB init), CORS, HTTPS redirect
- `security.py` — JWT auth, `get_current_user`/`get_current_admin` dependencies
- `auth_utils.py` — Argon2 password hashing (passlib)
- `database.py` — SQLAlchemy async engine, session factory, `init_db()`
- `datetime_types.py` — `MoscowDateTime` TypeDecorator for all ORM timestamps
- `models.py` — ORM models (Workshop > Line > Printer, Product, CodeTemplate, PrintJob, User, …)
- `services/print_queue.py` — Async print queue (per-printer workers, retries, cancellation, resume)
- `helpers/printers.py` — `substitute_placeholders()`, `replace_cyrillic_in_zpl()`, TCP send/status helpers (shared by queue + preview)
- `helpers/printer_drivers.py` — printer-type registry (status/clear/restart, batch send, mileage gate, buffer control)

## Tests

- Tests live under `tests/`, mirroring the source packages: `tests/services/` (8 files), `tests/helpers/`, `tests/schemas/`, `tests/auth/`. There is **no** `tests/__init__.py` (application packages are namespace packages), and pytest has no config beyond `requirements.txt` + the root `conftest.py`.
- The root `conftest.py` only puts the repo root on `sys.path`, so `from services... import ...` / `from main import app` work regardless of how pytest is launched.
- Pure unit tests — they import app modules and need no DB, `.env`, or printer (app import is side-effect free; lifespan only runs when a server/TestClient context starts). External I/O is faked (`httpx.AsyncClient` is monkeypatched), so no network / Labelary / zplr calls.
- 12 files: `tests/services/{test_codes_pdf,test_codes_text,test_datamatrix_layout,test_datamatrix_renderer,test_datamatrix_service,test_print_queue_datamatrix,test_print_queue_workers,test_zpl_pil_renderer}.py`, `tests/helpers/test_build_product_zpl.py`, `tests/schemas/test_code_template_label_type.py`, `tests/auth/{test_auth_required,test_auth_token_expiry}.py`.
- Convention: new functionality must be covered by tests; bug fixes add a regression test. When behavior changes significantly, update the existing tests.

## Fixtures

- `fixtures/products.json`, `fixtures/code_templates.json` — справочники для переноса между БД.
- `python export_fixtures.py` — БД → JSON; `python load_fixtures.py` — JSON → БД (идемпотентный upsert: продукты по артикулу, шаблоны по id; шаблоны с незнакомым продуктом/принтером пропускаются с предупреждением). Оба — psycopg2 + `.env`, без импорта приложения.

## Code Conventions

- **Language:** All comments, docstrings, log messages, UI text, and README are in **Russian**
- **Auth:** JWT tokens in cookies, Argon2 password hashing, 3 roles: admin/editor/user
- **DB:** SQLAlchemy 2.x async (`AsyncSession`, `async_sessionmaker`), all DB access via `get_db()` dependency
- **Naming:** Russian variable names in UI/logic, English in DB schemas; files use English names
- **Templates:** Jinja2 with custom date filters in `templates_config.py`
- **No linting/formatting/type-checking tools** are configured — no ruff, mypy, flake8, or black
- **No CI/CD** — no GitHub Actions, no Docker setup

## Gotchas

- **Cyrillic in ZPL:** Converted to HEX (`_XX`) by `helpers/printers.py:replace_cyrillic_in_zpl()`, applied **only at print time** (in `services/print_queue.py`). `substitute_placeholders()` (same helpers file) does placeholder substitution and is shared by preview + printing. Preview rendering does NOT apply the cyrillic conversion — it renders raw UTF-8.
- **Preview rendering:** `/templates/preview/render` (what the UI actually calls) and `/templates/preview` render PNG through a chain in `services/preview_renderer.py` (`render_preview_png()`, response header `X-Render-Engine`): **1) Labelary** (external HTTP, the look you want), **2) local `zplr`** via a Node bridge `zplr_preview_server.mjs` (geometry/barcodes like Labelary, Cyrillic via `RobotoCondensed-Bold.ttf` — **optional**: needs `node` + `npm i` for `zplr`, `skia-canvas`; skips silently if absent), **3) PIL** `render_zpl_to_png()` as guaranteed fallback. `/templates/preview/render_local` is the **legacy** route through `render_zpl_preview()` (`services/zpl_renderer.py`, tries zebrash → zebrafy → PIL). **`bin/zebrash-renderer` is NOT runnable** (a Go package archive `.a`, not an executable; running it fails) — the zebrash path is dead code, don't try to fix/run it.
- **PIL renderer (`services/zpl_pil_renderer.py`) is the offline bottom line:** covers Code128/GS1-128 via `python-barcode`, DataMatrix via `pylibdmtx`, text w/ Cyrillic (Arial), `^GB`; it does NOT draw `^GF` raster images, ignores unknown commands, and degrades unsupported barcodes to a labeled placeholder box. `^GF`/`^CI28`/`^A@` are handled by zplr/Labelary, not PIL.
- **DataMatrix is rasterized, not encoded by the printer/engines:** before preview (Labelary/zplr) the chain replaces `^BX` fields with `^GF` graphics generated by `services/datamatrix_renderer.py` (own ECC200 renderer). **При печати делается то же самое** (`services/print_queue.py:rasterize_datamatrix` → `replace_datamatrix_with_graphics`): `^BX` → `^GF` before sending to the printer, so Zebra doesn't encode the symbol (avoids empty `^BX` labels from escape chars / GS1 separators). **GS1-DataMatrix:** GS1 element strings (AI `01`+GTIN14, or an explicit ZPL escape `\1`) are encoded as GS1 Data Matrix (FNC1) via `pystrich` (pure Python Zint port) — libdmtx 0.7.4 bundled with `pylibdmtx` cannot do FNC1; the GS1 trigger is `services/datamatrix_renderer.py:is_gs1_data`.
- **Template `label_type` selects the ZPL template:** `unit` = потребительская упаковка, `group` (default) = групповая упаковка/набор. A product can have one active template per type.
- **Public ZPL endpoints (no auth):** `GET /api/printing/zpl?gtin=...` (template `group` by group GTIN) and `GET /api/printing/zpl-unit?gtin_unit=...` (template `unit` by unit GTIN) return substituted ZPL for external integration; product data comes from the DB, batch/marking_date/first_box are query params.
- **Print queue:** a queue worker is created automatically per printer (`ip:port`) when its first job is enqueued — separate `asyncio.Queue` + worker per printer; jobs on the same printer are sequential, across printers parallel. `PRINTER_WORKERS` no longer exists; printers can be added without restarting the service (`services/print_queue.py:PrinterQueue`).
- **Batch sending:** Labels are sent in batches of `batch_size` for all driver types (TSC and ZPL); at most `buffer_limit` labels are kept "ahead" of actual printing — TSC gates by mileage (`~!@`), ZPL by formats-in-buffer (`~HS eee`).
- **Progress persistence:** `printed_count` is committed once per batch for batch drivers, every `PROGRESS_COMMIT_EVERY` (25) labels for continuous — resume after a failure starts from that saved counter, not from the first label.
- **Alembic revision names:** use ASCII-only in `-m "..."` on Windows — Cyrillic mangles the generated filename (see the garbled `1805bce1d329_убрано...` revision in `alembic/versions/`); all newer revisions are ASCII.
- **Timezones:** all ORM timestamp columns use the `MoscowDateTime` TypeDecorator (`datetime_types.py`) — the DB stores UTC, reads come back converted to Europe/Moscow (naive values are assumed UTC). Don't compare ORM timestamps against naive `datetime.now()`; reuse the decorator for new timestamp columns.
- **Queue is in-memory only:** tasks live in an `asyncio.Queue` inside `PrinterQueue` — a service restart drops queued/in-flight tasks and **nothing re-enqueues** `pending`/`processing` rows from the DB, so they stay stuck. External DataMatrix codes are fetched at job creation and held only on the in-memory `PrintTask` (`routers/print_job.py`), not persisted.
- **Printer command references:** Zebra ZPL and TSC datasheets are committed as PDFs under `static/documents/` — check them before changing driver commands in `helpers/printers.py` / `helpers/printer_drivers.py`.
- **Access control:** a user's reachable printers are derived from `WorkshopUser` bindings (workshop/line); the special workshop literally named `Все цеха` grants access to all printers (matched by name in `routers/print_job.py`).
- **Expiration date:** computed automatically as `marking_date + product.date_expiration` — don't set manually.
- **Template `^XZ`:** appended automatically if missing from the ZPL template.
- **UIP (DataMatrix):** Always 32 chars: GTIN(14) + date(6) + article + serial(12); `uip_include_batch` flag on the template controls batch vs zeros.
- **External DataMatrix codes (live path):** template flag `is_print_gtin_unit` — before printing, codes are fetched by the product's external UUID (`Product.external_uuid`) via `services/datamatrix_service.py:fetch_datamatrix_codes_by_uuid()` → GET `CODES_SERVICE_URL` (default `http://127.0.0.1:8000`) + `/codes/api/get_codes_for_printer_by_product_uuid/` with `uuid_product`/`amount_codes`. One code per label is substituted into `{datamatrix}` (the queue cycles `task.datamatrix_codes[i]`). If the product has no `external_uuid`, or the service returns no/fewer codes than boxes, the job is cancelled with a warning (no blank DataMatrix printed).
- **README is stale here:** it documents the legacy `fetch_datamatrix_codes()` (POST to `DATAMATRIX_SERVICE_URL`) — that function still exists but is **not called** by the live printing path. Trust the code / this section over the README's DataMatrix chapter.
