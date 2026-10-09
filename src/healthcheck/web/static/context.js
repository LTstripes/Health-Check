/* No autosave, local storage or provider requests. Explicit same-origin form submit. */
(() => {
  const form = document.getElementById('context-form');
  if (!form) return;
  const pending = document.getElementById('context-pending');
  let submitting = false;
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    submitting = true;
    pending.textContent = 'Сохраняется… Если связь прервалась, повтор использует тот же ключ операции.';
    form.querySelector('button[type="submit"]').disabled = true;
  });
  window.addEventListener('pageshow', () => {
    submitting = false;
    form.querySelector('button[type="submit"]').disabled = false;
    pending.textContent = '';
  });
  document.getElementById('context-now').addEventListener('click', () => {
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    form.elements.event_date.value = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    form.elements.event_time.value = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
    const minutes = -now.getTimezoneOffset();
    form.elements.offset.value = `${minutes >= 0 ? '+' : '-'}${pad(Math.floor(Math.abs(minutes) / 60))}:${pad(Math.abs(minutes) % 60)}`;
    form.elements.timezone_name.value = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    pending.textContent = 'Дата и время заполнены по часам браузера. Проверь перед сохранением.';
  });
})();
