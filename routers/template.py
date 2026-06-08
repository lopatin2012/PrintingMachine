# routers/code_template.py

import logging
from uuid import UUID
from typing import Optional
import httpx

from fastapi import APIRouter, Form, Request, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from database import get_db
from crud.code_template import CodeTemplateCRUD
from crud.product import ProductCRUD
from crud.printer import PrinterCRUD
from schemas import CodeTemplateCreate, CodeTemplateUpdate
from models import User, CodeTemplate, Product, Printer

from templates_config import templates
from security import get_current_user, get_current_admin

from services.zpl_renderer import ZPLRenderError, render_zpl_preview

from helpers.responses import ajax_or_redirect
from helpers.printers import substitute_placeholders

logger = logging.getLogger(__name__)
router = APIRouter(tags=['templates'])
template_crud = CodeTemplateCRUD()
product_crud = ProductCRUD()
printer_crud = PrinterCRUD()


@router.get('/templates', response_class=HTMLResponse)
async def template_page(
        request: Request,
        product_filter: Optional[UUID] = Query(None),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Страница шаблонов печати"""
    # Получаем все шаблоны с продуктами и принтерами
    result = await db.execute(
        select(CodeTemplate)
        .join(Product, CodeTemplate.product_id == Product.id)
        .join(Printer, CodeTemplate.printer_id == Printer.id)
        .order_by(desc(CodeTemplate.created_at))
    )
    templates_list = result.scalars().all()

    # Получаем все продукты для фильтра и выпадающего списка
    products_result = await db.execute(select(Product).order_by(Product.name))
    products = products_result.scalars().all()

    # Получаем все принтеры для фильтра и выпадающего списка
    printers_result = await db.execute(select(Printer).order_by(Printer.name))
    printers = printers_result.scalars().all()

    # Параметры уведомлений
    success = request.query_params.get('success')
    error = request.query_params.get('error')

    return templates.TemplateResponse(
        'templates.html',
        {
            'request': request,
            'templates': templates_list,
            'products': products,
            'printers': printers,
            'prefill_product_id': str(product_filter) if product_filter else None,
            'user': current_user,
            'success': success,
            'error': error
        }
    )


@router.post('/templates')
async def template_create(
        request: Request,
        name: str = Form(...),
        product_id: UUID = Form(...),
        printer_id: UUID = Form(...),
        print_code: str = Form(...),
        is_active: bool = Form(True),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin),
        endpoint: str='/templates'
):
    """Добавить шаблон печати"""

    # Определяем тип запроса: AJAX или обычная форма.
    is_ajax = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or
            request.headers.get('Accept', '').startswith('application/json')
    )

    name = name.strip()
    print_code = print_code.strip()

    # Валидация наименования.
    if len(name) < 2:
        return ajax_or_redirect(
            endpoint, is_ajax, False, 'Наименование шаблона должно содержать минимум 2 символа'
        )
    if len(name) > 200:
        return ajax_or_redirect(
            endpoint, is_ajax, False, 'Наименование шаблона не должно превышать 200 символов'
        )

    # Валидация кода
    if len(print_code) < 5:
        return ajax_or_redirect(
            endpoint, is_ajax, False, 'Код шаблона должен содержать минимум 5 символов'
        )

    # Проверка существования продукта
    product = await product_crud.get(db, product_id)
    if not product:
        return ajax_or_redirect(
            endpoint,
            is_ajax,
            False,
            'Выбранный продукт не найден',
            error_code=status.HTTP_404_NOT_FOUND
        )

    # Проверка существования принтера
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        return ajax_or_redirect(
            endpoint,
            is_ajax,
            False,
            'Выбранный принтер не найден',
            error_code=status.HTTP_404_NOT_FOUND
        )

    # Проверка уникальности комбинации продукт+принтер
    result = await db.execute(
        select(CodeTemplate).where(
            CodeTemplate.product_id == product_id,
            CodeTemplate.printer_id == printer_id,
            CodeTemplate.is_active == True
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return ajax_or_redirect(
            endpoint,
            is_ajax,
            False,
             f'Активный шаблон для продукта "{product.name}" и принтера "{printer.name}" уже существует',
            error_code=status.HTTP_404_NOT_FOUND
        )

    # Создание шаблона
    template_data = CodeTemplateCreate(
        name=name,
        product_id=product_id,
        printer_id=printer_id,
        print_code=print_code,
        is_active=is_active
    )
    template = await template_crud.create(db, template_data)

    logger.info(
        f'Шаблон "{name}" создан пользователем {current_user.login} '
        f'для продукта "{product.name}" на принтере "{printer.name}"'
    )

    if is_ajax:
        template_data = {
            'id': str(template.id),
            'name': template.name,
            'product_id': str(template.product_id),
            'product_gtin': str(product.gtin),
            'printer_id': str(template.printer_id),
            'product_name': product.name,
            'printer_name': printer.name,
            'is_active': template.is_active,
            'print_code': template.print_code,
            'created_at': template.created_at.isoformat() if hasattr(template, 'created_at') else None,
        }

        return ajax_or_redirect(
            endpoint,
            is_ajax,
            True,
            'Шаблон успешно добавлен',
            template_data=template_data,
            wrap_key='template'
        )
    return ajax_or_redirect(endpoint, is_ajax, True, 'Шаблон успешно добавлен')

@router.post('/templates/{template_id}')
async def template_update(
        template_id: UUID,
        request: Request,
        name: str = Form(...),
        product_id: UUID = Form(...),
        printer_id: UUID = Form(...),
        print_code: str = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin),
        endpoint: str = '/templates'
):
    """Редактировать шаблон печати (поддержка AJAX + обычная форма)"""

    # Определяем тип запроса: AJAX или обычная форма
    is_ajax = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or
            request.headers.get('Accept', '').startswith('application/json')
    )

    # Проверка существования шаблона
    template = await template_crud.get(db, template_id)
    if not template:
        return ajax_or_redirect(
            endpoint,
            is_ajax,
            False,
            'Шаблон не найден',
            error_code=status.HTTP_404_NOT_FOUND
        )

    name = name.strip()
    print_code = print_code.strip()

    # Валидация наименования
    if len(name) < 2:
        return ajax_or_redirect(
            endpoint,
            is_ajax,
            False,
            'Наименование шаблона должно содержать минимум 2 символа',
            error_code=status.HTTP_404_NOT_FOUND
        )
    if len(name) > 200:
        return ajax_or_redirect(
            endpoint,
            is_ajax,
            False,
            'Наименование шаблона не должно превышать 200 символов'
        )

    # Валидация кода
    if len(print_code) < 5:
        return ajax_or_redirect(
            endpoint,
            is_ajax,
            False,
            'Код шаблона должен содержать минимум 5 символов'
        )

    # Проверка существования продукта
    product = await product_crud.get(db, product_id)
    if not product:
        return ajax_or_redirect(
            endpoint,
            is_ajax,
            False,
            'Выбранный продукт не найден',
            error_code=status.HTTP_404_NOT_FOUND
        )

    # Проверка существования принтера
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        return ajax_or_redirect(
            endpoint,
            is_ajax,
            False,
            'Выбранный принтер не найден',
            error_code=status.HTTP_404_NOT_FOUND
        )

    # Обновление шаблона
    template_data = CodeTemplateUpdate(
        name=name,
        product_id=product_id,
        printer_id=printer_id,
        print_code=print_code,
    )
    updated = await template_crud.update(db, template_id, template_data)

    logger.info(f'Шаблон "{template.name}" обновлён пользователем {current_user.login}')

    if is_ajax:
        data = {
            'template': {
                'id': str(updated.id),
                'name': updated.name,
                'product_id': str(updated.product_id),
                'printer_id': str(updated.printer_id),
                'is_active': updated.is_active,
                'updated_at': updated.updated_at.isoformat() if hasattr(updated, 'updated_at') else None,
            }
        }

        return ajax_or_redirect(
            endpoint,
            is_ajax,
            True,
            'Шаблон успешно обновлён',
            template_data=data,
            wrap_key='template'
        )
    return ajax_or_redirect(endpoint, is_ajax, True, 'Шаблон успешно обновлён')


@router.post('/templates/{template_id}/activate')
async def template_activate(
        template_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Активировать шаблон"""
    template = await template_crud.get(db, template_id)
    if not template:
        return RedirectResponse(
            url='/templates?error=Шаблон не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Деактивируем другие шаблоны для этой же пары продукт+принтер
    await db.execute(
        select(CodeTemplate).where(
            CodeTemplate.product_id == template.product_id,
            CodeTemplate.printer_id == template.printer_id,
            CodeTemplate.id != template_id,
            CodeTemplate.is_active == True
        )
    )
    other_templates = (await db.execute(
        select(CodeTemplate).where(
            CodeTemplate.product_id == template.product_id,
            CodeTemplate.printer_id == template.printer_id,
            CodeTemplate.id != template_id,
            CodeTemplate.is_active == True
        )
    )).scalars().all()

    for t in other_templates:
        t.is_active = False
        db.add(t)

    # Активируем текущий шаблон
    template_data = CodeTemplateUpdate(is_active=True)
    updated = await template_crud.update(db, template_id, template_data)

    logger.info(f'Шаблон "{template.name}" активирован пользователем {current_user.login}')

    return RedirectResponse(
        url='/templates?success=Шаблон активирован',
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post('/templates/{template_id}/deactivate')
async def template_deactivate(
        template_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Деактивировать шаблон"""
    template = await template_crud.get(db, template_id)
    if not template:
        return RedirectResponse(
            url='/templates?error=Шаблон не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    template_data = CodeTemplateUpdate(is_active=False)
    updated = await template_crud.update(db, template_id, template_data)

    logger.info(f'Шаблон "{template.name}" деактивирован пользователем {current_user.login}')

    return RedirectResponse(
        url='/templates?success=Шаблон деактивирован',
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post('/templates/{template_id}/delete')
async def template_delete(
        template_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Удалить шаблон"""
    template = await template_crud.get(db, template_id)
    if not template:
        return RedirectResponse(
            url='/templates?error=Шаблон не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    success = await template_crud.delete(db, template_id)

    if success:
        logger.info(f'Шаблон "{template.name}" (id={template_id}) удалён пользователем {current_user.login}')
        return RedirectResponse(
            url='/templates?success=Шаблон успешно удалён',
            status_code=status.HTTP_303_SEE_OTHER
        )
    else:
        return RedirectResponse(
            url='/templates?error=Ошибка при удалении шаблона',
            status_code=status.HTTP_303_SEE_OTHER
        )


@router.post('/templates/preview')
async def template_preview(
        request: Request,
        code: str = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Предпросмотр шаблона (рендеринг этикетки).
    В реальном приложении здесь будет использоваться библиотека для рендеринга ZPL/TSPL.
    """
    # Для демо возвращаем заглушку
    return JSONResponse({
        "success": True,
        "preview_url": "/static/images/label-preview.png",
        "width": 400,
        "height": 200,
        "message": "Предпросмотр сгенерирован (демо-режим)"
    })

@router.get('/templates/new', response_class=HTMLResponse)
async def template_new_page(
        request: Request,
        product_id: Optional[UUID] = Query(None),
        printer_id: Optional[UUID] = Query(None),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Страница создания нового шаблона с предзаполнением"""
    # Получаем все продукты и принтеры для выпадающих списков
    products = (await db.execute(select(Product).order_by(Product.name))).scalars().all()
    printers = (await db.execute(select(Printer).order_by(Printer.name))).scalars().all()

    return templates.TemplateResponse(
        'templates.html',
        {
            'request': request,
            'templates': [],  # Пустой список для новой страницы
            'products': products,
            'printers': printers,
            'user': current_user,
            'prefill_product_id': str(product_id) if product_id else None,
            'prefill_printer_id': str(printer_id) if printer_id else None,
            'is_new_template': True
        }
    )

@router.get('/templates/by-product/{product_id}', response_class=HTMLResponse)
async def templates_by_product(
        product_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Получить шаблоны для конкретного продукта"""
    # Получаем шаблоны продукта
    templates_list = (await db.execute(
        select(CodeTemplate)
        .join(Product, CodeTemplate.product_id == Product.id)
        .join(Printer, CodeTemplate.printer_id == Printer.id)
        .where(CodeTemplate.product_id == product_id)
        .order_by(CodeTemplate.name)
    )).scalars().all()

    # Получаем все продукты и принтеры для фильтров
    products = (await db.execute(select(Product).order_by(Product.name))).scalars().all()
    printers = (await db.execute(select(Printer).order_by(Printer.name))).scalars().all()

    # Получаем сам продукт для заголовка
    product = await product_crud.get(db, product_id)

    return templates.TemplateResponse(
        'templates.html',
        {
            'request': request,
            'templates': templates_list,
            'products': products,
            'printers': printers,
            'user': current_user,
            'product_filter': str(product_id),
            'page_title': f'Шаблоны для продукта: {product.name}' if product else 'Шаблоны продукта'
        }
    )


@router.get('/api/templates/product/{product_id}')
async def get_templates_by_product(
        product_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Получить список шаблонов для продукта (для модального окна)"""
    # Получаем шаблоны с принтерами
    result = await db.execute(
        select(CodeTemplate)
        .join(Printer, CodeTemplate.printer_id == Printer.id)
        .where(CodeTemplate.product_id == product_id)
        .order_by(CodeTemplate.name)
    )
    result_templates = result.scalars().all()

    # Формируем ответ для фронтенда
    templates_data = [
        {
            "id": str(t.id),
            "name": t.name,
            "is_active": t.is_active,
            "printer_name": t.printer.name if t.printer else "Неизвестный принтер",
            "created_at": t.created_at.isoformat()
        }
        for t in result_templates
    ]

    return {
        "success": True,
        "product_id": str(product_id),
        "templates": templates_data,
        "count": len(templates_data)
    }


@router.post('/templates/preview/render')
async def render_template_preview(
        request: Request,
        zpl_code: str = Form(...),
        batch_number: str = Form('01'),
        marking_date: str = Form('260305'),   # формат YYMMDD
        expiration_date: str = Form(''),      # формат YYMMDD, если пусто — вычисляется +7 дней
        first_box: int = Form(1),
        current_box: int = Form(1),
        gtin: str = Form(''),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Рендеринг предпросмотра шаблона с подстановкой значений.

    Формат дат: YYMMDD (например, 260305 = 05.03.2026).
    Срок годности (expiration_date) необязателен — если не передан,
    вычисляется как дата маркировки + 7 дней (для предпросмотра).
    """
    from datetime import datetime, timedelta

    try:
        # ── Парсим marking_date из YYMMDD → объект date
        md = marking_date.strip()[:6]
        try:
            marking_dt = (
                datetime.strptime(md, '%d%m%y').date()
                if len(md) == 6
                else datetime.today().date()
            )
        except ValueError:
            marking_dt = datetime.today().date()

        # ── expiration_date: если не передан или пустой — +7 дней
        ed = (expiration_date or '').strip()[:6]

        try:
            expiration_dt = (
                datetime.strptime(ed, '%d%m%y').date()
                if len(ed) == 6
                else marking_dt + timedelta(days=7)
            )
        except ValueError:
            expiration_dt = marking_dt + timedelta(days=7)

        preview_code = substitute_placeholders(
            zpl_code,
            batch_number=batch_number,
            marking_date=marking_dt,
            expiration_date=expiration_dt,
            current_box=current_box,
            gtin=gtin
        )

        # Добавляем ^XZ если отсутствует (обязательная команда завершения этикетки ZPL)
        if not preview_code.strip().endswith('^XZ'):
            preview_code = preview_code.strip() + '\n^XZ'

        # Значения размеров по умолчанию.
        pw = 5
        ll = 5

        # Поиск размеров в коде ZPL.
        for i in zpl_code.split('\n'):
            try:
                if '^PW' in i:
                    pw = max([min([int(i.replace('^PW', '')) // 200, 10]), 5])
                if '^LL' in i:
                    ll = max([min([int(i.replace('^LL', '')) // 200, 10]), 5])
            except ValueError:
                pw = 5
                ll = 5

        # Отправка на рендеринг через существующий эндпоинт
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f'http://api.labelary.com/v1/printers/8dpmm/labels/{pw}x{ll}/0/',
                content=preview_code.encode('utf-8'),
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )

        if response.status_code == 200:
            return Response(content=response.content, media_type='image/png')
        else:
            # При ошибке возвращаем локальную заглушку с информацией об ошибке
            from PIL import Image, ImageDraw, ImageFont
            from io import BytesIO

            img = Image.new('RGB', (400, 300), 'white')
            draw = ImageDraw.Draw(img)

            try:
                font = ImageFont.truetype("DejaVuSans.ttf", 24)
            except:
                try:
                    font = ImageFont.truetype("arial.ttf", 24)
                except:
                    font = ImageFont.load_default()

            draw.text((20, 20), "Ошибка рендеринга", fill='red', font=font)
            draw.text((20, 60), f"Код ошибки: {response.status_code}", fill='black', font=font)
            draw.text((20, 100), "Проверьте корректность шаблона", fill='black', font=font)

            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)

            return Response(content=buffer.getvalue(), media_type='image/png')

    except Exception as e:
        logger.error(f'Ошибка рендеринга предпросмотра: {e}')
        raise HTTPException(
            status_code=500,
            detail=f'Ошибка генерации предпросмотра: {str(e)}'
        )

@router.post('/templates/preview/render_local')
async def render_template_preview_local(
        request: Request,
        zpl_code: str = Form(...),
        batch_number: str = Form('01'),
        marking_date: str = Form(''),
        first_box: int = Form(1),
        current_box: int = Form(1),
        current_user: dict = Depends(get_current_user),
):
    """
    Генерирует PNG-превью этикетки по ZPL-коду.
    Работает полностью оффлайн через zebrash/zebrafy.
    """
    try:
        params = {
            'batch_number': batch_number,
            'marking_date': marking_date,
            'first_box': first_box,
            'current_box': current_box,
            'total_boxes': first_box,  # можно расширить логику
            # Размеры этикетки можно брать из шаблона или передавать отдельно
            'width_mm': 101.6,
            'height_mm': 152.4,
            'dpmm': 8,
        }

        png_bytes = await render_zpl_preview(
            zpl_code=zpl_code,
            params=params,
            use_zebrash=True  # Можно сделать настраиваемым
        )

        return Response(
            content=png_bytes,
            media_type='image/png',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'X-Render-Engine': 'zebrash',  # Для отладки
            }
        )

    except ZPLRenderError as e:
        logger.error(f"Ошибка рендеринга превью: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Ошибка генерации превью: {str(e)}"
        )
    except Exception as e:
        logger.exception("Неожиданная ошибка при рендеринге превью")
        raise HTTPException(
            status_code=500,
            detail="Внутренняя ошибка сервера при генерации превью"
        )