# routers/print_job.py

import logging
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Request, Depends, HTTPException, status, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

from database import get_db
from crud.print_job import PrintJobCRUD
from crud.workshop_user import WorkshopUserCRUD
from crud.product import ProductCRUD
from crud.printer import PrinterCRUD
from crud.code_template import CodeTemplateCRUD
from schemas import PrintJobCreate
from models import User, Workshop, Line, PrintJob, WorkshopUser, Product, Printer, CodeTemplate
from services.print_queue import PrintTask

from templates_config import templates
from security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=['printing'])
print_job_crud = PrintJobCRUD()
workshop_user_crud = WorkshopUserCRUD()
product_crud = ProductCRUD()
printer_crud = PrinterCRUD()
template_crud = CodeTemplateCRUD()

# ─── ЭНДПОИНТЫ ───────────────────────────────────────────────────────────────

@router.get('/printing', response_class=HTMLResponse)
async def printing_page(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Страница печати этикеток"""
    workshop_access = await db.execute(
        select(WorkshopUser).where(
            WorkshopUser.user_id == current_user.id,
            WorkshopUser.is_active == True
        )
    )
    user_workshops = workshop_access.scalars().all()

    if not user_workshops:
        return templates.TemplateResponse(
            'print_jobs.html',
            {
                'request': request,
                'user': current_user,
                'has_access': False,
                'error': 'У вас нет доступа к цехам. Обратитесь к администратору.'
            }
        )

    workshop_ids = [wu.workshop_id for wu in user_workshops]
    line_ids = [wu.line_id for wu in user_workshops if wu.line_id]

    printer_query = select(Printer.id).join(Line, Printer.line_id == Line.id)
    if line_ids:
        printer_query = printer_query.where(Line.id.in_(line_ids))
    else:
        printer_query = printer_query.where(Line.workshop_id.in_(workshop_ids))
    printer_ids = (await db.execute(printer_query)).scalars().all()

    products_query = (
        select(Product)
        .join(CodeTemplate, Product.id == CodeTemplate.product_id)
        .where(CodeTemplate.printer_id.in_(printer_ids), CodeTemplate.is_active == True)
        .order_by(desc(Product.created_at))
        .distinct()
    )
    products = (await db.execute(products_query)).scalars().all()

    # Если пользователь админ, то отображать все задания, иначе только пользователя.
    is_admin = current_user.role.is_admin
    user_jobs = await (
        print_job_crud.get_all_user_jobs(db)
        if is_admin else
        print_job_crud.get_user_jobs(db, current_user.id, limit=15)
    )

    return templates.TemplateResponse(
        'print_jobs.html',
        {
            'request': request,
            'user': current_user,
            'has_access': True,
            'products': products,
            'user_jobs': user_jobs,
            'search_query': request.query_params.get('search', ''),
            'success': request.query_params.get('success'),
            'error': request.query_params.get('error'),
        }
    )


@router.post('/printing/start')
async def start_printing(
        request: Request,
        product_id: UUID = Form(...),
        template_id: UUID = Form(...),
        printer_id: UUID = Form(...),
        batch_number: str = Form(...),
        marking_date: date = Form(...),
        first_box: int = Form(...),
        last_box: int = Form(...),
        gtin: str = Form(''),
        gtin_unit: str = Form(''),
        article: str = Form(''),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """Запуск реальной печати этикеток."""
    if first_box > last_box:
        raise HTTPException(status_code=400, detail="Номер первой коробки не может быть больше последней")

    product = await product_crud.get(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Продукт не найден")

    # Проверяем доступ пользователя к запрошенному принтеру
    workshop_access = await db.execute(
        select(WorkshopUser).where(
            WorkshopUser.user_id == current_user.id,
            WorkshopUser.is_active == True
        )
    )
    user_workshops = workshop_access.scalars().all()
    if not user_workshops:
        raise HTTPException(status_code=403, detail="У вас нет доступа к цехам")

    workshop_ids = [wu.workshop_id for wu in user_workshops]
    line_ids = [wu.line_id for wu in user_workshops if wu.line_id]

    # Проверяем, есть ли у пользователя доступ «Все цеха»
    workshops_result = await db.execute(
        select(Workshop).where(Workshop.id.in_(workshop_ids))
    )
    workshops = workshops_result.scalars().all()
    has_all_workshops = any(w.name == 'Все цеха' for w in workshops)

    # Проверяем, что выбранный принтер доступен пользователю
    printer_access_query = (
        select(Printer)
        .join(Line, Printer.line_id == Line.id)
        .where(Printer.id == printer_id)
    )
    if not has_all_workshops:
        if line_ids:
            printer_access_query = printer_access_query.where(Line.id.in_(line_ids))
        else:
            printer_access_query = printer_access_query.where(Line.workshop_id.in_(workshop_ids))

    printer = (await db.execute(printer_access_query)).scalar_one_or_none()
    if not printer:
        raise HTTPException(status_code=403, detail="Принтер недоступен или не найден")

    # Ищем шаблон для выбранного принтера и продукта.
    template = await template_crud.get(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Выбранный шаблон не найден")
    if not template.is_active:
        raise HTTPException(status_code=400, detail="Выбранный шаблон не активен")
    if template.product_id != product_id:
        raise HTTPException(status_code=400, detail="Шаблон не принадлежит выбранному продукту")

    expiration_date = marking_date + timedelta(days=product.date_expiration)
    boxes_count = last_box - first_box + 1

    print_job_data = PrintJobCreate(
        user_id=current_user.id,
        product_id=product_id,
        printer_id=printer_id,
        template_id=template.id,
        batch_number=batch_number.strip(),
        marking_date=marking_date,
        first_box=first_box,
        last_box=last_box,
        boxes_count=boxes_count,
        expiration_date=expiration_date,
        status='pending'
    )
    print_job = await print_job_crud.create(db, print_job_data)
    await db.commit()

    print_task = PrintTask(
        job_id=print_job.id,
        zpl_code=template.print_code,
        printer_ip=printer.ip_address,
        printer_port=printer.port_address,
        printer_type=printer.printer_type,
        marking_date=marking_date,
        expiration_date=expiration_date,
        batch_number=batch_number.strip(),
        first_box=first_box,
        boxes_count=boxes_count,
        max_retries=3,
        gtin=gtin,
        gtin_unit=gtin_unit.strip(),
        article=article.strip(),
        uip_include_batch=bool(template.uip_include_batch),
    )

    printer_queue = request.app.state.printer_queue

    if not printer_queue:
        # Очередь не инициализирована (например, приложение запущено без lifespan).
        job = await print_job_crud.get(db, print_job.id)
        if job:
            job.status = 'failed'
            job.error_message = 'Очередь печати не инициализирована'
            await db.commit()
        raise HTTPException(
            status_code=503,
            detail="Очередь печати не инициализирована"
        )

    await printer_queue.enqueue(print_task)
    status_msg = f"Задание добавлено в очередь печати (принтер: {printer.name})"

    logger.info(
        f"Запущена печать: пользователь={current_user.login}, "
        f"продукт={product.name}, принтер={printer.name}, "
        f"партия={batch_number}, коробки={first_box}–{last_box} ({boxes_count} шт.)"
    )

    return RedirectResponse(
        url=f'/printing?success={status_msg}',
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post('/api/printing/jobs/{job_id}/stop')
async def stop_print_job(
        request: Request,
        job_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    job = await print_job_crud.get(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Задание не найдено")

    is_admin = current_user.role.is_admin or current_user.role.is_editor
    if job.user_id != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Нет доступа к этому заданию")

    if job.status not in ('pending', 'processing'):
        return JSONResponse({
            "success": False,
            "message": f"Задание уже завершено со статусом '{job.status}'"
        })

    printer_queue = request.app.state.printer_queue

    # Пробуем отменить через очередь
    if printer_queue and printer_queue.cancel_task(job_id):
        return JSONResponse({
            "success": True,
            "message": "Команда остановки отправлена в очередь. Задание будет остановлено после текущей этикетки."
        })

    # Если задание не нашлось в очереди — обновляем БД напрямую
    job.status = 'cancelled'
    job.error_message = 'Остановлено оператором'
    await db.commit()
    return JSONResponse({
        "success": True,
        "message": "Задание остановлено (обновление БД)."
    })


@router.get('/api/printing/jobs/user')
async def get_user_print_jobs(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Последние задания пользователя для обновления статуса."""
    if current_user is None:
        return {
            "jobs": []
        }

    is_admin = current_user.role.is_admin
    jobs = await (
        print_job_crud.get_all_user_jobs(db)
        if is_admin else
        print_job_crud.get_user_jobs(db, current_user.id, limit=20)
    )

    return {
        "jobs": [
            {
                "id": str(job.id),
                "status": job.status,
                "product_name": job.product.name if job.product else "Неизвестно",
                "batch_number": job.batch_number,
                "boxes_count": job.boxes_count,
                "printed_count": job.printed_count,
                "first_box": job.first_box,
                "last_box": job.last_box,
                "created_at": job.created_at.isoformat(),
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "error_message": job.error_message,
            }
            for job in jobs
        ]
    }


@router.get('/api/printing/jobs/active')
async def get_active_print_jobs(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    if current_user is None:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    """Все активные задания (для админа/редактора)."""
    if not (current_user.role.is_admin or current_user.role.is_editor):
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    jobs = await print_job_crud.get_active_jobs(db, limit=50)
    return {
        "jobs": [
            {
                "id": str(job.id),
                "user_login": job.user.login if job.user else "Неизвестно",
                "product_name": job.product.name if job.product else "Неизвестно",
                "printer_name": job.printer.name if job.printer else "Неизвестно",
                "batch_number": job.batch_number,
                "status": job.status,
                "boxes_count": job.boxes_count,
                "printed_count": job.printed_count,
                "first_box": job.first_box,
                "last_box": job.last_box,
                "created_at": job.created_at.isoformat(),
            }
            for job in jobs
        ]
    }


@router.get('/printing/history', response_class=HTMLResponse)
async def printing_history(
        request: Request,
        page: int = Query(1, ge=1),
        user_id: Optional[str] = Query(None),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """История заданий печати с пагинацией.

    Администратор видит задания всех пользователей (с фильтром по пользователю
    через ?user_id=...), обычный пользователь — только свои.
    """
    PAGE_SIZE = 25
    is_admin = bool(current_user.role and current_user.role.is_admin)

    # Фильтр: админ может выбрать пользователя, обычный пользователь — только себя.
    # Пустое/некорректное значение user_id трактуем как «все пользователи».
    if is_admin:
        filter_user_id = None
        if user_id:
            try:
                filter_user_id = UUID(user_id)
            except (ValueError, AttributeError, TypeError):
                filter_user_id = None
    else:
        filter_user_id = current_user.id

    base_filter = [PrintJob.user_id == filter_user_id] if filter_user_id else []

    total_count = (await db.execute(
        select(func.count(PrintJob.id)).where(*base_filter)
    )).scalar()

    total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(1, min(page, total_pages)) if total_pages > 0 else 1
    offset = (page - 1) * PAGE_SIZE

    jobs = (await db.execute(
        select(PrintJob)
        .where(*base_filter)
        .order_by(PrintJob.created_at.desc())
        .offset(offset).limit(PAGE_SIZE)
    )).scalars().all()

    # Сводка по отфильтрованным заданиям.
    total_jobs, total_boxes = (await db.execute(
        select(
            func.count(PrintJob.id),
            func.coalesce(func.sum(PrintJob.boxes_count), 0),
        ).where(*base_filter)
    )).one()

    # Список пользователей для фильтра (только для администратора).
    users = []
    if is_admin:
        users = (await db.execute(
            select(User).order_by(User.login)
        )).scalars().all()

    return templates.TemplateResponse(
        'print_jobs_history.html',
        {
            'request': request,
            'user': current_user,
            'is_admin': is_admin,
            'jobs': jobs,
            'users': users,
            'selected_user_id': str(filter_user_id) if filter_user_id else '',
            'total_jobs': total_jobs,
            'total_boxes': total_boxes,
            'page': page,
            'total_pages': total_pages,
            'total_count': total_count,
            'page_size': PAGE_SIZE,
        }
    )


@router.get('/api/printing/template/{product_id}')
async def get_active_template_for_product(
        product_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Активный шаблон для продукта с информацией о принтере."""
    workshop_access = await db.execute(
        select(WorkshopUser).where(
            WorkshopUser.user_id == current_user.id,
            WorkshopUser.is_active == True
        )
    )
    user_workshops = workshop_access.scalars().all()
    if not user_workshops:
        raise HTTPException(status_code=403, detail="Нет доступа к цехам")

    workshop_ids = [wu.workshop_id for wu in user_workshops]
    line_ids = [wu.line_id for wu in user_workshops if wu.line_id]

    printer_query = select(Printer.id).join(Line, Printer.line_id == Line.id)
    if line_ids:
        printer_query = printer_query.where(Line.id.in_(line_ids))
    else:
        printer_query = printer_query.where(Line.workshop_id.in_(workshop_ids))
    printer_ids = (await db.execute(printer_query)).scalars().all()

    template = (await db.execute(
        select(CodeTemplate)
        .options(selectinload(CodeTemplate.printer))
        .where(
            CodeTemplate.product_id == product_id,
            CodeTemplate.printer_id.in_(printer_ids),
            CodeTemplate.is_active == True
        )
        .limit(1)
    )).scalar_one_or_none()

    if not template:
        return {"template": None, "message": "Нет активного шаблона для продукта"}

    return {
        "template": {
            "id": str(template.id),
            "name": template.name,
            "printer_id": str(template.printer_id),
            "printer_name": template.printer.name if template.printer else "Неизвестный принтер",
            "printer_ip": (
                f"{template.printer.ip_address}:{template.printer.port_address}"
                if template.printer else ""
            ),
            "print_code": template.print_code,
            "uip_include_batch": bool(template.uip_include_batch),
        }
    }

@router.get('/api/printing/printers')
async def get_available_printers(
        product_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    workshop_access = await db.execute(
        select(WorkshopUser).where(
            WorkshopUser.user_id == current_user.id,
            WorkshopUser.is_active == True
        )
    )
    user_workshops = workshop_access.scalars().all()
    if not user_workshops:
        raise HTTPException(status_code=403, detail="Нет доступа к цехам")

    workshop_ids = [wu.workshop_id for wu in user_workshops]
    line_ids = [wu.line_id for wu in user_workshops if wu.line_id]

    workshops_result = await db.execute(
        select(Workshop).where(Workshop.id.in_(workshop_ids))
    )
    workshops = workshops_result.scalars().all()
    has_all_workshops = any(w.name == 'Все цеха' for w in workshops)

    from sqlalchemy.orm import selectinload as sload
    printer_query = (
        select(Printer)
        .options(sload(Printer.line))
        .join(Line, Printer.line_id == Line.id)
    )

    if not has_all_workshops:
        if line_ids:
            printer_query = printer_query.where(Line.id.in_(line_ids))
        else:
            printer_query = printer_query.where(Line.workshop_id.in_(workshop_ids))

    printers = (await db.execute(printer_query)).scalars().all()

    return {
        "printers": [
            {
                "id": str(p.id),
                "name": p.name,
                "ip_address": p.ip_address,
                "port_address": p.port_address,
                "printer_type": p.printer_type,
                "line_name": p.line.name if p.line else "—",
            }
            for p in printers
        ]
    }

@router.get('/api/printing/templates')
async def get_templates_for_product(
        product_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Получить список активных шаблонов для продукта."""
    # Проверка доступа пользователя к цехам
    workshop_access = await db.execute(
        select(WorkshopUser).where(
            WorkshopUser.user_id == current_user.id,
            WorkshopUser.is_active == True
        )
    )
    user_workshops = workshop_access.scalars().all()
    if not user_workshops:
        raise HTTPException(status_code=403, detail="Нет доступа к цехам")

    workshop_ids = [wu.workshop_id for wu in user_workshops]
    line_ids = [wu.line_id for wu in user_workshops if wu.line_id]

    # Получаем доступные принтеры.
    printer_query = select(Printer.id).join(Line, Printer.line_id == Line.id)

    workshops_result = await db.execute(select(Workshop).where(Workshop.id.in_(workshop_ids)))
    workshops = workshops_result.scalars().all()
    has_all_workshops = any(w.name == 'Все цеха' for w in workshops)

    if not has_all_workshops:
        if line_ids:
            printer_query = printer_query.where(Line.id.in_(line_ids))
        else:
            printer_query = printer_query.where(Line.workshop_id.in_(workshop_ids))

    accessible_printer_ids = (await db.execute(printer_query)).scalars().all()

    # Получаем все активные шаблоны для продукта.
    templates_query = (
        select(CodeTemplate)
        .options(selectinload(CodeTemplate.printer))
        .where(
            CodeTemplate.product_id == product_id,
            CodeTemplate.is_active == True
        )
        .order_by(CodeTemplate.name)
    )

    # Фильтруем по доступным принтерам, если есть ограничения
    if accessible_printer_ids:
        filtered_query = templates_query.where(CodeTemplate.printer_id.in_(accessible_printer_ids))
        templates = (await db.execute(filtered_query)).scalars().all()
        if not templates:
            # Fallback: если для доступных принтеров нет шаблонов, берем любые активные для продукта
            templates = (await db.execute(templates_query)).scalars().all()
    else:
        templates = (await db.execute(templates_query)).scalars().all()

    return {
        "templates": [
            {
                "id": str(t.id),
                "name": t.name,
                "printer_id": str(t.printer_id),
                "printer_name": t.printer.name if t.printer else "Неизвестный принтер",
                "print_code": t.print_code,
                "uip_include_batch": bool(t.uip_include_batch),
            }
            for t in templates
        ]
    }

__all__ = ['router']