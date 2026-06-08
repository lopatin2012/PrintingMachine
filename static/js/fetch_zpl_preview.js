// Глобальное хранение текущего угла поворота
let currentRotation = 0;

// Функция поворота
function rotatePreview90() {
    currentRotation = (currentRotation + 90) % 360;
    applyRotation();
    document.getElementById('rotationValue').textContent = `${currentRotation}°`;
}

// Применяет поворот к обёртке, если она существует
function applyRotation() {
    const wrapper = document.querySelector('.rotatable-wrapper');
    if (wrapper) {
        wrapper.style.transform = `rotate(${currentRotation}deg)`;
    }
}

// Обновлённая функция получения превью — сохраняет поворот!
async function fetchAndDisplayPreview() {
    const zplInput = document.getElementById('zplInput');
    const preview = document.getElementById('preview');
    const zpl = zplInput?.value.trim();

    if (!zpl) {
        alert("Пожалуйста, введите ZPL-код.");
        return;
    }

    // Гарантируем наличие обёртки
    let wrapper = document.querySelector('.rotatable-wrapper');
    let img;

    if (!wrapper) {
        wrapper = document.createElement('div');
        wrapper.className = 'rotatable-wrapper';
        img = document.createElement('img');
        img.style.maxWidth = '100%';
        img.style.height = 'auto';
        wrapper.appendChild(img);
        preview.innerHTML = '';
        preview.appendChild(wrapper);
        preview.classList.remove('hidden');
    } else {
        img = wrapper.querySelector('img');
    }

    // Показываем загрузку (опционально)
    img.src = ''; // очистить старое изображение
    img.alt = 'Загрузка...';

    try {
        const response = await fetch('/zpl_render_labelary', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ zpl })
        });

        if (!response.ok) {
            const errorText = await response.text();
            img.alt = `Ошибка: ${errorText}`;
            return;
        }

        const blob = await response.blob();
        const imgUrl = URL.createObjectURL(blob);
        img.src = imgUrl;

        // Применяем текущий поворот к новому изображению.
        applyRotation();

    } catch (e) {
        img.alt = `Ошибка загрузки: ${e.message}`;
    }
}