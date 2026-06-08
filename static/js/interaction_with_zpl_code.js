document.getElementById('addZplForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const messageEl = document.getElementById('formMessage');
    messageEl.textContent = '';
    messageEl.className = '';

    const formData = new FormData(form);
    const data = Object.fromEntries(formData);

    try {
        const res = await fetch('/api/add-zpl-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        const result = await res.json();

        if (res.ok) {
            messageEl.textContent = '✅ ZPL-код успешно добавлен!';
            messageEl.style.color = 'green';
            form.reset(); // очистить форму
        } else {
            messageEl.textContent = `❌ Ошибка: ${result.detail || 'Неизвестная ошибка'}`;
            messageEl.style.color = 'red';
        }
    } catch (err) {
        messageEl.textContent = `❌ Ошибка сети: ${err.message}`;
        messageEl.style.color = 'red';
    }
});