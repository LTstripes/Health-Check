/* Offline browser check over captured production /imports HTML + synthetic API.
 * Fixture dir contains imports.html and freshness.json; external requests fail.
 */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const fixtures = process.env.HEALTHCHECK_DATA_FIXTURES_DIR;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.ok(fixtures && evidence);
const sha = execFileSync('git', ['rev-parse', 'HEAD'], {cwd: root, encoding: 'utf8'}).trim();
assert.equal(execFileSync('git', ['status', '--porcelain'], {cwd: root, encoding: 'utf8'}).trim(), '');
const base = 'http://127.0.0.1:8120';
const packet = JSON.parse(fs.readFileSync(path.join(fixtures, 'freshness.json'), 'utf8'));
function fixture(mode) {
  const value = structuredClone(packet);
  if (mode === 'missing') return value;
  for (const item of value.components) {
    Object.assign(item, {state: 'fresh', reason_code: 'evidence_current', actionable: false});
    Object.assign(item.facts, {latest_evidence_local_date: '2026-10-08',
      last_relevant_attempt_utc: '2026-10-11T09:00:00Z', last_successful_refresh_utc: '2026-10-08T09:00:00Z'});
    if (mode === 'partial' && item.provider === 'garmin' && item.role === 'required') {
      Object.assign(item, {state: 'unavailable', reason_code: 'reauth_required', actionable: true});
    }
    if (mode === 'partial' && item.scope_key === 'google:heart_rate') {
      Object.assign(item, {state: 'unavailable', reason_code: 'refresh_failed', actionable: true});
      item.facts.latest_evidence_local_date = '2026-10-03';
    }
    if (mode === 'partial' && item.scope_key === 'google:daily_spo2') {
      Object.assign(item, {state: 'not_requested', reason_code: 'disabled'});
    }
    if (mode === 'partial' && item.scope_key === 'garmin:spo2') {
      Object.assign(item, {state: 'not_requested', reason_code: 'not_requested'});
    }
  }
  value.providers.garmin.state = value.providers.google.state = value.owner.state = mode === 'partial' ? 'unavailable' : 'fresh';
  return value;
}
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE});
  const pngs = [];
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [], external = [], apiCalls = [];
    page.on('pageerror', error => errors.push(error.message));
    let mode = 'partial';
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) { external.push(url.href); return route.abort(); }
      if (url.pathname === '/api/source-freshness') {
        apiCalls.push({method: route.request().method(), mode});
        if (mode === 'error') return route.fulfill({status: 503, json: {code: 'database_unavailable'}});
        if (mode === 'invalid') return route.fulfill({json: {owner: {state: 'fresh'}}});
        return route.fulfill({json: fixture(mode)});
      }
      if (url.pathname === '/imports') return route.fulfill({body: fs.readFileSync(path.join(fixtures, 'imports.html')), contentType: 'text/html'});
      if (url.pathname.startsWith('/static/')) {
        const file = path.join(root, 'src/healthcheck/web', url.pathname);
        return route.fulfill({body: fs.readFileSync(file), contentType: file.endsWith('.css') ? 'text/css' : 'application/javascript'});
      }
      return route.fulfill({status: 404, body: ''});
    });
    fs.mkdirSync(evidence, {recursive: true});
    for (const width of [1024, 1440]) {
      await page.setViewportSize({width, height: 1000});
      for (const scenario of ['partial', 'success', 'missing', 'error']) {
        mode = scenario;
        await page.goto(base + '/imports');
        await page.waitForFunction(() => document.querySelector('#data-results').getAttribute('aria-busy') === 'false' && !document.querySelector('#data-refresh').hidden);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        assert.equal(await page.locator('#data-refresh').isDisabled(), false);
        assert.equal(await page.locator('#photo-extraction-status').getAttribute('data-configured'), 'false');
        assert.equal(await page.locator('#import-files').isDisabled(), true);
        if (scenario === 'error') {
          assert.equal(await page.locator('#data-feedback').getAttribute('data-failure-code'), 'database_unavailable');
          assert.equal(await page.locator('[data-provider]').count(), 0);
        } else {
          for (const provider of ['garmin', 'google']) {
            const card = page.locator(`[data-provider="${provider}"]`);
            assert.equal(await card.locator('details').getAttribute('open'), null);
            assert.equal(await card.locator('.data-stream').first().isVisible(), false);
            assert.equal(await card.locator('.data-actions').count(), scenario === 'success' ? 0 : 1);
          }
          if (scenario === 'partial') {
            const garmin = page.locator('[data-provider="garmin"]');
            assert.equal((await garmin.textContent()).match(/Повтори вход/g).length, 1);
            assert.match(await garmin.locator(':scope > dl').textContent(), /8 октября 2026/);
            assert.match(await garmin.locator(':scope > dl').textContent(), /11 октября 2026/);
            assert.match(await page.locator('[data-provider="google"] > dl').textContent(), /3 октября 2026 — 8 октября 2026/);
          }
          if (scenario === 'missing') assert.match(await page.locator('[data-provider="garmin"] > dl').textContent(), /Неизвестн/);
        }
        const name = `data-${scenario}-${width}.png`;
        await page.screenshot({path: path.join(evidence, name), fullPage: true});
        pngs.push(name);
        if (scenario === 'partial') {
          const summary = page.locator('[data-provider="google"] summary');
          await summary.focus(); await page.keyboard.press('Enter');
          assert.equal(await page.locator('[data-provider="google"] details').getAttribute('open'), '');
          assert.match(await page.locator('[data-scope="google:daily_spo2"]').textContent(), /Сбор отключён/);
          assert.equal(await page.locator('[data-scope="google:sleep"] [data-owner-state]').getAttribute('data-owner-state'), 'present');
          assert.equal(await page.locator('[data-scope="google:heart_rate"] [data-owner-state]').getAttribute('data-owner-state'), 'unavailable');
          const expanded = `data-partial-expanded-${width}.png`;
          await page.screenshot({path: path.join(evidence, expanded), fullPage: true}); pngs.push(expanded);
        }
      }
    }
    mode = 'invalid'; await page.locator('#data-refresh').click();
    await page.waitForFunction(() => document.querySelector('#data-feedback').dataset.failureCode === 'invalid_response');
    mode = 'success'; await page.locator('#data-refresh').click();
    await page.locator('[data-provider="garmin"]').waitFor();
    assert.equal(await page.locator('#data-feedback').getAttribute('data-failure-code'), null);
    assert.deepEqual(external, []); assert.deepEqual(errors, []);
    assert.ok(apiCalls.every(call => call.method === 'GET'));
    fs.writeFileSync(path.join(evidence, 'browser-result.json'), JSON.stringify({status: 'PASS', sha,
      fixtures: 'captured production route, synthetic payloads; no runtime or provider', apiCalls,
      checks: ['success/partial/missing/error', 'reauth deduplicated', 'saved dates vs attempts',
        'disabled/failed/present distinct', 'keyboard disclosure', 'retry/invalid response',
        'photo remains independent', '1024/1440 no overflow', 'no external requests'],
      screenshots: pngs}, null, 2));
    console.log(JSON.stringify({status: 'PASS', sha, screenshots: pngs}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
