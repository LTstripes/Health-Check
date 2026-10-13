/* Offline desktop acceptance on production HTML and captured synthetic DTOs.
 * Requires imports.html, saved-rhr.json and freshness.json in the fixture dir.
 * No app startup or upstream request. PNG receipts bind actual image SHA256.
 */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const fixtures = process.env.HEALTHCHECK_DATA_FIXTURES_DIR;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.ok(fixtures && evidence);
const saved = JSON.parse(fs.readFileSync(path.join(fixtures, 'saved-rhr.json'), 'utf8'));
const freshness = JSON.parse(fs.readFileSync(path.join(fixtures, 'freshness.json'), 'utf8'));
const base = 'http://127.0.0.1:8120';
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE});
  const receipts = [], external = [], errors = [], calls = [];
  try {
    const context = await browser.newContext({timezoneId: 'UTC', viewport: {width: 1440, height: 1000}});
    await context.addInitScript(timestamp => {
      const NativeDate = Date;
      window.Date = class extends NativeDate {
        constructor(...args) { super(...(args.length ? args : [timestamp])); }
        static now() { return new NativeDate(timestamp).getTime(); }
      };
    }, saved.evaluated_at_utc);
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    let mode = 'saved', held;
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) { external.push(url.href); return route.abort(); }
      if (url.pathname === '/imports') return route.fulfill({body: fs.readFileSync(path.join(fixtures, 'imports.html')), contentType: 'text/html'});
      if (url.pathname === '/api/source-freshness') return route.fulfill({json: freshness});
      if (url.pathname === '/api/imports/saved-rhr') {
        calls.push({method: route.request().method(), url: url.href, mode});
        if (mode === 'held') { held = route; return; }
        if (mode === 'error') return route.fulfill({status: 503, json: {code: 'database_unavailable', ignored: 'synthetic-secret'}});
        const body = structuredClone(saved);
        for (const dto of body.items) {
          const p = dto.query.provider_code, override = url.searchParams.get(p === 'garmin_connect' ? 'garmin_source_id' : 'google_source_id');
          dto.query.source_id = override;
          if (mode === 'ambiguous' && p === 'google_health' && !override) {
            dto.available_sources.push({...dto.source_identity, source_id: 'synthetic-other', source_instance_id: 'second synthetic identity'});
            dto.source_identity = dto.observation = null; dto.state = 'ambiguous'; dto.reason = 'source_selection_required';
          }
          if (mode === 'cap') { dto.state = 'search_incomplete'; dto.reason = dto.search.reason = 'candidate_group_cap'; dto.observation = null; dto.search.complete = false; dto.search.incomplete_group_date = saved.evaluation_local_date; }
        }
        return route.fulfill({json: body});
      }
      if (url.pathname.startsWith('/static/')) {
        const file = path.join(root, 'src/healthcheck/web', url.pathname);
        return route.fulfill({body: fs.readFileSync(file), contentType: file.endsWith('.css') ? 'text/css' : 'application/javascript'});
      }
      return route.fulfill({status: 404, body: ''});
    });
    fs.mkdirSync(evidence, {recursive: true});
    for (const width of [1024, 1440]) {
      await page.setViewportSize({width, height: 1000});
      for (const scenario of ['saved', 'ambiguous', 'cap', 'error']) {
        mode = scenario; await page.goto(base + '/imports');
        await page.waitForFunction(() => document.querySelector('#saved-rhr-results').getAttribute('aria-busy') === 'false');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        assert.equal(await page.locator('#import-queue').count(), 1);
        assert.equal(await page.locator('#data-refresh').isVisible(), true);
        if (scenario === 'error') {
          assert.equal(await page.locator('#saved-rhr-feedback').getAttribute('data-failure-code'), 'database_unavailable');
          assert.doesNotMatch(await page.locator('#saved-rhr-feedback').textContent(), /synthetic-secret/);
        } else {
          assert.equal(await page.locator('[data-saved-provider]').count(), 2);
          assert.match(await page.locator('#saved-rhr-clock').textContent(), /default_latest/);
          if (scenario === 'saved') {
            for (const dto of saved.items) {
              const card = page.locator(`[data-saved-provider="${dto.query.provider_code}"]`);
              assert.match(await card.textContent(), new RegExp(dto.observation.value + ' bpm'));
              assert.ok((await card.textContent()).includes(dto.observation.source_local_date));
              assert.ok((await card.textContent()).includes('Возраст: ' + dto.observation.observation_age_days + ' дн.'));
              const details = card.locator('details').filter({hasText: 'Точные значения и provenance'});
              assert.equal(await details.getAttribute('open'), null);
              await details.locator('summary').focus(); await page.keyboard.press('Enter');
              assert.equal(await details.locator('pre').isVisible(), true);
              assert.ok((await details.textContent()).includes(dto.observation.raw_payload_id));
              await details.locator('summary').focus(); await page.keyboard.press('Enter');
            }
          }
          if (scenario === 'ambiguous') {
            const select = page.locator('#saved-source-google_health');
            await select.focus(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
            await page.waitForFunction(() => document.querySelector('#saved-rhr-results').getAttribute('aria-busy') === 'false');
            assert.ok(calls.some(item => item.url.includes('google_source_id=')));
            assert.equal(await select.evaluate(item => document.activeElement === item), true);
          }
          if (scenario === 'cap') assert.match(await page.locator('#saved-rhr-results').textContent(), /candidate_group_cap/);
        }
        const file = path.join(evidence, `data-saved-rhr-${scenario}-${width}.png`);
        await page.screenshot({path: file, fullPage: true});
        receipts.push({file, width, scenario, sha256: crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')});
      }
    }
    mode = 'held'; await page.locator('#saved-rhr-refresh').click();
    await page.waitForFunction(() => document.querySelector('#saved-rhr-results').getAttribute('aria-busy') === 'true');
    mode = 'saved'; await page.locator('#saved-rhr-refresh').click();
    await page.waitForFunction(() => document.querySelector('#saved-rhr-results').getAttribute('aria-busy') === 'false');
    if (held) await held.fulfill({json: {invalid: 'late response'}}).catch(() => {});
    assert.equal(await page.locator('#saved-rhr-feedback').getAttribute('data-failure-code'), null);
    assert.equal(await page.locator('[data-saved-provider]').count(), 2);
    assert.deepEqual(external, []); assert.deepEqual(errors, []);
    assert.ok(calls.every(item => item.method === 'GET'));
    const receipt = {candidate: process.env.HEALTHCHECK_CANDIDATE_SHA, calls: calls.length, external, errors, pngs: receipts};
    fs.writeFileSync(path.join(evidence, 'data-saved-rhr-browser.json'), JSON.stringify(receipt, null, 2));
    console.log(JSON.stringify(receipt, null, 2));
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
