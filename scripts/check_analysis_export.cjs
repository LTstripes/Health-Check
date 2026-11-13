/* Production export selector over synthetic inventories; no provider or browser. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(text = '', value = '') { this.textContent = text; this.value = value; this.children = []; this.listeners = {}; }
  replaceChildren(...children) { this.children = children; this.value = ''; }
  add(child) { this.children.push(child); }
  addEventListener(event, fn) { this.listeners[event] = fn; }
  removeAttribute() {}
  setCustomValidity(value) { this.validityText = value; }
}
async function run(garminCount, googleCount) {
  const ids = ['analysis-export-form', 'analysis-export-status', 'analysis-export-result', 'analysis-export-reload',
    'analysis-export-options', 'analysis-export-preview', 'analysis-export-text', 'analysis-export-json',
    'analysis-export-disclosures', 'analysis-export-summary'];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const form = elements['analysis-export-form'];
  form.elements = {days: new Element('', '7'), end_date: new Element('', '2026-11-10'),
    garmin_source_id: new Element(), google_hrv_source_id: new Element()};
  const controls = Object.fromEntries(['[type="submit"]', '[data-export-garmin-choice]', '[data-export-google-choice]']
    .map(selector => [selector, new Element()]));
  form.querySelector = selector => controls[selector];
  const rows = (count, provider) => Array.from({length: count}, (_, index) => ({
    id: `${provider === 'garmin_connect' ? 'abcd1234' : 'fedc9876'}-${index}`,
    provider, label: `${provider === 'garmin_connect' ? 'Garmin Connect' : 'Google'} · источник · ${provider === 'garmin_connect' ? 'abcd1234' : 'fedc9876'}`,
  }));
  const sources = [...rows(garminCount, 'garmin_connect'), ...rows(googleCount, 'google_health')];
  const calls = [];
  const context = {document: {getElementById: id => elements[id]},
    window: {healthcheckOwnerDate: value => value, addEventListener() {}},
    Option: Element, Date, URL, AbortController,
    fetch: async (url, options) => {calls.push({url, options}); return {ok: true, json: async () => ({sources})};}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/healthcheck/web/static/analysis_export.js'), 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/analysis-export/sources');
  assert.equal(calls[0].options.cache, 'no-store');
  const garmin = form.elements.garmin_source_id, google = form.elements.google_hrv_source_id;
  assert.equal(garmin.value, garminCount === 1 ? sources[0].id : '');
  assert.equal(google.value, googleCount === 1 ? sources.at(-1).id : '');
  const options = elements['analysis-export-options'];
  assert.equal(options.open, garminCount > 1);
  assert.equal(options.hidden, garminCount <= 1 && googleCount <= 1);
  assert.equal(controls['[type="submit"]'].disabled, garminCount !== 1);
  for (const select of [garmin, google]) {
    const labels = select.children.slice(1).map(option => option.textContent);
    assert.equal(new Set(labels).size, labels.length);
    for (const option of select.children.slice(1)) {
      assert.equal(option.title, option.value.slice(0, 8));
      assert.doesNotMatch(option.textContent, /abcd1234|fedc9876|Garmin Connect/);
    }
  }
  if (garminCount === 1 && googleCount > 1) {
    assert.match(elements['analysis-export-status'].textContent, /Google HRV не включён/);
    google.value = google.children[1].value;
    form.listeners.input();
    assert.equal(google.value, google.children[1].value);
    assert.equal(elements['analysis-export-result'].hidden, true);
  }
}
(async () => {
  for (const [garmin, google] of [[1, 1], [1, 3], [2, 3], [0, 2], [1, 0]]) await run(garmin, google);
  console.log('PASS: optional/required disclosures, unique labels, tooltip IDs, unchanged defaults and exact selections');
})().catch(error => {console.error(error); process.exitCode = 1;});
