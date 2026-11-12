(() => {
  for (const frame of document.querySelectorAll('.owner-chart-frame')) {
    const points = Array.from(frame.querySelectorAll('.overview-observed'));
    const output = frame.parentElement.querySelector('.owner-chart-selection');
    const show = point => { const title = point.querySelector('title'); if (title && output) output.textContent = title.textContent; };
    points.forEach((point, index) => {
      point.addEventListener('pointerenter', () => show(point));
      point.addEventListener('click', () => show(point));
      point.addEventListener('focus', () => show(point));
      point.addEventListener('keydown', event => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        points[(index + (event.key === 'ArrowRight' ? 1 : -1) + points.length) % points.length].focus();
      });
    });
  }
})();
