// js/line.js

// Открыть форму добавления
function openAddLineForm() {
    document.getElementById('formTitle').textContent = '➕ Добавить линию';
    document.getElementById('formSubmitText').textContent = 'Добавить линию';
    document.getElementById('lineForm').action = '/lines';
    document.getElementById('lineId').value = '';
    document.getElementById('lineName').value = '';
    document.getElementById('workshopId').value = '';
    document.getElementById('lineFormModal').classList.remove('hidden');
}

// Открыть форму редактирования
function editLine(id, name, workshopId) {
    document.getElementById('formTitle').textContent = '✏️ Редактировать линию';
    document.getElementById('formSubmitText').textContent = 'Сохранить изменения';
    document.getElementById('lineForm').action = `/lines/${id}`;
    document.getElementById('lineId').value = id;
    document.getElementById('lineName').value = name.trim();
    document.getElementById('workshopId').value = workshopId;
    document.getElementById('lineFormModal').classList.remove('hidden');
    document.getElementById('lineName').focus();
}

// Закрыть форму
function closeLineForm() {
    document.getElementById('lineFormModal').classList.add('hidden');
    const submitBtn = document.getElementById('formSubmitBtn');
    submitBtn.disabled = false;
    submitBtn.innerHTML = '<span class="btn-text" id="formSubmitText">Добавить линию</span>';
}

// Удалить линию
function deleteLine(id, name) {
    name = String(name || 'без названия');

    if (confirm(`Вы уверены, что хотите удалить линию "${name}"?\n\n⚠️ Внимание: Все связанные принтеры также будут удалены!`)) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/lines/${id}/delete`;
        document.body.appendChild(form);
        form.submit();
    }
}

// Фильтрация по цеху
function filterLines() {
    const workshopId = document.getElementById('workshopFilter').value;
    const rows = document.querySelectorAll('#linesTableBody tr');

    rows.forEach(row => {
        if (!workshopId || row.dataset.workshopId === workshopId) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

// Инициализация после загрузки DOM
document.addEventListener('DOMContentLoaded', function() {
    // Кнопка "Добавить линию"
    const addBtn = document.getElementById('addLineBtn');
    if (addBtn) {
        addBtn.addEventListener('click', openAddLineForm);
    }

    // Фильтр по цеху
    const filterSelect = document.getElementById('workshopFilter');
    if (filterSelect) {
        filterSelect.addEventListener('change', filterLines);
    }

    // Закрытие модального окна при клике вне его
    const modal = document.getElementById('lineFormModal');
    if (modal) {
        modal.addEventListener('click', function(event) {
            if (event.target === modal) {
                closeLineForm();
            }
        });
    }

    // Валидация формы
    const form = document.getElementById('lineForm');
    if (form) {
        form.addEventListener('submit', function(e) {
            const nameInput = document.getElementById('lineName');
            const workshopSelect = document.getElementById('workshopId');
            const name = nameInput.value.trim();

            if (name.length < 2) {
                e.preventDefault();
                alert('Название линии должно содержать минимум 2 символа');
                nameInput.focus();
                return false;
            }

            if (name.length > 50) {
                e.preventDefault();
                alert('Название линии не должно превышать 50 символов');
                nameInput.focus();
                return false;
            }

            if (!workshopSelect.value) {
                e.preventDefault();
                alert('Пожалуйста, выберите цех для линии');
                workshopSelect.focus();
                return false;
            }

            // Показать состояние загрузки
            const submitBtn = document.getElementById('formSubmitBtn');
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="btn-text">Сохранение...</span><span class="btn-spinner"></span>';
        });
    }

    // Обработка нажатия клавиши Escape
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeLineForm();
        }
    });
});