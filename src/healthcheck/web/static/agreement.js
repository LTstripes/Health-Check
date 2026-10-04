/* Presentation of frozen agreement differences only; no pooling or statistics. */
(function () {
  document.querySelectorAll('svg[data-group-index]').forEach(function (svg) {
    const points = JSON.parse(svg.dataset.groupIndex);
    const values = points.map(point => point.difference).filter(Number.isFinite);
    if (!values.length) {
      const empty = document.createElement('p');
      empty.className = 'unavailable';
      empty.textContent = 'Нет сопоставимых точек.';
      svg.replaceWith(empty);
      return;
    }
    const width = 900, height = 150, left = 40, right = 12, top = 12, bottom = 24;
    const min = Math.min(...values), max = Math.max(...values);
    const span = max === min ? 1 : max - min;
    let previous = null;
    const path = points.map(function (point, index) {
      const day = Date.parse(point.wake_date + 'T00:00:00Z');
      if (!Number.isFinite(point.difference) || !Number.isFinite(day)) {
        previous = null;
        return '';
      }
      const x = left + (index / Math.max(1, points.length - 1)) * (width - left - right);
      const y = top + (1 - (point.difference - min) / span) * (height - top - bottom);
      const move = previous === null || day - previous !== 86400000;
      previous = day;
      return (move ? 'M' : 'L') + x.toFixed(1) + ' ' + y.toFixed(1);
    }).join(' ');
    const ns = 'http://www.w3.org/2000/svg';
    const line = document.createElementNS(ns, 'path');
    line.setAttribute('d', path);
    line.setAttribute('fill', 'none');
    line.setAttribute('stroke', 'var(--series-4)');
    line.setAttribute('stroke-width', '2');
    svg.appendChild(line);
    points.forEach(function (point, index) {
      if (!Number.isFinite(point.difference)) return;
      const dot = document.createElementNS(ns, 'rect');
      dot.setAttribute('x', left + (index / Math.max(1, points.length - 1)) * (width - left - right) - 4);
      dot.setAttribute('y', top + (1 - (point.difference - min) / span) * (height - top - bottom) - 4);
      dot.setAttribute('width', '8');
      dot.setAttribute('height', '8');
      dot.setAttribute('fill', 'var(--series-4)');
      const title = document.createElementNS(ns, 'title');
      title.textContent = point.wake_date + ': ' + point.difference;
      dot.appendChild(title);
      svg.appendChild(dot);
    });
  });
})();
