// Валидация данных.
document.getElementById('registerForm').addEventListener('submit', function() {
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirm_password').value;
    const submitBtn = document.getElementById('submitBtn');

    // Проверка совпадения паролей.
    if (password != confirmPassword) {
        e.preventDefault();
        alert('Пароли не совпадают!');
        return false;
    }

    // Проверка длины пароля.
    if (password.length < 8) {
        e.preventDefault();
        alert('Пароль должен содержать минимум 8 символов!');
        return false
    }

    // Показываем загрузку.
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="btn-text">Регистрация...</span><span class="btn-spinner"></span>';
});

// Показываем и скрываем пароль при наведении курсора.
const passwordInputs = document.querySelectorAll('input[type="password"]');
passwordInputs.forEach(input => {
    input.addEventListener('focus', function() {
        this.parentElement.classList.add('focused')
    });

    input.addEventListener('blur', function() {
        this.parentElement.classList.remove('focused');
    });
});
