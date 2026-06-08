# routers/product.py

import logging
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, desc

from database import get_db
from crud.product import ProductCRUD
from schemas import ProductCreate, ProductUpdate
from models import User, Product

# Константы
from helpers.pagination import DEFAULT_PAGE, DEFAULT_PER_PAGE, MAX_PER_PAGE

from templates_config import templates
from security import get_current_user, get_current_admin


logger = logging.getLogger(__name__)
router = APIRouter(tags=['products'])
product_crud = ProductCRUD()

# Локальные функции.

def _build_pagination_query(
        search: Optional[str] = None,
        expiration_filter: Optional[str] = None
):
    """Базовый запрос по фильтрам."""
    query = select(Product)

    if search:
        search_lower = search.lower().strip()
        query = query.where(
            (func.lower(Product.name).contains(search_lower)) |
            (func.lower(Product.current_code_1c).contains(search_lower)) |
            (func.lower(Product.gtin).contains(search_lower)) |
            (func.lower(Product.other_codes_1c).contains(search_lower) if Product.other_codes_1c is not None else text("false"))
        )

    if expiration_filter:
        if expiration_filter == 'lt7':
            query = query.where(Product.date_expiration < 7)
        elif expiration_filter == 'lt30':
            query = query.where(Product.date_expiration < 30)
        elif expiration_filter == 'gt30':
            query = query.where(Product.date_expiration >= 30)
        elif expiration_filter == 'gt180':
            query = query.where(Product.date_expiration >= 180)

    return query.order_by(desc(Product.created_at))


    # Генерация диапазона страниц для отображения
def _get_page_range(current: int, total: int, window: int = 5):
    """Возвращает список страниц для отображения в пагинаторе"""
    if total <= window + 2:
        return list(range(1, total + 1))

    start = max(2, current - window // 2)
    end = min(total - 1, current + window // 2)

    pages = [1]
    if start > 2:
        pages.append('...')
    pages.extend(range(start, end + 1))
    if end < total - 1:
        pages.append('...')
    if total > 1:
        pages.append(total)
    return pages


@router.get('/products', response_class=HTMLResponse)
async def product_page(
        request: Request,
        page: int = DEFAULT_PAGE,
        per_page: int = DEFAULT_PER_PAGE,
        search: Optional[str] = None,
        expiration_filter: Optional[str] = None,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Страница продуктов"""
    page = max(1, page)
    per_page = min(max(1, per_page), MAX_PER_PAGE)

    base_query = _build_pagination_query(search, expiration_filter)

    # Получение общего количества записей.
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total_items = total_result.scalar() or 0

    # Расчёт пагинации.
    total_pages = (total_items + per_page - 1) // per_page
    offset = (page - 1) * per_page

    # Если страница вне диапазона - редирект на последнюю валидную
    if page > total_pages > 0:
        from urllib.parse import urlencode
        params = {'page': total_pages}
        if per_page != DEFAULT_PER_PAGE:
            params['per_page'] = per_page
        if search:
            params['search'] = search
        if expiration_filter:
            params['expiration_filter'] = expiration_filter
        query_string = urlencode(params)
        return RedirectResponse(
            url=f'/products?{query_string}' if query_string else '/products',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Данные с пагинацией.
    paginated_query = base_query.offset(offset).limit(per_page)
    result = await db.execute(paginated_query)
    products = result.scalars().all()

    success = request.query_params.get('success')
    error = request.query_params.get('error')

    # Сохранение текущих параметров для ссылок пагинации.
    pagination_params = {
        'search': search,
        'expiration_filter': expiration_filter,
        'per_page': per_page if per_page != DEFAULT_PER_PAGE else None
    }
    pagination_params = {k: v for k, v in pagination_params.items() if v is not None}

    return templates.TemplateResponse(
        'products.html',
        {
            'request': request,
            'products': products,
            'user': current_user,
            'success': success,
            'error': error,

            # Данные пагинации
            'page': page,
            'per_page': per_page,
            'total_items': total_items,
            'total_pages': total_pages,
            'page_range': _get_page_range(page, total_pages),
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'pagination_params': pagination_params,

            # Текущие фильтры для формы
            'current_search': search or '',
            'current_expiration_filter': expiration_filter or '',
        }
    )

@router.post('/products')
async def product_create(
        request: Request,
        name: str = Form(...),
        current_code_1c: str = Form(...),
        gtin: str = Form(...),
        other_codes_1c: str = Form(None),
        date_expiration: int = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Добавить продукт"""
    name = name.strip()
    current_code_1c = current_code_1c.strip()
    gtin = gtin.strip()

    # Валидация наименования
    if len(name) < 2:
        return RedirectResponse(
            url='/products?error=Наименование продукта должно содержать минимум 2 символа',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if len(name) > 200:
        return RedirectResponse(
            url='/products?error=Наименование продукта не должно превышать 200 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация кода 1С
    if len(current_code_1c) < 1:
        return RedirectResponse(
            url='/products?error=Код 1С обязателен',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if len(current_code_1c) > 50:
        return RedirectResponse(
            url='/products?error=Код 1С не должен превышать 50 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация GTIN (13-14 цифр)
    if not gtin.isdigit() or len(gtin) not in (13, 14):
        return RedirectResponse(
            url='/products?error=GTIN должен содержать 13 или 14 цифр',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация срока годности
    if date_expiration < 0 or date_expiration > 3650:
        return RedirectResponse(
            url='/products?error=Срок годности должен быть от 0 до 3650 дней',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности кода 1С
    result = await db.execute(
        select(Product).where(func.lower(Product.current_code_1c) == func.lower(current_code_1c))
    )
    existing_by_code = result.scalar_one_or_none()
    if existing_by_code:
        return RedirectResponse(
            url=f'/products?error=Продукт с кодом 1С "{current_code_1c}" уже существует',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности GTIN
    result = await db.execute(
        select(Product).where(func.lower(Product.gtin) == func.lower(gtin))
    )
    existing_by_gtin = result.scalar_one_or_none()
    if existing_by_gtin:
        return RedirectResponse(
            url=f'/products?error=Продукт с GTIN "{gtin}" уже существует',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Очистка других кодов
    if other_codes_1c:
        other_codes_1c = other_codes_1c.strip() or None

    # Создание продукта
    product_data = ProductCreate(
        name=name,
        current_code_1c=current_code_1c,
        gtin=gtin,
        other_codes_1c=other_codes_1c,
        date_expiration=date_expiration
    )
    product = await product_crud.create(db, product_data)

    logger.info(
        f'Продукт "{name}" (код 1С: {current_code_1c},'
        f' GTIN: {gtin}) создан пользователем {current_user.login}'
    )

    return RedirectResponse(
        url='/products?success=Продукт успешно добавлен',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/products/{product_id}')
async def product_update(
        product_id: UUID,
        request: Request,
        name: str = Form(...),
        current_code_1c: str = Form(...),
        gtin: str = Form(...),
        other_codes_1c: str = Form(None),
        date_expiration: int = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Редактировать продукт"""
    # Проверка существования
    product = await product_crud.get(db, product_id)
    if not product:
        return RedirectResponse(
            url='/products?error=Продукт не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    name = name.strip()
    current_code_1c = current_code_1c.strip()
    gtin = gtin.strip()

    # Валидация наименования
    if len(name) < 2:
        return RedirectResponse(
            url='/products?error=Наименование продукта должно содержать минимум 2 символа',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if len(name) > 200:
        return RedirectResponse(
            url='/products?error=Наименование продукта не должно превышать 200 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация кода 1С
    if len(current_code_1c) < 1:
        return RedirectResponse(
            url='/products?error=Код 1С обязателен',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if len(current_code_1c) > 50:
        return RedirectResponse(
            url='/products?error=Код 1С не должен превышать 50 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация GTIN
    if not gtin.isdigit() or len(gtin) not in (13, 14):
        return RedirectResponse(
            url='/products?error=GTIN должен содержать 13 или 14 цифр',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация срока годности
    if date_expiration < 0 or date_expiration > 3650:
        return RedirectResponse(
            url='/products?error=Срок годности должен быть от 0 до 3650 дней',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности кода 1С (исключая текущий продукт)
    result = await db.execute(
        select(Product).where(
            func.lower(Product.current_code_1c) == func.lower(current_code_1c),
            Product.id != product_id
        )
    )
    existing_by_code = result.scalar_one_or_none()
    if existing_by_code:
        return RedirectResponse(
            url=f'/products?error=Продукт с кодом 1С "{current_code_1c}" уже существует',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности GTIN (исключая текущий продукт)
    result = await db.execute(
        select(Product).where(
            func.lower(Product.gtin) == func.lower(gtin),
            Product.id != product_id
        )
    )
    existing_by_gtin = result.scalar_one_or_none()
    if existing_by_gtin:
        return RedirectResponse(
            url=f'/products?error=Продукт с GTIN "{gtin}" уже существует',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Очистка других кодов
    if other_codes_1c:
        other_codes_1c = other_codes_1c.strip() or None

    # Обновление продукта
    product_data = ProductUpdate(
        name=name,
        current_code_1c=current_code_1c,
        gtin=gtin,
        other_codes_1c=other_codes_1c,
        date_expiration=date_expiration
    )
    updated = await product_crud.update(db, product_id, product_data)

    logger.info(f'Продукт "{product.name}" обновлён пользователем {current_user.login}')

    return RedirectResponse(
        url='/products?success=Продукт успешно обновлён',
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post('/products/{product_id}/delete')
async def product_delete(
        product_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Удалить продукт"""
    # Проверка существования
    product = await product_crud.get(db, product_id)
    if not product:
        return RedirectResponse(
            url='/products?error=Продукт не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Удаление
    success = await product_crud.delete(db, product_id)

    if success:
        logger.info(
            f'Продукт "{product.name}" (id={product_id})'
            f' удалён пользователем {current_user.login}'
        )
        return RedirectResponse(
            url='/products?success=Продукт успешно удалён',
            status_code=status.HTTP_303_SEE_OTHER
        )
    else:
        return RedirectResponse(
            url='/products?error=Ошибка при удалении продукта',
            status_code=status.HTTP_303_SEE_OTHER
        )
