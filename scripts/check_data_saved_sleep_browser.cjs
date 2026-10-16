/* Offline production HTML + synthetic production DTOs; desktop-only evidence. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const fixture = process.env.HEALTHCHECK_DATA_FIXTURES_DIR;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.ok(fixture && evidence);
const read = name => JSON.parse(fs.readFileSync(path.join(fixture, name + '.json'), 'utf8'));
const base = 'http://127.0.0.1:8120';
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE});
  const external = [], errors = [], calls = [], images = [], checks = [];
  try {
    const context = await browser.newContext({timezoneId: 'UTC'});
    await context.addInitScript(timestamp => {
      const NativeDate = Date;
      window.Date = class extends NativeDate {
        constructor(...args) { super(...(args.length ? args : [timestamp])); }
        static now() { return new NativeDate(timestamp).getTime(); }
      };
    }, read('saved').evaluated_at_utc);
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    let mode = 'saved', held;
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) { external.push(url.href); return route.abort(); }
      if (url.pathname === '/imports') return route.fulfill({body: fs.readFileSync(path.join(fixture, 'imports.html')), contentType: 'text/html'});
      if (url.pathname === '/api/source-freshness') return route.fulfill({json: read('freshness')});
      if (url.pathname === '/api/imports/saved-rhr') return route.fulfill({json: read('saved-rhr')});
      if (url.pathname === '/api/imports/saved-sleep') {
        calls.push({url: url.href, method: route.request().method(), mode});
        if (mode === 'held') { held = route; return; }
        if (mode === 'error') return route.fulfill({status: 503, json: {code: 'saved_sleep_read_unavailable', secret: 'synthetic-secret'}});
        let body = read(mode === 'malformed' ? 'saved' : mode);
        if (mode === 'ambiguous' && url.searchParams.has('google_source_id')) {
          body = read('selected');
          assert.equal(body.items[1].requested_source_id, url.searchParams.get('google_source_id'));
        }
        if (mode === 'malformed') body.items[0].observation.observation_age_days = 0;
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
      for (const scenario of ['saved', 'auto', 'conflict', 'zero', 'ambiguous', 'cap', 'error']) {
        mode = scenario;
        await page.goto(base + '/imports');
        await page.waitForFunction(() => document.querySelector('#saved-sleep-results').getAttribute('aria-busy') === 'false');
        const section = page.locator('#saved-sleep');
        await section.scrollIntoViewIfNeeded();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        const rect = await section.boundingBox();
        const nav = await page.locator('.owner-nav').boundingBox();
        assert.ok(!nav || rect.y > nav.y + nav.height, 'sleep card overlaps sticky navigation');
        assert.equal(await section.locator('pre').count(), 0, 'no technical wall');
        if (scenario === 'error') {
          assert.equal(await section.locator('[role="alert"]').count(), 1);
          assert.doesNotMatch(await section.innerText(), /synthetic-secret/);
        } else {
          assert.equal(await section.locator('[data-sleep-provider]').count(), 2);
          if (scenario === 'saved' || scenario === 'auto') {
            assert.match(await section.innerText(), /8 ч 0 мин/);
            assert.match(await section.innerText(), /6 ч 50 мин/);
            for (const dto of read('saved').items) {
              const card = section.locator(`[data-sleep-provider="${dto.provider}"]`);
              const formatted = await page.evaluate(day => window.healthcheckOwnerDate(day), dto.observation.wake_date);
              assert.ok((await card.innerText()).includes(formatted));
              assert.ok((await card.innerText()).includes(`Возраст: ${dto.observation.observation_age_days} дн.`));
              assert.doesNotMatch(await card.innerText(), /\d{4}-\d{2}-\d{2}/);
            }
          }
          if (scenario === 'auto') {
            const card = section.locator('[data-sleep-provider="google"]');
            assert.equal(read('auto').items[1].available_sources.length, 5);
            assert.equal(await card.locator('details:not([open])').count(), 1);
            assert.equal(await card.locator('select').isVisible(), false);
            assert.equal(await card.locator('.saved-sleep-duration').count(), 1);
            await card.locator('summary').focus();
            await page.keyboard.press('Enter');
            assert.equal(await card.locator('select').isVisible(), true);
            assert.equal(await card.locator('select').inputValue(), '');
            await page.keyboard.press('Enter');
            checks.push({width, automatic_google_value_without_choice: 'PASS'});
          }
          if (scenario === 'conflict') assert.match(await section.innerText(), /Более новые ночи с конфликтом/);
          if (scenario === 'zero') {
            assert.equal(await section.locator('.saved-sleep-duration').count(), 2);
            assert.equal(await section.locator('.saved-sleep-duration').first().textContent(), '0 ч 0 мин');
            assert.match(await section.innerText(), /Запись частичная/);
            assert.match(await section.innerText(), /Основная роль этой сессии не подтверждена/);
          }
          if (scenario === 'cap') assert.match(await section.innerText(), /Поиск ограничен/);
          if (scenario === 'ambiguous') {
            assert.match(await section.innerText(), /Нужен выбор источника/);
            assert.equal(await section.locator('[data-sleep-provider="google"] .saved-sleep-duration').count(), 0);
          }
        }
        const file = path.join(evidence, `saved-sleep-${scenario}-${width}.png`);
        await page.screenshot({path: file});
        images.push({file: path.basename(file), width, scenario, sha256: crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')});
        if (scenario === 'ambiguous') {
          const select = section.locator('#sleep-source-google');
          await select.focus();
          const options = await select.locator('option').evaluateAll(items => items.map(x => x.value));
          const target = read('selected').items[1].requested_source_id;
          assert.equal(options[1], target);
          await page.keyboard.press('ArrowDown');
          await page.keyboard.press('Enter');
          await page.waitForFunction(() => document.querySelector('#saved-sleep-results').getAttribute('aria-busy') === 'false');
          assert.equal(await page.evaluate(() => document.activeElement.id), 'sleep-source-google');
          assert.equal(await section.locator('[data-sleep-provider="google"] .saved-sleep-duration').count(),
            Number(Boolean(read('selected').items[1].observation)));
          checks.push({width, keyboard_source_choice: 'PASS'});
        }
      }
    }
    mode = 'malformed'; await page.goto(base + '/imports');
    await page.waitForFunction(() => document.querySelector('#saved-sleep-feedback').getAttribute('role') === 'alert');
    assert.equal(await page.locator('.saved-sleep-duration').count(), 0);
    mode = 'held'; await page.goto(base + '/imports');
    await page.waitForFunction(() => document.querySelector('#saved-sleep-results').getAttribute('aria-busy') === 'true');
    while (!held) await new Promise(resolve => setTimeout(resolve, 10));
    mode = 'saved'; await page.locator('#saved-sleep-refresh').focus(); await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('#saved-sleep-results').getAttribute('aria-busy') === 'false');
    await held.fulfill({json: read('zero')}).catch(() => {});
    assert.match(await page.locator('#saved-sleep-results').innerText(), /8 ч 0 мин/);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'saved-sleep-refresh');
    assert.deepEqual(external, []); assert.deepEqual(errors, []);
    assert.ok(calls.every(call => call.method === 'GET'));
    const inputs = [
      'src/healthcheck/saved_sleep.py', 'src/healthcheck/metric_source_selection.py',
      'src/healthcheck/web/imports.py',
      'src/healthcheck/web/templates/imports.html', 'src/healthcheck/web/static/data_saved_sleep.js',
      'scripts/prepare_data_saved_sleep_browser.py', 'scripts/check_data_saved_sleep_browser.cjs',
    ].map(file => ({file, sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex')}));
    const fixtures = fs.readdirSync(fixture).filter(file => /\.(json|html)$/.test(file))
      .map(file => ({file, sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(fixture, file))).digest('hex')}));
    fs.writeFileSync(path.join(evidence, 'receipt.json'), JSON.stringify({status: 'PASS', mode: 'offline production HTML/DTO replay; synthetic only', browser: browser.version(), inputs, fixtures, images, checks, external, errors, calls, stale_response: 'PASS', malformed: 'PASS'}, null, 2));
    console.log('PASS: synthetic desktop sleep, keyboard, safe failures, stale response, no external requests');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
