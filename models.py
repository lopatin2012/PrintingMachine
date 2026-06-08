import uuid

from sqlalchemy import (
    Column, Integer, String, Date, Text, DateTime, func, ForeignKey, Boolean,
    UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base

from datetime_types import MoscowDateTime


class Workshop(Base):
    """Цеха."""
    __tablename__ = "workshops"
    __table_args__ = {"comment": "Цеха"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(String(50), index=True, unique=True, nullable=False, comment='Наименование')
    created_at = Column(MoscowDateTime(), server_default=func.now(), comment='Дата добавления')
    edited_at = Column(MoscowDateTime(), server_default=func.now(), onupdate=func.now(), comment='Дата редактирования')

    lines = relationship('Line', back_populates='workshop', lazy='selectin', cascade='all, delete-orphan')
    workshop_users = relationship('WorkshopUser', back_populates='workshop', lazy='selectin', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Workshop(id={self.id}, name={self.name})>'


class Line(Base):
    """Линии."""
    __tablename__ = "lines"
    __table_args__ = {"comment": "Линии"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workshop_id = Column(UUID(as_uuid=True), ForeignKey('workshops.id', ondelete='CASCADE'), nullable=False, comment='id цеха')
    name = Column(String(50), index=True, unique=True, nullable=False, comment='Наименования')
    created_at = Column(MoscowDateTime(), server_default=func.now(), comment='Дата добавления')
    edited_at = Column(MoscowDateTime(), server_default=func.now(), onupdate=func.now(), comment='Дата редактирования')

    workshop = relationship('Workshop', back_populates='lines', lazy='selectin')

    printers = relationship('Printer', back_populates='line', lazy='selectin', cascade='all, delete-orphan')
    workshop_users = relationship('WorkshopUser', back_populates='line', lazy='selectin', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Line(id={self.id}, name={self.name}, workshop_id={self.workshop_id})>'


class Printer(Base):
    """Принтеры."""
    __tablename__ = "printers"
    __table_args__ = {"comment": "Принтеры"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    line_id = Column(UUID(as_uuid=True), ForeignKey('lines.id', ondelete='CASCADE'), nullable=False, comment='id линии')
    name = Column(String(50), index=True, unique=True, nullable=False, comment='Наименование')
    ip_address = Column(String(45), index=True, unique=True, nullable=False, comment='IP-адрес')
    port_address = Column(Integer, default=9100, index=True, nullable=False, comment='Порт')
    created_at = Column(MoscowDateTime(), server_default=func.now(), comment='Дата добавления')
    edited_at = Column(MoscowDateTime(), server_default=func.now(), onupdate=func.now(), comment='Дата редактирования')

    line = relationship('Line', back_populates='printers', lazy='selectin')

    code_templates = relationship('CodeTemplate', back_populates='printer', lazy='selectin', cascade='all, delete-orphan')
    print_jobs = relationship('PrintJob', back_populates='printer', lazy='selectin', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Printer(id={self.id}, name={self.name}, ip={self.ip_address})>'


class Role(Base):
    """Роли."""
    __tablename__ = "roles"
    __table_args__ = {"comment": "Роли"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(String(50), index=True, unique=True, nullable=False, comment='Наименование')
    description = Column(String(200), nullable=True, comment='Описание')
    is_admin = Column(Boolean, default=False, comment='Админ')
    is_editor = Column(Boolean, default=False, comment='Редактирование')
    created_at = Column(MoscowDateTime(), server_default=func.now(), comment='Дата добавления')
    edited_at = Column(MoscowDateTime(), server_default=func.now(), onupdate=func.now(), comment='Дата редактирования')

    users = relationship('User', back_populates='role', lazy='selectin', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Role(id={self.id}, name={self.name})>'


class User(Base):
    """Пользователи."""
    __tablename__ = "users"
    __table_args__ = {"comment": "Пользователи"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    role_id = Column(UUID(as_uuid=True), ForeignKey('roles.id', ondelete='SET NULL'), nullable=False)
    login = Column(String(100), index=True, unique=True, nullable=False, comment='Логин')
    password = Column(String(255), nullable=False, comment='Пароль')
    email = Column(String(100), unique=True, nullable=True, comment='E-mail')
    is_active = Column(Boolean, default=True, comment='Активен')
    created_at = Column(MoscowDateTime(), server_default=func.now(), comment='Дата добавления')
    edited_at = Column(MoscowDateTime(), server_default=func.now(), onupdate=func.now(), comment='Дата редактирования')

    role = relationship('Role', back_populates='users', lazy='selectin')

    workshop_users = relationship('WorkshopUser', back_populates='user', lazy='selectin', cascade='all, delete-orphan')
    print_jobs = relationship('PrintJob', back_populates='user', lazy='selectin', cascade='all, delete-orphan')

    def __repr__(self):
        role_name = self.role.name if self.role else f'role_id={self.role_id}'
        return f'<User(id={self.id}, login={self.login}, role={role_name})>'


class Product(Base):
    """Продукты."""
    __tablename__ = "products"
    __table_args__ = {"comment": "Продукты"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    current_code_1c = Column(String(50), unique=True, nullable=False, comment='Текущий код 1С')
    name = Column(String(200), nullable=False, comment='Наименование')
    gtin = Column(String(50), unique=True, nullable=False, comment='GTIN')
    other_codes_1c = Column(Text, nullable=True, comment='Другие коды 1C')
    date_expiration = Column(Integer, nullable=False, comment='Срок годности в днях')
    created_at = Column(MoscowDateTime(), server_default=func.now())
    edited_at = Column(MoscowDateTime(), server_default=func.now(), onupdate=func.now())

    code_templates = relationship('CodeTemplate', back_populates='product', lazy='selectin', cascade='all, delete-orphan')
    print_jobs = relationship('PrintJob', back_populates='product', lazy='selectin', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Product(id={self.id}, name={self.name}, code_1c={self.current_code_1c})>'


class CodeTemplate(Base):
    """Коды шаблонов."""
    __tablename__ = "code_templates"
    __table_args__ = {"comment": "Коды шаблонов"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    product_id = Column(UUID(as_uuid=True), ForeignKey('products.id', ondelete='CASCADE'), nullable=False, comment='id продукта')
    printer_id = Column(UUID(as_uuid=True), ForeignKey('printers.id', ondelete='CASCADE'), nullable=False, comment='id принтера')
    print_code = Column(Text, nullable=False, comment='Код шаблона')
    name = Column(String(200), nullable=False, comment='Наименование')
    is_active = Column(Boolean, default=True, comment='Активен')
    created_at = Column(MoscowDateTime(), server_default=func.now(), comment='Дата добавления')
    edited_at = Column(MoscowDateTime(), server_default=func.now(), onupdate=func.now(), comment='Дата редактирования')

    printer = relationship('Printer', back_populates='code_templates', lazy='selectin')
    product = relationship('Product', back_populates='code_templates', lazy='selectin')

    print_jobs = relationship('PrintJob', back_populates='template', lazy='selectin', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<CodeTemplate(id={self.id}, name={self.name})>'


class WorkshopUser(Base):
    """Пользователи цеха."""
    __tablename__ = "workshop_users"
    __table_args__ = (
        UniqueConstraint('user_id', 'workshop_id', name='uq_workshop_user'),
        Index('ix_workshop_users_user_active', 'user_id', 'is_active'),
        Index('ix_workshop_users_workshop_active', 'workshop_id', 'is_active'),
        {"comment": "Привязка пользователей к цехам"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, comment='id пользователя')
    workshop_id = Column(UUID(as_uuid=True), ForeignKey('workshops.id', ondelete='CASCADE'), nullable=False, comment='id цеха')
    line_id = Column(UUID(as_uuid=True), ForeignKey('lines.id', ondelete='SET NULL'), nullable=True, comment='id линии')
    role_in_workshop = Column(String(50), default='master', nullable=False, comment='Роль в цеху')
    is_active = Column(Boolean, default=True, nullable=False, comment='Доступ к цеху')
    comment = Column(String(255), nullable=True, comment='Комментарий')
    created_at = Column(MoscowDateTime(), server_default=func.now())
    edited_at = Column(MoscowDateTime(), server_default=func.now(), onupdate=func.now())

    user = relationship('User', back_populates='workshop_users', lazy='selectin')
    workshop = relationship('Workshop', back_populates='workshop_users', lazy='selectin')
    line = relationship('Line', back_populates='workshop_users', lazy='selectin')

    def __repr__(self):
        return f'<WorkshopUser(id={self.id}, user={self.user_id}, workshop={self.workshop_id})>'


class PrintJob(Base):
    """Задания на печать этикеток."""
    __tablename__ = 'print_jobs'
    __table_args__ = (
        Index('ix_print_jobs_user_status', 'user_id', 'status'),
        Index('ix_print_jobs_created_at', 'created_at'),
        {'comment': 'Задания на печать этикеток'}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, comment='id пользователя')
    product_id = Column(UUID(as_uuid=True), ForeignKey('products.id', ondelete='CASCADE'), nullable=False, comment='id продукта')
    printer_id = Column(UUID(as_uuid=True), ForeignKey('printers.id', ondelete='CASCADE'), nullable=False, comment='id принтер')
    template_id = Column(UUID(as_uuid=True), ForeignKey('code_templates.id', ondelete='CASCADE'), nullable=False, comment='id шаблона')

    batch_number = Column(String(50), nullable=False, comment='Номер партии')
    marking_date = Column(Date, nullable=False, comment='Дата маркировки')
    expiration_date = Column(Date, nullable=False, comment='Дата окончания срока годности')
    first_box = Column(Integer, nullable=False, comment='Номер первой коробки')
    last_box = Column(Integer, nullable=False, comment='Номер последней коробки')
    boxes_count = Column(Integer, nullable=False, comment='Количество коробок')
    status = Column(String(20), nullable=False, default='pending', comment='Статус печати')
    error_message = Column(Text, nullable=True, comment='Сообщение об ошибке')
    printed_count = Column(Integer, default=0, comment='Количество напечатанных этикеток')
    created_at = Column(MoscowDateTime(), server_default=func.now())
    edited_at = Column(MoscowDateTime(), server_default=func.now(), onupdate=func.now())
    completed_at = Column(MoscowDateTime(), nullable=True, comment='Дата завершения')

    user = relationship('User', back_populates='print_jobs', lazy='selectin')
    product = relationship('Product', back_populates='print_jobs', lazy='selectin')
    printer = relationship('Printer', back_populates='print_jobs', lazy='selectin')
    template = relationship('CodeTemplate', back_populates='print_jobs', lazy='selectin')

    def __repr__(self):
        return f'<PrintJob(id={self.id}, user={self.user_id}, product={self.product_id}, status={self.status})>'
