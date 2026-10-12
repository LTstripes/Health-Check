/* No autosave, local storage or provider requests. Explicit same-origin form submit. */
(() => {
  const form = document.getElementById('context-form');
  if (!form) return;
  const pending = document.getElementById('context-pending');
  const zone = form.elements.timezone_name;
  const syncZone = () => {
    const timed = Boolean(form.elements.event_time.value);
    document.getElementById('context-zone').hidden = !timed;
    zone.disabled = !timed;
    form.querySelectorAll('[data-fold]').forEach(label => {
      label.hidden = !timed;
      label.querySelector('select').disabled = !timed;
    });
  };
  const clearFold = field => {
    const label = form.querySelector(`[data-fold="${field}"]`);
    if (label) label.remove();
  };
  ['event_date', 'event_time', 'end_date', 'end_time', 'timezone_name'].forEach(name => {
    form.elements[name].addEventListener('input', () => {
      syncZone();
      if (!name.startsWith('end_')) clearFold('occurrence');
      if (name.startsWith('end_') || name === 'timezone_name') clearFold('end_occurrence');
    });
  });
  syncZone();
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
    zone.value = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    syncZone();
    clearFold('occurrence');
    clearFold('end_occurrence');
    pending.textContent = 'Дата и время заполнены по часам браузера. Проверь перед сохранением.';
  });
})();
