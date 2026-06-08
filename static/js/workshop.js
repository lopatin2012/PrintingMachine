// Открыть форму добавления
function openAddForm() {
    document.getElementById('formTitle').textContent = '➕ Добавить цех';
    document.getElementById('formSubmitText').textContent = 'Добавить цех';
    document.getElementById('workshopForm').action = '/workshops';
    document.getElementById('workshopId').value = '';
    document.getElementById('workshopName').value = '';
    document.getElementById('workshopFormModal').classList.remove('hidden');
}

// Открыть форму редактирования
function editWorkshop(id, name) {
    // Убедимся, что имя — строка (защита от undefined)
    name = String(name || '').trim();

    document.getElementById('formTitle').textContent = '✏️ Редактировать цех';
    document.getElementById('formSubmitText').textContent = 'Сохранить изменения';
    document.getElementById('workshopForm').action = `/workshops/${id}`;
    document.getElementById('workshopId').value = id;
    document.getElementById('workshopName').value = name;
    document.getElementById('workshopFormModal').classList.remove('hidden');

    // Фокус на поле ввода
    document.getElementById('workshopName').focus();
}

// Закрыть форму
function closeForm() {
    document.getElementById('workshopFormModal').classList.add('hidden');
    // Сброс состояния кнопки
    const submitBtn = document.getElementById('formSubmitBtn');
    submitBtn.disabled = false;
    submitBtn.innerHTML = '<span class="btn-text" id="formSubmitText">Добавить цех</span>';
}

// Удалить цех
function deleteWorkshop(id, name) {
    // Убедимся, что имя — строка
    name = String(name || 'без названия');

    if (confirm(`Вы уверены, что хотите удалить цех "${name}"?\n\n⚠️ Внимание: Все связанные линии и принтеры также будут удалены!`)) {
        // Создаём форму для отправки DELETE запроса
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/workshops/${id}/delete`;

        // Добавляем токен CSRF, если используется
        const csrfToken = document.querySelector('meta[name="csrf-token"]');
        if (csrfToken) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'csrf_token';
            input.value = csrfToken.content;
            form.appendChild(input);
        }

        document.body.appendChild(form);
        form.submit();
    }
}

// Инициализация после загрузки DOM
document.addEventListener('DOMContentLoaded', function() {
    // Кнопка "Добавить цех"
    const addBtn = document.getElementById('addWorkshopBtn');
    if (addBtn) {
        addBtn.addEventListener('click', openAddForm);
    }

    // Закрытие модального окна при клике вне его
    const modal = document.getElementById('workshopFormModal');
    if (modal) {
        modal.addEventListener('click', function(event) {
            if (event.target === modal) {
                closeForm();
            }
        });
    }

    // Валидация формы
    const form = document.getElementById('workshopForm');
    if (form) {
        form.addEventListener('submit', function(e) {
            const nameInput = document.getElementById('workshopName');
            const name = nameInput.value.trim();

            if (name.length < 2) {
                e.preventDefault();
                alert('Название цеха должно содержать минимум 2 символа');
                nameInput.focus();
                return false;
            }

            if (name.length > 50) {
                e.preventDefault();
                alert('Название цеха не должно превышать 50 символов');
                nameInput.focus();
                return false;
            }

            // Показать состояние загрузки
            const submitBtn = document.getElementById('formSubmitBtn');
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="btn-text">Сохранение...</span><span class="btn-spinner"></span>';
        });
    }

    // Обработка нажатия клавиши Escape для закрытия модалки
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeForm();
        }
    });
});
