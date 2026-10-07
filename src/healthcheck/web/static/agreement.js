/* Two source series from frozen compatible pairs. No pairing, pooling or statistics. */
(function () {
  const ns = 'http://www.w3.org/2000/svg';
  const add = (svg, tag, attributes, text) => {
    const node = document.createElementNS(ns, tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
    if (text !== undefined) node.textContent = text;
    svg.appendChild(node);
    return node;
  };
  document.querySelectorAll('svg[data-sleep-comparison]').forEach(svg => {
    const chart = JSON.parse(svg.dataset.sleepComparison), points = chart.points;
    const days = points.map(p => Date.parse(p.wake_date + 'T00:00:00Z'));
    const values = points.flatMap(p => [p.garmin, p.google]);
    if (!values.length || values.some(v => !Number.isFinite(v)) || days.some(d => !Number.isFinite(d))) return;
    let min = Math.min(...values), max = Math.max(...values);
    if (min === max) { min -= 1; max += 1; }
    const span = max - min;
    const start = days[0], end = days[days.length - 1], dateSpan = end - start || 86400000;
    const x = i => 110 + (days[i] - start) / dateSpan * 765;
    const y = v => 20 + (1 - (v - min) / span) * 170;
    const tick = v => chart.unit === 'UTC instant' ?
      new Date(v * 1000).toLocaleString('ru-RU', { timeZone: 'UTC', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) :
      (chart.unit === 'seconds' ? v / 3600 : v).toFixed(1);
    [min, max].forEach(v => {
      add(svg, 'line', { x1: 110, x2: 875, y1: y(v), y2: y(v), stroke: 'var(--line)' });
      add(svg, 'text', { x: 100, y: y(v) + 4, 'text-anchor': 'end', class: 'sleep-chart-axis' }, tick(v));
    });
    [0, points.length - 1].filter((i, pos, all) => all.indexOf(i) === pos).forEach(i => {
      add(svg, 'text', { x: x(i), y: 224, 'text-anchor': i ? 'end' : 'start', class: 'sleep-chart-axis' },
        new Date(days[i]).toLocaleDateString('ru-RU', {timeZone: 'UTC'}));
    });
    ['garmin', 'google'].forEach((provider, series) => {
      const color = `var(--series-${series + 1})`;
      const d = points.map((p, i) =>
        (i === 0 || days[i] - days[i - 1] !== 86400000 ? 'M' : 'L') + x(i).toFixed(1) + ' ' + y(p[provider]).toFixed(1)).join(' ');
      add(svg, 'path', { d, fill: 'none', stroke: color, 'stroke-width': 2,
        'stroke-dasharray': series ? '6 4' : 'none', 'data-source-series': provider });
      points.forEach((p, i) => {
        const dot = add(svg, series ? 'rect' : 'circle', series ?
          { x: x(i) - 4, y: y(p[provider]) - 4, width: 8, height: 8, fill: color } :
          { cx: x(i), cy: y(p[provider]), r: 4, fill: color });
        add(dot, 'title', {}, `${p.wake_date} · ${series ? 'Google' : 'Garmin'}: ${p[provider + '_text']}`);
      });
    });
  });
})();
