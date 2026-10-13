/* Production JS over a synthetic DOM; no browser, runtime or provider calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const packet = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.events = {}; this.text = ''; }
  set textContent(text) { this.text = String(text); this.children = []; }
  get textContent() { return this.text + this.children.map(item => item.textContent).join(' '); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.text = ''; this.children = items; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(key, callback) { this.events[key] = callback; }
  focus() { this.focused = true; }
}
function tree(root) { return [root, ...root.children.flatMap(tree)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture(params, mode = 'saved') {
  const result = structuredClone(packet);
  result.evaluated_at_utc = params.get('evaluated_at_utc');
  result.evaluation_local_date = params.get('evaluation_local_date');
  result.collection_policy = {status: 'valid', disabled_streams: ['google:daily_resting_hr']};
  for (const [index, dto] of result.items.entries()) {
    const source = {source_id: 'source-' + index, provider_code: dto.query.provider_code,
      source_instance_id: 'synthetic-' + index, source_kind: 'synthetic', device_model: null, device_code: null, device_attributed: false};
    dto.query.evaluation_local_date = dto.query.requested_start_date = dto.query.requested_end_date = result.evaluation_local_date;
    dto.query.evaluated_at_utc = result.evaluated_at_utc;
    dto.query.source_id = params.get(index ? 'google_source_id' : 'garmin_source_id');
    dto.available_sources = [source];
    dto.source_identity = source;
    const age = index ? 3 : 0;
    const date = new Date(result.evaluation_local_date); date.setUTCDate(date.getUTCDate() - age);
    dto.state = age ? 'last_eligible' : 'exact'; dto.reason = null;
    dto.search.complete = true;
    dto.observation = {value: index ? 59 : 0, unit: 'bpm', source_local_date: date.toISOString().slice(0, 10),
      observation_age_days: age, record_status: 'partial', raw_payload_id: 'synthetic-raw', field_path: 'synthetic-field'};
    dto.refresh.terminal_status = 'reauth_required';
    dto.newer_exclusions = index ? [{source_local_date: result.evaluation_local_date, reason: 'ambiguous_same_date_records', record_ids: ['a', 'b'], candidate_count: 2}] : [];
    if (mode === 'ambiguous' && index && !dto.query.source_id) {
      dto.available_sources.push({...source, source_id: 'source-other', source_instance_id: 'other'});
      dto.state = 'ambiguous'; dto.reason = 'source_selection_required'; dto.observation = dto.source_identity = null;
    }
    if (mode === 'cap') { dto.state = 'search_incomplete'; dto.reason = dto.search.reason = 'candidate_group_cap'; dto.search.complete = false; dto.search.incomplete_group_date = result.evaluation_local_date; dto.observation = null; }
  }
  return result;
}
function setup(mode = 'saved') {
  const elements = Object.fromEntries(['saved-rhr-results', 'saved-rhr-feedback', 'saved-rhr-refresh', 'saved-rhr-clock'].map(id => [id, new Element('div')]));
  const requests = [];
  const doc = {activeElement: null, querySelectorAll: () => [], createElement: tag => new Element(tag),
    getElementById: id => elements[id] || tree(elements['saved-rhr-results']).find(item => item.id === id)};
  const context = {document: doc, window: {}, Date, Intl, URLSearchParams, AbortController, setTimeout, clearTimeout,
    fetch: (url, options) => new Promise(resolve => requests.push({url, options, resolve}))};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/healthcheck/web/static/data_status.js'), 'utf8'), context);
  async function finish(index, mutate, status = 200) {
    const request = requests[index], params = new URL(request.url, 'http://localhost').searchParams;
    const body = fixture(params, mode); if (mutate) mutate(body);
    request.resolve({ok: status === 200, status, json: async () => body}); await tick();
  }
  return {elements, requests, doc, finish, refresh: () => elements['saved-rhr-refresh'].events.click()};
}
(async () => {
  const current = setup(); await current.finish(0);
  const text = current.elements['saved-rhr-results'].textContent;
  assert.match(text, /0 bpm/); assert.match(text, /59 bpm/); assert.match(text, /Возраст: 3 дн/);
  assert.match(text, /Нужен повторный вход/); assert.match(text, /Сбор отключён/);
  assert.match(text, /ambiguous_same_date_records/); assert.match(text, /synthetic-raw/);
  assert.match(text, /Запись частичная/); assert.match(text, /правило возраста: не настроено/i);
  assert.equal(current.requests[0].options.cache, 'no-store');
  assert.match(current.requests[0].url, /^\/api\/imports\/saved-rhr\?/);
  assert.ok(tree(current.elements['saved-rhr-results']).filter(item => item.tag === 'details').every(item => !item.attrs.open));
  current.refresh(); current.refresh();
  assert.equal(current.requests[1].options.signal.aborted, true);
  await current.finish(2, body => { body.items[0].observation.value = 72; });
  await current.finish(1, body => { body.items[0].observation.value = 99; });
  assert.match(current.elements['saved-rhr-results'].textContent, /72 bpm/);
  assert.doesNotMatch(current.elements['saved-rhr-results'].textContent, /99 bpm/);
  assert.equal(current.elements['saved-rhr-results'].attrs['aria-busy'], 'false');
  const choices = setup('ambiguous'); await choices.finish(0);
  assert.match(choices.elements['saved-rhr-results'].textContent, /Выберите источник явно/);
  const select = choices.doc.getElementById('saved-source-google_health');
  select.value = 'source-other'; choices.doc.activeElement = select; select.events.change();
  assert.match(choices.requests[1].url, /google_source_id=source-other/);
  await choices.finish(1, body => {
    const dto = body.items[1]; dto.source_identity = {...dto.source_identity, source_id: 'source-other'};
    dto.available_sources = [dto.source_identity];
  });
  assert.equal(choices.doc.getElementById('saved-source-google_health').focused, true);
  for (const mutate of [body => body.items.pop(), body => body.items[0].query.metric_code = 'sleep',
    body => body.items[0].observation.observation_age_days = 5, body => body.items[0].source_identity.provider_code = 'google_health']) {
    const invalid = setup(); await invalid.finish(0, mutate);
    assert.equal(invalid.elements['saved-rhr-feedback'].dataset.failureCode, 'invalid_response');
    assert.equal(invalid.elements['saved-rhr-results'].children.length, 0);
  }
  const cap = setup('cap'); await cap.finish(0);
  assert.match(cap.elements['saved-rhr-results'].textContent, /candidate_group_cap/);
  assert.doesNotMatch(cap.elements['saved-rhr-results'].textContent, /59 bpm/);
  const failed = setup(); await failed.finish(0, body => {body.secret = 'synthetic-secret';}, 503);
  assert.equal(failed.elements['saved-rhr-feedback'].dataset.failureCode, 'database_unavailable');
  assert.doesNotMatch(failed.elements['saved-rhr-feedback'].textContent, /synthetic-secret/);
  console.log('PASS: saved values, age, refresh separation, overrides, caps, validation, repeated and late requests');
})().catch(error => {console.error(error); process.exitCode = 1;});
