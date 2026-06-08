# routers/api/zpl_db.py

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import status as fast_api_status

import models
from crud.zpl import create_zpl_code
from database import get_db
from models import ZPLCode

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from processing_tool import ProcessingToolZPL
from schemas import PrintRequest, ZPLCodeResponse, ZPLCodeCreate
from security import get_current_admin

router = APIRouter()

logger = logging.getLogger(__name__)
tool = ProcessingToolZPL()

ZPL_TEMPLATE = """
^XA
^CI28
^PW800
^LL600
^FO50,50^A0N,30^FDПродукт: {product_name}^FS
^FO50,100^A0N,30^FDПартия: {batch}^FS
^FO50,150^A0N,30^FDМаркировка: {marking_date}^FS
^FO50,200^A0N,30^FDГоден до: {expiration_date}^FS
^FO50,250^A0N,30^FDКоробка №{box_number}^FS
^XZ
"""


@router.post("/api/print/{zpl_code_id}")
async def print_zpl_code(
        zpl_code_id: UUID,
        request: PrintRequest,
        db: AsyncSession = Depends(get_db)
):
    """
    Печать этикеток по указанному шаблону.
    """
    # Валидация количества
    if request.quantity <= 0 or request.quantity > 1000:
        raise HTTPException(
            status_code=400,
            detail=f"Некорректное количество коробок: {request.quantity} (допустимо: 1–1000)"
        )

    # Получение шаблона из БД
    result = await db.execute(select(ZPLCode).where(ZPLCode.id == zpl_code_id))
    zpl_template = result.scalar_one_or_none()

    if not zpl_template:
        raise HTTPException(status_code=404, detail="Шаблон ZPL не найден")

    # Генерация команд
    zpl_commands = []
    for i in range(request.quantity):
        box_number = request.start_box_number + i
        box_string = f""
        rendered_zpl = zpl_template.zpl_code.format(
            batch=request.batch,
            marking_date=request.marking_date,
            expiration_date=request.expiration_date,
            box_number=box_number
        )
        zpl_commands.append(rendered_zpl)

    # Отправка на принтер
    success = tool.send_to_printer(
        zpl_commands=zpl_commands,
        ip=request.printer_ip,
        port=request.printer_port
    )

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Не удалось отправить команды на принтер"
        )

    return {
        "status": "success",
        "message": "Команды на печать успешно отправлены",
        "printed": request.quantity,
        "printer": f"{request.printer_ip}:{request.printer_port}",
        "template_id": str(zpl_code_id)
    }

@router.post("/api/add-zpl-code", response_model=ZPLCodeResponse)
async def add_zpl_code(
        zpl_data: ZPLCodeCreate,
        current_user: models.User = Depends(get_current_admin),
        db: AsyncSession = Depends(get_db)
):
    try:
        return await create_zpl_code(zpl_data, db)

    except ValueError as e:
        print('Возникает ошибка!')
        raise HTTPException(
            status_code=fast_api_status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
