# migrate.py
"""
Умная накатка миграций БД (alembic).

Запуск: python migrate.py (из любого каталога, обязательно venv-питоном)

Решает три ситуации:
  1. Пустая БД (таблиц нет) — создаёт полную актуальную схему через init_db
     и помечает alembic на head.
  2. БД восстановлена из дампа / создана вручную (таблицы есть, а таблицы
     alembic_version нет) — по маркерам схемы определяет, какой ревизии
     соответствует БД, делает alembic stamp на эту ревизию и применяет
     оставшиеся миграции. Это убирает ошибку
     "отношение products уже существует".
  3. Обычная БД с alembic_version — просто применяет миграции до head.

Данные при этом не удаляются: миграции только доводят схему до актуальной.
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import psycopg2
from dotenv import load_dotenv
from alembic import command
from alembic.config import Config

load_dotenv(ROOT / '.env')

DB = dict(
    user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', ''),
    host=os.getenv('DB_HOST', 'localhost'),
    port=os.getenv('DB_PORT', '5432'),
    dbname=os.getenv('DB_NAME', 'database'),
)

ALEMBIC_CFG = Config(str(ROOT / 'alembic.ini'))


# ---------------------------------------------------------------------------
# Хелперы для проверки схемы
# ---------------------------------------------------------------------------

def get_tables(cur) -> set:
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    return {r[0] for r in cur.fetchall()}


def has_column(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone() is not None


def fk_delete_rule(cur, table: str, column: str):
    cur.execute(
        """
        SELECT rc.delete_rule
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.referential_constraints rc
          ON rc.constraint_name = tc.constraint_name
         AND rc.constraint_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
          AND tc.table_name = %s AND kcu.column_name = %s
        """,
        (table, column),
    )
    row = cur.fetchone()
    return row[0] if row else None


def column_length(cur, table: str, column: str):
    cur.execute(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    row = cur.fetchone()
    return row[0] if row else None


def column_default(cur, table: str, column: str):
    cur.execute(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Определение ревизии по маркерам схемы
# ---------------------------------------------------------------------------
# Каждая миграция оставляет в схеме отличительный маркер. Проверяем от head
# вниз и возвращаем первую (самую позднюю) ревизию, которой схема соответствует.

def detect_schema_revision(cur) -> str:
    tables = get_tables(cur)
    if 'printers' not in tables:
        return 'bfd9a6d5bfd3'

    # head: печать DataMatrix-кодов из внешнего сервиса (is_print_gtin_unit).
    if has_column(cur, 'code_templates', 'is_print_gtin_unit'):
        return 'a7b8c9d0e1f2'
    # head: партия в УИП выключена по умолчанию (server_default = false).
    if has_column(cur, 'code_templates', 'uip_include_batch') \
            and column_default(cur, 'code_templates', 'uip_include_batch') == 'false':
        return 'a6b7c8d9e0f1'
    if has_column(cur, 'printers', 'buffer_limit') and has_column(cur, 'printers', 'batch_size'):
        return 'a5b6c7d8e9f0'
    if has_column(cur, 'printers', 'printer_type'):
        return 'a4b5c6d7e8f9'
    if has_column(cur, 'code_templates', 'uip_include_batch'):
        return 'a3b4c5d6e7f8'                       # = 1805bce1d329 (без изменений схемы)
    if has_column(cur, 'products', 'article'):
        return 'a2b3c4d5e6f7'                       # current_code_1c -> article
    if has_column(cur, 'products', 'gtin_unit'):
        return 'a1b2c3d4e5f6'
    if has_column(cur, 'users', 'role_id') and fk_delete_rule(cur, 'users', 'role_id') == 'SET NULL':
        return 'fe21ba439272'                       # = c9dd5dc70482 (структурно)
    if has_column(cur, 'code_templates', 'printer_id') and fk_delete_rule(cur, 'code_templates', 'printer_id') == 'CASCADE':
        return 'cab6df366dc0'
    if 'print_jobs' in tables:
        if fk_delete_rule(cur, 'print_jobs', 'product_id') == 'CASCADE':
            return 'd0f1a83e977d'
        return '36629821b5af'
    if has_column(cur, 'workshop_users', 'workshop_id'):
        return '95fb1c828ec9'
    if column_length(cur, 'printers', 'ip_address') == 45:
        return '6acd694e7127'
    return 'bfd9a6d5bfd3'


# ---------------------------------------------------------------------------
# Основной сценарий
# ---------------------------------------------------------------------------

def main() -> int:
    print(f'БД: {DB["host"]}:{DB["port"]}/{DB["dbname"]}')

    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor()
    try:
        tables = get_tables(cur)
        if not tables:
            # --- 1. Пустая БД: полная схема через init_db + stamp head ---
            print('БД пуста — создаю полную актуальную схему (init_db)...')
            from database import engine, init_db
            asyncio.run(init_db(engine))
            command.stamp(ALEMBIC_CFG, 'head')
            print('Схема создана, alembic помечен на head. Готово.')
            return 0

        # Есть ли таблица alembic_version с записью?
        has_version = 'alembic_version' in tables
        if has_version:
            cur.execute('SELECT count(*) FROM alembic_version')
            has_version = cur.fetchone()[0] > 0

        if not has_version:
            # --- 2. БД без alembic_version (дамп / ручное создание) ---
            rev = detect_schema_revision(cur)
            print(f'Таблицы уже существуют, alembic_version нет.')
            print(f'По маркерам схемы определена ревизия: {rev}')
            print('Делаю alembic stamp на эту ревизию...')
            command.stamp(ALEMBIC_CFG, rev)
        else:
            print('alembic_version есть — применяю недосающие миграции...')

        command.upgrade(ALEMBIC_CFG, 'head')
        print('Все миграции применены (head). Готово.')
        return 0
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
