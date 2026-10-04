# export_fixtures.py
"""Выгрузка данных БД в JSON-фикстуры (fixtures/).

Фикстуры удобны для переноса/резервного копирования справочников:
  * fixtures/products.json        — все продукты;
  * fixtures/code_templates.json  — все шаблоны печати (со ссылками на
                                     продукт по артикулу и принтер по имени).

Запуск: python export_fixtures.py
Загрузка обратно: python load_fixtures.py
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


def main() -> int:
    FIXTURES_DIR.mkdir(exist_ok=True)
    conn = psycopg2.connect(**DB)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, article, name, gtin, gtin_unit, external_uuid,
               other_codes_1c, date_expiration
        FROM products
        ORDER BY article
        """
    )
    products = [
        {
            'id': str(row[0]),
            'article': row[1],
            'name': row[2],
            'gtin': row[3],
            'gtin_unit': row[4],
            'external_uuid': row[5],
            'other_codes_1c': row[6],
            'date_expiration': row[7],
        }
        for row in cur.fetchall()
    ]

    cur.execute(
        """
        SELECT t.id, p.article, pr.name, t.name, t.print_code,
               t.is_active, t.uip_include_batch, t.is_print_gtin_unit
        FROM code_templates t
        JOIN products p ON p.id = t.product_id
        JOIN printers pr ON pr.id = t.printer_id
        ORDER BY p.article, t.name
        """
    )
    templates = [
        {
            'id': str(row[0]),
            'product_article': row[1],
            'printer_name': row[2],
            'name': row[3],
            'print_code': row[4],
            'is_active': bool(row[5]),
            'uip_include_batch': bool(row[6]),
            'is_print_gtin_unit': bool(row[7]),
        }
        for row in cur.fetchall()
    ]

    cur.close()
    conn.close()

    (FIXTURES_DIR / 'products.json').write_text(
        json.dumps(products, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    (FIXTURES_DIR / 'code_templates.json').write_text(
        json.dumps(templates, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )

    print(f'Продуктов: {len(products)} -> fixtures/products.json')
    print(f'Шаблонов: {len(templates)} -> fixtures/code_templates.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
