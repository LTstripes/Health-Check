// Synthetic DOM contract test of the production duration chart and event toggle.
// No browser, runtime database, provider or network. Input is a packet file or stdin.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const data = JSON.parse(fs.readFileSync(process.argv[2] || 0, 'utf8'));
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.attributes = {}; this.events = {};
    this.textContent = ''; this.clientWidth = 900; this.hidden = false;
    this.style = { setProperty() {} };
    this.classes = new Set();
    this.classList = { add: name => this.classes.add(name),
      toggle: (name, value) => value ? this.classes.add(name) : this.classes.delete(name) };
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
  set innerHTML(value) { this.html = value; this.children = []; }
  get innerHTML() { return this.html || ''; }
  addEventListener(name, fn) { (this.events[name] ||= []).push(fn); }
  fire(name, values = {}) { (this.events[name] || []).forEach(fn => fn({ target: this, ...values })); }
  focus() { document.activeElement = this; this.fire('focus'); }
  blur() { document.activeElement = null; }
  closest() { return null; }
  getScreenCTM() { return { inverse: () => ({}) }; }
  querySelectorAll(selector) {
    const match = node => selector.startsWith('[') ?
      node.getAttribute(selector.slice(1, -1)) !== null : node.tagName === selector;
    return this.children.flatMap(child => [...(match(child) ? [child] : []),
      ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
const host = new Element('div'), detail = new Element('div'), node = new Element('script');
node.textContent = JSON.stringify(data);
const toggles = data.display_series.map(series => {
  const toggle = new Element('input'); toggle.checked = true;
  toggle.setAttribute('data-sleep-series-toggle', series.series_id); return toggle;
});
const cells = data.display_series.map(series => {
  const cell = new Element('div'); cell.setAttribute('data-sleep-context-source', series.series_id);
  return cell;
});
const document = {
  activeElement: null,
  getElementById: id => ({ 'sleep-timeline-data': node, 'sleep-timeline-chart': host,
    'sleep-timeline-detail': detail })[id] || null,
  createElementNS: (_namespace, tag) => new Element(tag),
  querySelectorAll: selector => ({ '[data-sleep-series-toggle]': toggles,
    '[data-sleep-context-source]': cells })[selector] || [],
};
const context = vm.createContext({ window: {}, document, URLSearchParams,
  fetch: () => new Promise(() => {}),
  ResizeObserver: class { observe() {} disconnect() {} },
  DOMPoint: class { constructor(x, y) { this.x = x; this.y = y; } matrixTransform() { return this; } },
});
const root = path.join(__dirname, '..', 'src', 'healthcheck', 'web', 'static');
for (const name of ['owner_dates.js', 'owner_formatting.js', 'sleep_night_card.js', 'sleep_timeline.js', 'sleep_context.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), context, { filename: name });
}
const dots = host.querySelectorAll('[data-sleep-context-marker]');
const points = dots.map(dot => dot.parentElement);
if (points.length) points[0].focus();
const focusHtml = detail.innerHTML;
if (points.length > 1) {
  const hit = points[1].querySelector('circle');
  host.querySelector('svg').fire('pointermove', { clientX: Number(hit.getAttribute('cx')),
    clientY: Number(hit.getAttribute('cy')) });
}
const hoverHtml = detail.innerHTML;
if (toggles.length) { toggles[0].checked = false; toggles[0].fire('change'); }
process.stdout.write(JSON.stringify({ dots: dots.length,
  labels: points.map(point => point.getAttribute('aria-label')),
  focus_html: focusHtml, hover_html: hoverHtml, hidden_cells: cells.map(cell => cell.hidden) }));
