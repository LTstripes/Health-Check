// Exercise production timeline initialization and DOM event handlers, without network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Node {
  constructor() { this.attrs = {}; this.children = []; this.events = {}; this.innerHTML = ''; this.style = {setProperty() {}}; this.classList = {add() {}, toggle() {}}; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key]; }
  removeAttribute(key) { delete this.attrs[key]; }
  appendChild(node) { this.children.push(node); }
  addEventListener(key, fn) { this.events[key] = fn; }
  querySelector(selector) { return this.children.find(item => selector === 'circle' && item.tag === 'circle') || null; }
  querySelectorAll() { return this.children; }
  focus() { this.events.focus?.(); }
  closest() { return this; }
}
const dates = ['2026-11-08', '2026-11-09', '2026-11-10'];
function series(provider, states) {
  return {provider, label: provider === 'garmin' ? 'Garmin' : 'Google', series_id: provider,
    source: {source_id: provider}, points: states.map((state, index) => ({
      state, wake_date: dates[index], value_seconds: state === 'value' ? 25200 : null,
      value_hours: state === 'value' ? 7 : null, record_id: provider + index, note: ''
    }))};
}
function setup(display_series) {
  const detail = new Node(), host = new Node(), table = new Node(); host.clientWidth = 1000;
  table.setAttribute('open', '');
  const packet = {dates, end_date: dates[2], display_series};
  const dataNode = {textContent: JSON.stringify(packet)};
  const toggles = display_series.map(item => {
    const node = new Node(); node.checked = true;
    node.setAttribute('data-sleep-series-toggle', item.series_id); return node;
  });
  const fetches = [];
  const document = {
    getElementById(id) { return {'sleep-timeline-data': dataNode, 'sleep-timeline-chart': host, 'sleep-timeline-detail': detail}[id]; },
    querySelector() { return table; }, querySelectorAll() { return toggles; },
    createElementNS(ns, tag) { const node = new Node(); node.tag = tag; return node; }
  };
  const context = vm.createContext({window: {}, document, URLSearchParams,
    fetch(url) { fetches.push(url); return new Promise(() => {}); },
    ResizeObserver: class { observe() {} disconnect() {} }});
  for (const file of ['owner_dates.js', 'owner_formatting.js', 'sleep_night_card.js', 'sleep_timeline.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/healthcheck/web/static', file), 'utf8'), context);
  }
  function click(key, value) { const node = new Node(); node.setAttribute(key, value); detail.events.click({target: node}); }
  function points() { return host.children.at(-1).children.flatMap(group => group.children).filter(node => node.getAttribute('data-wake-date')); }
  return {detail, host, table, toggles, fetches, click, points, packet, dataNode};
}
let ui = setup([series('garmin', ['value', 'ambiguous', 'no_records']), series('google', ['value', 'value', 'value'])]);
assert.match(ui.detail.innerHTML, /За ночь на 10 ноября у Garmin нет записи/);
assert.match(ui.detail.innerHTML, /Это не „0 часов“/);
assert.match(ui.detail.innerHTML, /Показать 8 ноября/);
assert.equal(ui.fetches.length, 0); // No neighboring night is selected or fetched.
assert.equal(ui.table.getAttribute('open'), undefined);
assert.equal(ui.points().filter(node => node.getAttribute('aria-pressed') === 'true').length, 0);
ui.click('data-night-latest', dates[0]);
assert.match(ui.detail.innerHTML, /Ночь на 8 ноября/);
assert.match(ui.detail.innerHTML, /aria-label="7 ч 00 мин"/);
assert.equal(ui.points().find(node => node.getAttribute('aria-pressed') === 'true').getAttribute('data-wake-date'), dates[0]);
ui.click('data-night-step', '1');
assert.match(ui.detail.innerHTML, /Несколько записей за дату; значение не выбрано/);
assert.doesNotMatch(ui.detail.innerHTML, /night-card-figure/);
assert.equal(ui.detail.innerHTML.split('<details').length - 1, 2);
ui.click('data-night-source', 'google');
assert.match(ui.detail.innerHTML, /Ночь на 9 ноября/);
assert.match(ui.detail.innerHTML, /data-night-source="google" aria-pressed="true"/);
const point = ui.points().find(node => node.getAttribute('data-sleep-series-id') === 'google' && node.getAttribute('data-wake-date') === dates[1]);
point.focus();
point.events.keydown({key: 'ArrowRight', preventDefault() {}});
assert.match(ui.detail.innerHTML, /Ночь на 10 ноября/);
ui.toggles[1].checked = false; ui.toggles[1].events.change();
assert.match(ui.detail.innerHTML, /За ночь на 10 ноября у Garmin нет записи/);
ui.toggles[0].checked = false; ui.toggles[0].events.change();
assert.match(ui.detail.textContent, /Выбери источник/);
ui.toggles[1].checked = true; ui.toggles[1].events.change();
assert.match(ui.detail.innerHTML, /Ночь на 10 ноября/);
ui = setup([series('google', ['value', 'value', 'value'])]);
assert.match(ui.detail.innerHTML, /Ночь на 10 ноября/);
assert.match(ui.fetches[0], /provider=google.*wake_date=2026-11-10/);
ui = setup([series('garmin', ['value', 'value', 'ambiguous'])]);
assert.match(ui.detail.innerHTML, /Несколько записей за дату/);
assert.equal(ui.fetches.length, 0);
ui = setup([series('garmin', ['no_records', 'no_records', 'no_records'])]);
assert.match(ui.detail.innerHTML, /За ночь на 10 ноября/);
assert.doesNotMatch(ui.detail.innerHTML, /data-night-latest/);
ui = setup([series('garmin', ['value', 'value', 'value'])]);
assert.match(ui.detail.innerHTML, /Ночь на 10 ноября/);
assert.match(ui.fetches[0], /provider=garmin.*wake_date=2026-11-10/);
assert.deepEqual(JSON.parse(ui.dataNode.textContent), ui.packet);
console.log('PASS: default/end-date, empty/latest, ambiguous, source, arrows, legend, packet unchanged');
