# routers/preview_barcode.py

import logging
import os
from io import BytesIO

from fastapi import APIRouter, HTTPException, Request, Response, Depends, status, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import httpx

from PIL import Image, ImageDraw, ImageFont

import models

from pathlib import Path

from security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

BASE_DIR = Path(__file__).parent.parent

# Шаблоны
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@router.get('/zpl_preview_page', response_class=HTMLResponse)
async def zpl_preview_page(
        request: Request,
        user: models.User = Depends(get_current_user)
):
    return templates.TemplateResponse(
        "preview.html",
        {"request": request, "user": user}
    )

def generate_local_preview(zpl_code: str) -> Image.Image:
    """Генерация локального изображения этикетки без интернета"""
    width_px = 4 * 203
    height_px = 6 * 203
    img = Image.new('RGB', (width_px, height_px), 'white')
    draw = ImageDraw.Draw(img)

    # Извлечение текста из команд ^FD
    lines = []
    for line in zpl_code.split('^FD'):
        if '^FS' in line:
            text = line.split('^FS')[0].strip()
            # Ограничение на длину строки
            if text and len(text) < 100:
                lines.append(text[:50])

    # Если текст не найден — показываем заглушку
    if not lines:
        lines = [
            "ЛОКАЛЬНЫЙ ПРЕДПРОСМОТР",
            "(без интернета)",
            "Находится в разработке",
        ]

    # Рисуем текст
    try:
        # Пытаемся использовать системный шрифт
        font = ImageFont.truetype("DejaVuSans.ttf", 40)
    except:
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except:
            try:
                font = ImageFont.truetype("Arial.ttf", 40)  # Windows
            except:
                font = ImageFont.load_default()

    y_offset = 100
    for line in lines[:8]:  # Максимум 8 строк
        draw.text((100, y_offset), line, fill='black', font=font)
        y_offset += 60

    # Добавляем рамку этикетки
    draw.rectangle([50, 50, width_px - 50, height_px - 50], outline='gray', width=3)

    return img


@router.post('/zpl_render_labelary')
async def zpl_render_labelary(data: dict, offline: bool = Query(False)):
    zpl = data.get('zpl', '').strip()
    if not zpl:
        raise HTTPException(status_code=400, detail='ZPL код отсутствует!')

    # Локальный режим (без интернета)
    if offline or os.getenv('OFFLINE_MODE', 'False').lower() == 'true':
        try:
            img = generate_local_preview(zpl)
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            return Response(content=buffer.getvalue(), media_type='image/png')
        except Exception as e:
            logger.error(f'Ошибка локальной генерации изображения: {e}')
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f'Ошибка локальной генерации: {str(e)}'
            )

    # Онлайн-режим через Labelary API
    dpmm = '8dpmm'  # 203 DPI
    width_in = '4'
    height_in = '6'
    idx = '0'
    url = f"http://api.labelary.com/v1/printers/{dpmm}/labels/{width_in}x{height_in}/{idx}/"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                content=zpl,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
    except httpx.RequestError as e:
        logger.warning(f'Labelary API недоступен: {e}')
        # Автоматический переход на локальный режим
        try:
            img = generate_local_preview(zpl)
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            return Response(
                content=buffer.getvalue(),
                media_type='image/png',
                headers={'X-Preview-Source': 'local-fallback'}
            )
        except Exception as fallback_error:
            logger.error(f'Ошибка локального рендеринга после падения API: {fallback_error}')
            raise HTTPException(
                status_code=500,
                detail='Сервис недоступен, локальный рендеринг также не удался'
            )

    if response.status_code != 200:
        logger.warning(f'Ошибка Labelary API {response.status_code}: {response.text}')
        # Переход на локальный режим при ошибке API
        try:
            img = generate_local_preview(zpl)
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            return Response(
                content=buffer.getvalue(),
                media_type='image/png',
                headers={'X-Preview-Source': 'local-fallback'}
            )
        except Exception as fallback_error:
            logger.error(f'Ошибка локального рендеринга после ошибки API: {fallback_error}')
            raise HTTPException(
                status_code=502,
                detail=f'Ошибка сервиса рендеринга: {response.status_code}'
            )

    return Response(content=response.content, media_type='image/png')