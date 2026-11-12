(() => {
  // Dynamic SVG renderers retain their geometry while labels live in HTML.
  window.healthcheckChartLabels = function (host, svg) {
    let layer = host.querySelector(':scope > .owner-chart-overlay');
    if (!layer) {
      layer = document.createElement('div');
      layer.className = 'owner-chart-overlay';
      layer.setAttribute('aria-hidden', 'true');
      host.appendChild(layer);
    }
    layer.replaceChildren();
    const box = svg.viewBox.baseVal;
    svg.querySelectorAll('text[data-axis]').forEach(node => {
      const label = document.createElement('span');
      label.className = 'owner-chart-overlay-label';
      label.textContent = node.textContent;
      label.style.left = ((Number(node.getAttribute('x')) - box.x) / box.width * 100) + '%';
      label.style.top = ((Number(node.getAttribute('y')) - box.y) / box.height * 100) + '%';
      const anchor = node.getAttribute('text-anchor');
      label.style.transform = anchor === 'end' ? 'translate(-100%, -100%)' :
        anchor === 'middle' ? 'translate(-50%, -100%)' : 'translate(0, -100%)';
      layer.appendChild(label);
      node.style.visibility = 'hidden';
    });
  };
  for (const axis of document.querySelectorAll('.owner-chart-x[data-chart-start]')) {
    const draw = () => {
      const start = Date.parse(axis.dataset.chartStart + 'T00:00:00Z');
      const end = Date.parse(axis.dataset.chartEnd + 'T00:00:00Z');
      const days = Math.round((end - start) / 86400000);
      const count = Math.min(5, days + 1, Math.max(2, Math.floor(axis.clientWidth / 85) + 1));
      if (!Number.isFinite(days) || days < 0) return;
      axis.replaceChildren();
      for (let i = 0; i < count; i++) {
        const date = new Date(start + Math.round(i * days / Math.max(1, count - 1)) * 86400000);
        const label = document.createElement('span');
        label.textContent = window.healthcheckOwnerShortDate(date.toISOString().slice(0, 10));
        axis.appendChild(label);
      }
    };
    draw();
    if (window.ResizeObserver) new ResizeObserver(draw).observe(axis);
  }
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
