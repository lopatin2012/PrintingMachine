// Отображение и сокрытие пароля.
function togglePassword(inputId) {
    const input = document.getElementById(inputId);
    const button = event.currentTarget;

    if (input.type == 'password') {
        input.type = 'text';
        button.innerHTML = '🙈';
    } else {
        input.type = 'password';
        button.innerHTML = '👁️';
    }
}