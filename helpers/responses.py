# helpers/responses.py

from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import status


def ajax_or_redirect(
        endpoint: str,
        is_ajax: bool,
        success: bool,
        message: str,
        template_data: dict = None,
        error_code: int = status.HTTP_400_BAD_REQUEST,
        wrap_key: str = None  # Оборачиваем data в {wrap_key: data}
):
    """Универсальный ответ для AJAX (JSON) или Redirect (формы)."""
    if is_ajax:
        content = {'success': success}

        if success:
            content['message'] = message
        else:
            content['error'] = message

        # Добавляем данные: либо напрямую, либо в обёртке.
        if template_data:
            if wrap_key:
                content[wrap_key] = template_data
            else:
                content.update(template_data)

        return JSONResponse(
            status_code=status.HTTP_200_OK if success else error_code,
            content=content
        )

    return RedirectResponse(
        url=f'{endpoint}?{"success" if success else "error"}={message}',
        status_code=status.HTTP_303_SEE_OTHER
    )