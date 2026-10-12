/* Focused synthetic DOM checks of the production Data script. No browser/provider. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const packet = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.text = ''; }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(' '); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.text = ''; this.children = children; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener() {}
}
function find(element, predicate) {
  return [element, ...element.children.flatMap(child => find(child, predicate))].filter(predicate);
}
async function run(value, status = 200) {
  const elements = Object.fromEntries(['data-results', 'data-refresh', 'data-feedback', 'data-clock']
    .map(id => [id, new Element('div')]));
  const calls = [];
  const context = { document: { querySelectorAll: () => [], getElementById: id => elements[id],
    createElement: tag => new Element(tag) }, window: {}, Date, Intl, URLSearchParams, AbortController,
    setTimeout, clearTimeout, fetch: async (url, options) => {
      calls.push({url, options}); return {ok: status === 200, status, json: async () => value};
    } };
  vm.createContext(context);
  for (const file of ['owner_dates.js', 'data_status.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/healthcheck/web/static', file), 'utf8'), context);
  }
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /^\/api\/source-freshness\?/);
  assert.equal(calls[0].options.cache, 'no-store');
  assert.equal(elements['data-results'].attributes['aria-busy'], 'false');
  assert.equal(elements['data-refresh'].disabled, false);
  return elements;
}
(async () => {
  const partial = structuredClone(packet);
  partial.components.forEach(item => {
    item.state = 'unknown'; item.reason_code = 'never_observed'; item.actionable = item.role === 'required';
    item.facts = {};
  });
  const garmin = partial.components.filter(item => item.provider === 'garmin');
  for (const item of garmin.filter(item => item.role === 'required')) {
    Object.assign(item, {state: 'unavailable', reason_code: 'reauth_required'});
    item.facts = {latest_evidence_local_date: '2026-10-04', last_relevant_attempt_utc: '2026-10-11T09:00:00Z'};
  }
  const optional = garmin.find(item => item.role === 'optional');
  Object.assign(optional, {state: 'not_requested', reason_code: 'disabled'});
  const google = partial.components.filter(item => item.provider === 'google' && item.role === 'required');
  Object.assign(google[0], {state: 'fresh', reason_code: 'evidence_current', actionable: false});
  google[0].facts = {latest_evidence_local_date: '2026-10-08'};
  Object.assign(google[1], {state: 'unavailable', reason_code: 'refresh_failed'});
  google[1].facts = {latest_evidence_local_date: '2026-10-03', last_relevant_attempt_utc: '2026-10-11T10:00:00Z'};
  partial.providers.garmin.state = 'unavailable'; partial.providers.google.state = 'unavailable';
  const rendered = await run(partial);
  const host = rendered['data-results'];
  const cards = find(host, el => ['garmin', 'google'].includes(el.dataset.provider));
  assert.equal(cards.length, 2);
  for (const card of cards) {
    assert.equal(find(card, el => el.className === 'data-actions uncertainty-note').length, 1);
    const disclosure = find(card, el => el.tag === 'details');
    assert.equal(disclosure.length, 1);
    assert.equal(disclosure[0].attributes.open, undefined);
    assert.ok(find(disclosure[0], el => el.dataset.scope).length >= 10);
  }
  assert.equal((cards[0].textContent.match(/Повтори вход/g) || []).length, 1);
  assert.match(cards[0].textContent, /4 октября 2026/);
  assert.match(cards[0].textContent, /11 октября 2026, 09:00:00 UTC/);
  assert.match(cards[0].textContent, /Сбор отключён/);
  assert.match(cards[1].textContent, /3 октября 2026 — 8 октября 2026/);
  assert.match(cards[1].textContent, /Последняя попытка обновления/);
  assert.match(cards[1].textContent, /завершилась неудачно/);
  assert.equal(find(cards[1], el => el.dataset.ownerState === 'present').length, 1);
  const success = structuredClone(partial);
  success.components.forEach(item => { item.state = 'fresh'; item.reason_code = 'evidence_current'; item.actionable = false; });
  success.providers.garmin.state = success.providers.google.state = success.owner.state = 'fresh';
  assert.equal(find((await run(success))['data-results'], el => el.className === 'data-actions uncertainty-note').length, 0);
  const missing = await run(packet);
  assert.match(missing['data-results'].textContent, /Неизвестн/);
  assert.doesNotMatch(missing['data-results'].textContent, /Повтори вход/);
  const invalid = structuredClone(packet); invalid.components.pop();
  assert.equal((await run(invalid))['data-feedback'].dataset.failureCode, 'invalid_response');
  const failed = await run({message: 'synthetic-secret'}, 500);
  assert.equal(failed['data-feedback'].dataset.failureCode, 'endpoint_error');
  assert.doesNotMatch(failed['data-feedback'].textContent, /synthetic-secret/);
  assert.equal(find(failed['data-results'], el => el.dataset.provider).length, 0);
  console.log('PASS: success, partial, repeated errors, disabled, missing, invalid, safe HTTP error; read-only request');
})().catch(error => { console.error(error); process.exitCode = 1; });
