// Обработка формы.
document.querySelectorAll('.toggle-form-btn').forEach(button => {
    button.addEventListener('click', () => {
        const templateId = button.dataset.templateId;
        const formRow = document.querySelector(`.print-form-row[data-template-id="${templateId}"]`);

        if (formRow.style.display === 'table-row') {
            formRow.style.display = 'none';
        } else {
            // Скрыть все остальные формы
            document.querySelectorAll('.print-form-row').forEach(row => {
                row.style.display = 'none';
            });
            formRow.style.display = 'table-row';
        }
    });
});

// Обработка отправки форм
document.querySelectorAll('.print-form').forEach(form => {
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const templateId = form.dataset.templateId;
        const messageEl = form.querySelector('.form-message');
        messageEl.textContent = '';
        messageEl.style.color = '';

        const formData = new FormData(form);
        const data = Object.fromEntries(formData.entries());

        // Преобразуем числа
        data.start_box_number = parseInt(data.start_box_number);
        data.quantity = parseInt(data.quantity);
        data.printer_port = parseInt(data.printer_port);

        try {
            const res = await fetch(`/api/print/${templateId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            const result = await res.json();

            if (res.ok) {
                messageEl.textContent = `✅ Напечатано ${result.printed} этикеток!`;
                messageEl.style.color = 'green';
//                // Автоматически закрыть форму через 2 секунды
//                setTimeout(() => {
//                    document.querySelector(`.print-form-row[data-template-id="${templateId}"]`).style.display = 'none';
//                }, 2000);
            } else {
                messageEl.textContent = `❌ Ошибка: ${result.detail || 'Неизвестная ошибка'}`;
                messageEl.style.color = 'red';
            }
        } catch (err) {
            messageEl.textContent = `❌ Ошибка сети: ${err.message}`;
            messageEl.style.color = 'red';
        }
    });
});
