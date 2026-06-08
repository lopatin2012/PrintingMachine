# types.py

from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.types import TypeDecorator, DateTime

moscow_tz = ZoneInfo('Europe/Moscow')

class MoscowDateTime(TypeDecorator):
    """Автоматическая конвертация datetime из UTC в Московское"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None

        # Если нужно, то конвертируем, иначе нет.
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo('UTC'))
        return value.astimezone(moscow_tz)
