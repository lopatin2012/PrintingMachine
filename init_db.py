# init_db.py
"""
Первоначальная инициализация базы данных.
"""

import asyncio
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    logger.info('Запуск инициализации базы данных..')

    from database import engine, init_db

    try:
        await init_db(engine)
        logger.info('База данных успешно инициализирована')
    except Exception as e:
        logger.error(f'Ошибка инициализации базы данных: {e}')

if __name__ == '__main__':
    asyncio.run(main())
