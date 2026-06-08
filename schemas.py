# schemas.py
import ipaddress
from uuid import UUID
from datetime import date

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime

# ---------- Цех ----------

class WorkshopBase(BaseModel):
    """Базовая схема цеха"""
    name: str = Field(..., max_length=50, description='Наименование')

class WorkshopCreate(WorkshopBase):
    """Создание цеха"""
    pass

class WorkshopUpdate(BaseModel):
    """Обновление наименования"""
    name: Optional[str] = Field(None, max_length=50, description='Наименование')

class WorkshopInDBBase(WorkshopBase):
    """Схема с полями из БД"""
    id: UUID
    created_at: datetime = Field(..., description='Дата добавления')
    edited_at: datetime = Field(..., description='Дата редактирования')

    class Config:
        from_attributes = True

class WorkshopResponse(WorkshopInDBBase):
    """Схема ответа для цеха (без вложенных объектов)"""
    pass

# ---------- Линия ----------

class LineBase(BaseModel):
    """Базовая схема линии"""
    workshop_id: UUID = Field(..., description='UUID цеха')
    name: str = Field(..., max_length=50, description='Наименование')

class LineCreate(LineBase):
    """Создание линии"""
    pass

class LineUpdate(BaseModel):
    """Обновление линии"""
    workshop_id: Optional[UUID] = Field(None, description='UUID цеха')
    name: Optional[str] = Field(None, max_length=50, description='Наименование')

class LineInDBBase(LineBase):
    """Схема линии из БД"""
    id: UUID
    created_at: datetime = Field(..., description='Дата добавления')
    edited_at: datetime = Field(..., description='Дата редактирования')

    class Config:
        from_attributes = True

class LineResponse(LineInDBBase):
    """Линии с вложенным цехом"""
    workshop: Optional[WorkshopResponse] = Field(None, description='Цех линии')

# ---------- Принтер ----------
class PrinterBase(BaseModel):
    """Базовая схема принтера"""
    line_id: UUID = Field(..., description='UUID линии')
    name: str = Field(..., max_length=50, description='Наименование')
    ip_address: str = Field(..., max_length=45, description='IP-адрес')
    port_address: int = Field(9100, ge=1, le=65535, description='Порт')

    @field_validator('ip_address')
    @classmethod
    def validate_ip_address(cls, v: str):
        """Валидация IP-адреса"""
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError('Некорректный IP-адрес')
        return v


class PrinterCreate(PrinterBase):
    """Добавление принтера"""
    pass

class PrinterUpdate(BaseModel):
    """Обновление принтера"""
    line_id: Optional[UUID] = Field(None, description='UUID линии')
    name: Optional[str] = Field(None, max_length=50, description='Наименование')
    ip_address: str = Field(None, description='IP-адрес')
    port_address: Optional[int] = Field(None, ge=1, le=65535, description='Порт')

    @field_validator('ip_address')
    @classmethod
    def validate_ip_address(cls, v: str):
        """Валидация IP-адреса"""
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError('Некорректный IP-адрес')
        return v

class PrinterInDBBase(PrinterBase):
    """Схема принтера из БД"""
    id: UUID
    created_at: datetime = Field(..., description='Дата добавления')
    edited_at: datetime = Field(..., description='Дата редактирования')

    class Config:
        from_attributes = True

class PrinterResponse(PrinterInDBBase):
    """Ответ по принтеру с вложенной линией"""
    line: Optional[LineResponse] = Field(None, description='Линия принтера')

# ---------- Роль ----------

class RoleBase(BaseModel):
    """Базовая схема роли"""
    name: str = Field(..., max_length=50, description='Наименование')
    description: Optional[str] = Field(None, max_length=200, description='Описание')
    is_admin: bool = Field(False, description='Является админом')
    is_editor: bool = Field(False, description='Является редактором')

class RoleCreate(RoleBase):
    """Создание роли"""
    pass

class RoleUpdate(BaseModel):
    """Обновление роли"""
    name: Optional[str] = Field(None, max_length=50, description='Наименование')
    description: Optional[str] = Field(None, max_length=200, description='Описание')
    is_admin: Optional[bool] = Field(None, description='Является админом')
    is_editor: Optional[bool] = Field(None, description='Является редактором')

class RoleInDBBase(RoleBase):
    """Схема роли из БД"""
    id: UUID
    created_at: datetime = Field(..., description='Дата добавления')
    edited_at: datetime = Field(..., description='Дата редактирования')

    class Config:
        from_attributes = True

class RoleResponse(RoleInDBBase):
    """Ответ по роли"""
    pass

# ---------- Пользователь ----------

class UserBase(BaseModel):
    """Схема пользователя"""
    login: str = Field(..., max_length=100, description='Логин')
    email: Optional[str] = Field(None, max_length=100, description='E-mail')
    is_active: bool = Field(True, description='Активен')

class UserCreate(UserBase):
    """Создание пользователя"""
    password: str = Field(...,min_length=8, max_length=255, description='Пароль (минимум 8 символов)')
    role_id: UUID = Field(..., description='Роль')

class UserUpdate(BaseModel):
    """Обновление пользователя"""
    login: Optional[str] = Field(None, max_length=100, description='Логин')
    email: Optional[str] = Field(None, max_length=100, description='E-mail')
    password: Optional[str] = Field(None, max_length=255, description='Хэш пароля')
    role_id: Optional[UUID] = Field(None, description='Роль')
    is_active: Optional[bool] = Field(None, description='Активен')

class UserInDBBase(UserBase):
    """Схема пользователя из БД"""
    id: UUID
    created_at: datetime = Field(..., description='Дата добавления')
    edited_at: datetime = Field(..., description='Дата редактирования')
    role_id: UUID = Field(..., description='Роль')
    password: str = Field(..., description='Хэш пароля')

    class Config:
        from_attributes = True

class UserResponse(UserInDBBase):
    """Ответ по пользователю"""

    role: Optional[RoleResponse] = Field(None, description='Роль')

    class Config:
        from_attributes = True
        exclude = {'password'}

# ---------- Продукт ----------

class ProductBase(BaseModel):
    """Схема продукта"""
    current_code_1c: str = Field(..., max_length=50, description='Текущий код 1С')
    name: str = Field(..., max_length=200, description='Наименование')
    gtin: str = Field(..., max_length=50, description='GTIN')
    other_codes_1c: Optional[str] = Field(None, description='Другие коды 1C')
    date_expiration: int = Field(..., ge=0, description='Срок годности в днях')

class ProductCreate(ProductBase):
    """Создание продукта"""
    pass

class ProductUpdate(BaseModel):
    """Обновление продукта"""

    current_code_1c: Optional[str] = Field(None, max_length=50, description='Текущий код 1С')
    name: Optional[str] = Field(None, max_length=200, description='Наименование')
    gtin: Optional[str] = Field(None, max_length=50, description='GTIN')
    other_codes_1c: Optional[str] = Field(None, description='Другие коды 1C')
    date_expiration: Optional[int] = Field(None, ge=0, description='Срок годности в днях')

class ProductInDBBase(ProductBase):
    """Схема продукта из БД"""
    id: UUID
    created_at: datetime = Field(..., description='Дата добавления')
    edited_at: datetime = Field(..., description='Дата редактирования')

    class Config:
        from_attributes = True

class ProductResponse(ProductInDBBase):
    """Ответ по продукту"""
    pass

# ---------- Код шаблона ----------

class CodeTemplateBase(BaseModel):
    """Схема кода шаблона"""
    product_id: UUID = Field(..., description='UUID продукта')
    printer_id: UUID = Field(..., description='UUID принтера')
    name: str = Field(..., max_length=200, description='Наименование')
    print_code: str = Field(..., description='Код шаблона')
    is_active: bool = Field(True, description='Активен')

class CodeTemplateCreate(CodeTemplateBase):
    pass

class CodeTemplateUpdate(BaseModel):
    product_id: Optional[UUID] = Field(None, description='UUID продукта')
    printer_id: Optional[UUID] = Field(None, description='UUID принтера')
    name: Optional[str] = Field(None, max_length=200, description='Наименование')
    print_code: Optional[str] = Field(None, description='Код шаблона')
    is_active: Optional[bool] = Field(None, description='Активен')

class CodeTemplateInDBBase(CodeTemplateBase):
    """Код шаблона из БД"""
    id: UUID
    created_at: datetime = Field(..., description='Дата добавления')
    edited_at: datetime = Field(..., description='Дата редактирования')

    class Config:
        from_attributes = True


class CodeTemplateResponse(CodeTemplateInDBBase):
    """Ответ кода шаблона с вложенными объектами"""
    product: Optional[ProductResponse] = Field(None, description='Продукт шаблона')
    printer: Optional[PrinterResponse] = Field(None, description='Принтер шаблона')

# ---------- Пользователи цеха ----------

class WorkshopUserBase(BaseModel):
    """Схема пользователи цеха"""
    user_id: UUID = Field(..., description='UUID пользователя')
    workshop_id: UUID = Field(..., description='UUID цеха')
    line_id: Optional[UUID] = Field(None, description='UUID линии')
    role_in_workshop: str = Field('master', description='Роль в цеху: master, operator, supervisor')
    is_active: bool = Field(True, description='Активен ли доступ к цеху')
    comment: Optional[str] = Field(None, max_length=255, description='Комментарий')

    @field_validator('role_in_workshop')
    @classmethod
    def validate_role_in_workshop(cls, v: str):
        """Валидация роли"""
        allowed_roles = ['master', 'operator', 'supervisor']
        if v not in allowed_roles:
            raise ValueError(f'Роль должна быть одной из: {", ".join(allowed_roles)}')
        return v

class WorkshopUserCreate(WorkshopUserBase):
    pass

class WorkshopUserUpdate(BaseModel):
    user_id: Optional[UUID] = Field(None, description='UUID пользователя')
    workshop_id: Optional[UUID] = Field(None, description='UUID цеха')
    line_id: Optional[UUID] = Field(None, description='UUID линии')
    role_in_workshop: Optional[str] = Field(None, description='Роль в цехе')
    is_active: Optional[bool] = Field(None, description='Активен')
    comment: Optional[str] = Field(None, max_length=255, description='Комментарий')

class WorkshopUserInDBBase(WorkshopUserBase):
    id: UUID
    created_at: datetime = Field(..., description='Дата обновления')
    edited_at: datetime = Field(..., description='Дата редактирования')

    class Config:
        from_attributes = True

class WorkshopUserResponse(WorkshopUserInDBBase):
    user: Optional[UserResponse] = Field(None, description='Пользователь')
    workshop: Optional[WorkshopResponse] = Field(None, description='Цех')
    line: Optional[LineResponse] = Field(None, description='Линия')

# ---------- Задания на печать ----------

class PrintJobBase(BaseModel):
    """Базовая схема задания на печать"""
    user_id: UUID = Field(..., description='UUID пользователя')
    product_id: UUID = Field(..., description='UUID продукта')
    printer_id: UUID = Field(..., description='UUID принтера')
    template_id: UUID = Field(..., description='UUID шаблона')
    batch_number: str = Field(..., max_length=50, description='Номер партии')
    marking_date: date = Field(..., description='Дата маркировки')
    first_box: int = Field(..., ge=1, description='Номер первой коробки')
    last_box: int = Field(..., ge=1, description='Номер последней коробки')
    boxes_count: int = Field(..., ge=1, description='Количество коробок')
    status: str = Field(..., description='Статус задания')
    expiration_date: date = Field(..., description='Дата окончания срока годности')

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str):
        """Валидация роли"""
        allowed_status = ['pending', 'processing', 'pause', 'completed', 'failed', 'cancelled']
        if v not in allowed_status:
            raise ValueError(f'Статус задания должен быть одним из: {", ".join(allowed_status)}')
        return v

class PrintJobCreate(PrintJobBase):
    """Создание задания на печать"""
    pass

class PrintJobUpdate(BaseModel):
    """Обновление статуса задания"""
    status: Optional[str] = Field(None, description='Статус задания')
    error_message: Optional[str] = Field(None, description='Сообщение об ошибке')
    printed_count: Optional[int] = Field(None, description='Количество напечатанных этикеток')
    completed_at: Optional[datetime] = Field(None, description='Дата завершения')

class PrintJobInDBBase(PrintJobBase):
    """Схема задания из БД"""
    id: UUID
    status: str = Field(..., description='Статус задания')
    error_message: Optional[str] = Field(None, description='Сообщение об ошибке')
    printed_count: int = Field(0, description='Количество напечатанных этикеток')
    created_at: datetime = Field(..., description='Дата создания')
    updated_at: datetime = Field(..., description='Дата обновления')
    completed_at: Optional[datetime] = Field(None, description='Дата завершения')

    class Config:
        from_attributes = True

class PrintJobResponse(PrintJobInDBBase):
    """Ответ по заданию с вложенными объектами"""
    user: Optional[UserResponse] = Field(None, description='Пользователь')
    product: Optional[ProductResponse] = Field(None, description='Продукт')
    printer: Optional[PrinterResponse] = Field(None, description='Принтер')
    template: Optional[CodeTemplateResponse] = Field(None, description='Шаблон')

# ---------- Дополнительные схемы для вывода списков ----------

class WorkshopWithLinesResponse(WorkshopResponse):
    """Цех со списком линий"""
    lines: List[LineResponse] = Field(default_factory=list, description='Линии цеха')

class LineWithPrintersResponse(LineResponse):
    """Линии со списком принтеров"""
    printers: List[PrinterResponse] = Field(default_factory=list, description='Принтеры линии')

class PrinterWithTemplatesResponse(PrinterResponse):
    """Принтер со списком шаблонов"""
    code_templates: List[CodeTemplateResponse] = Field(default_factory=list, description='Шаблоны кодов принтера')
