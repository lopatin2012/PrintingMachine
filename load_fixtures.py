# load_fixtures.py
"""Загрузка JSON-фикстур (fixtures/) в БД.

Идемпотентно: продукты обновляются/создаются по артикулу, шаблоны — по id.
Ссылки в шаблонах разрешаются по артикулу продукта и имени принтера; если
продукт или принтер не найден, шаблон пропускается с предупреждением.

Запуск: python load_fixtures.py
"""

import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

FIXTURES_DIR = ROOT / 'fixtures'

DB = dict(
    user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', ''),
    host=os.getenv('DB_HOST', 'localhost'),
    port=os.getenv('DB_PORT', '5432'),
    dbname=os.getenv('DB_NAME', 'database'),
)


def _load_json(name: str):
    path = FIXTURES_DIR / name
    if not path.exists():
        raise SystemExit(f'Нет файла фикстур: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> int:
    products = _load_json('products.json')
    templates = _load_json('code_templates.json')

    conn = psycopg2.connect(**DB)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()

    # --- Продукты: upsert по артикулу -------------------------------------
    for p in products:
        cur.execute(
            """
            INSERT INTO products
                (id, article, name, gtin, gtin_unit, external_uuid,
                 other_codes_1c, date_expiration)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (article) DO UPDATE SET
                name = EXCLUDED.name,
                gtin = EXCLUDED.gtin,
                gtin_unit = EXCLUDED.gtin_unit,
                external_uuid = EXCLUDED.external_uuid,
                other_codes_1c = EXCLUDED.other_codes_1c,
                date_expiration = EXCLUDED.date_expiration
            """,
            (
                p['id'], p['article'], p['name'], p['gtin'], p.get('gtin_unit'),
                p.get('external_uuid'), p.get('other_codes_1c'),
                p['date_expiration'],
            ),
        )
    print(f'Продуктов загружено: {len(products)}')

    # --- Шаблоны: upsert по id, ссылки по артикулу/имени -------------------
    loaded = skipped = 0
    for t in templates:
        cur.execute('SELECT id FROM products WHERE article = %s',
                    (t['product_article'],))
        product_row = cur.fetchone()
        cur.execute('SELECT id FROM printers WHERE name = %s',
                    (t['printer_name'],))
        printer_row = cur.fetchone()
        if not product_row or not printer_row:
            print(f"  ПРОПУСК шаблона {t['name']!r}: "
                  f"product={t['product_article']!r}, "
                  f"printer={t['printer_name']!r} не найдены")
            skipped += 1
            continue

        cur.execute(
            """
            INSERT INTO code_templates
                (id, product_id, printer_id, print_code, name, is_active,
                 uip_include_batch, is_print_gtin_unit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                product_id = EXCLUDED.product_id,
                printer_id = EXCLUDED.printer_id,
                print_code = EXCLUDED.print_code,
                name = EXCLUDED.name,
                is_active = EXCLUDED.is_active,
                uip_include_batch = EXCLUDED.uip_include_batch,
                is_print_gtin_unit = EXCLUDED.is_print_gtin_unit
            """,
            (
                t['id'], product_row[0], printer_row[0], t['print_code'],
                t['name'], bool(t.get('is_active', True)),
                bool(t.get('uip_include_batch', False)),
                bool(t.get('is_print_gtin_unit', False)),
            ),
        )
        loaded += 1
    print(f'Шаблонов загружено: {loaded} (пропущено: {skipped})')

    conn.commit()
    cur.close()
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
