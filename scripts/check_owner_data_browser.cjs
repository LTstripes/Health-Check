/* Focused Stage-2 browser checks. Run against a disposable synthetic UI only.
 * NODE_PATH must expose playwright. Set HEALTHCHECK_BROWSER_BASE_URL,
 * HEALTHCHECK_BROWSER_EXECUTABLE and HEALTHCHECK_BROWSER_EVIDENCE_DIR.
 * No uploads, provider calls or database writes are performed by this check.
 */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
if (!base || !evidence || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) {
  throw new Error('Explicit loopback synthetic UI URL and evidence directory required');
}
const checks = [];
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE});
  try {
    const page = await browser.newPage({viewport: {width: 1100, height: 900}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const params = new URLSearchParams({evaluated_at_utc: new Date().toISOString(), evaluation_local_date: '2099-01-01'});
    const response = await page.request.get(base + '/api/source-freshness?' + params);
    assert.equal(response.status(), 200);
    const packet = await response.json();
    let mode = 'real';
    let calls = 0;
    let release;
    function fixture() {
      const value = structuredClone(packet);
      value.components.forEach(item => { item.state = 'unknown'; item.reason_code = 'never_observed'; item.actionable = item.role === 'required'; });
      function set(key, state, reason, facts = {}) {
        const item = value.components.find(item => item.scope_key === key);
        Object.assign(item, {state, reason_code: reason, actionable: item.role === 'required' && ['stale', 'unknown', 'unavailable'].includes(state)});
        Object.assign(item.facts, facts);
      }
      set('garmin:daily_summary', 'fresh', 'evidence_current', {last_successful_refresh_utc: '2026-10-04T09:00:00Z', latest_evidence_local_date: '2026-10-04'});
      set('garmin:sleep', 'stale', 'refresh_overdue');
      set('garmin:heart_rate', 'unavailable', 'reauth_required');
      set('garmin:activities', 'quiet', 'event_window_confirmed_empty', {activity_count: 0});
      set('garmin:spo2', 'not_requested', 'disabled', {disabled: true});
      set('google:sleep', 'quiet', 'evidence_within_grace');
      set('google:heart_rate', 'unknown', 'future_chronology');
      set('weight', 'quiet', 'voluntary_sampling', {confirmed_weight: true});
      value.providers.garmin.state = 'unavailable';
      value.providers.google.state = 'unknown';
      value.owner.state = 'unavailable';
      value.collection_policy = {status: 'invalid', problem_code: 'invalid_json'};
      return value;
    }
    await page.route('**/api/source-freshness?*', async route => {
      calls += 1;
      const url = new URL(route.request().url());
      assert.ok(url.searchParams.get('evaluated_at_utc').endsWith('Z'));
      assert.match(url.searchParams.get('evaluation_local_date'), /^\d{4}-\d{2}-\d{2}$/);
      assert.equal(route.request().method(), 'GET');
      if (mode === 'real') return route.continue();
      if (mode === 'delay') {
        await new Promise(resolve => { release = resolve; });
        return route.fulfill({json: fixture()});
      }
      if (mode === 'error') return route.fulfill({status: 503, json: {detail: 'database_unavailable'}});
      if (mode === 'malformed') return route.fulfill({json: {owner: {state: 'fresh'}, components: []}});
      if (mode === 'incomplete') {
        const value = fixture(); value.components.pop(); return route.fulfill({json: value});
      }
      if (mode === 'safe-text') {
        const value = fixture(); value.components[0].reason_code = '<img src=x onerror=alert(1)>';
        return route.fulfill({json: value});
      }
      return route.fulfill({json: fixture()});
    });
    await page.goto(base + '/imports');
    await page.locator('[data-provider="garmin"]').waitFor();
    assert.equal(await page.locator('#data-feedback [data-owner-state]').getAttribute('data-owner-state'), 'unknown');
    assert.ok(await page.locator('#data-results').textContent());
    checks.push('real persisted API renders without inferring fresh/empty');
    assert.match(await page.locator('#import-queue').textContent(), /Ожидают проверки:/);
    const table = page.getByRole('region', {name: 'История загрузок, прокрутка таблицы'});
    assert.equal(await table.locator('table').count(), 1);
    const review = table.getByRole('link', {name: 'Проверить'}).first();
    assert.match(await review.getAttribute('href'), /^\/imports\//);
    assert.match(await page.locator('#import-queue').textContent(), /не более 50/);
    checks.push('populated synthetic queue keeps bounded counts, existing review links and real table layout');

    mode = 'delay';
    await page.getByRole('button', {name: 'Проверить состояние'}).click();
    await page.locator('#data-feedback [data-owner-state="loading"]').waitFor();
    assert.equal(await page.locator('#data-results').getAttribute('aria-busy'), 'true');
    assert.equal(await page.locator('[data-provider]').count(), 0);
    assert.equal(await page.locator('#data-clock').textContent(), '');
    assert.equal(await page.locator('#data-refresh').isDisabled(), true);
    const beforeCalls = calls;
    await page.locator('#data-refresh').evaluate(button => button.click());
    assert.equal(calls, beforeCalls);
    while (!release) await new Promise(resolve => setTimeout(resolve, 10));
    release();
    await page.locator('[data-provider="weight"]').waitFor();
    checks.push('loading clears previous results/clocks and prevents concurrent requests');
    const garmin = page.locator('[data-provider="garmin"]');
    const google = page.locator('[data-provider="google"]');
    assert.equal(await garmin.locator('[data-scope="garmin:daily_summary"] [data-owner-state]').getAttribute('data-owner-state'), 'present');
    assert.equal(await garmin.locator('[data-scope="garmin:sleep"] [data-owner-state]').getAttribute('data-owner-state'), 'partial');
    assert.match(await garmin.textContent(), /устарело/);
    assert.match(await page.locator('.data-actions').textContent(), /Повтори вход/);
    assert.ok(!(await page.locator('.data-actions').textContent()).includes('Кислород'));
    assert.equal(await google.locator('[data-scope="google:sleep"] [data-owner-state]').getAttribute('data-owner-state'), 'present');
    assert.match(await google.textContent(), /пауза/);
    assert.equal(await google.locator('[data-scope="google:heart_rate"] [data-owner-state]').getAttribute('data-owner-state'), 'unknown');
    assert.match(await google.textContent(), /будущего/);
    assert.match(await page.locator('[data-provider="weight"]').textContent(), /ежедневный сбор не ожидается/);
    assert.match(await page.locator('#data-results').textContent(), /Настройки сбора недоступны/);
    assert.equal(await page.locator('#data-results details[open]').count(), 0);
    assert.equal(await page.locator('img[src="x"]').count(), 0);
    checks.push('fresh/stale/reauth/quiet/weight/future chronology and invalid collection policy remain distinct');

    await garmin.locator('summary').click();
    assert.equal(await garmin.locator('[data-scope="garmin:activities"] [data-owner-state]').getAttribute('data-owner-state'), 'confirmed_empty');
    assert.equal(await garmin.locator('[data-scope="garmin:spo2"] [data-owner-state]').getAttribute('data-owner-state'), 'not_requested');
    assert.match(await garmin.locator('[data-scope="garmin:spo2"]').textContent(), /Сбор отключён/);
    assert.match(await garmin.locator('[data-scope="garmin:activities"]').textContent(), /подтверждённая пустота/);
    checks.push('optional streams disclose confirmed empty and disabled without inventing owner actions');
    const technical = page.locator('#data-results > details');
    await technical.locator('summary').focus();
    await page.keyboard.press('Enter');
    assert.equal(await technical.getAttribute('open'), '');
    assert.match(await technical.textContent(), /source-freshness-v1/);
    checks.push('keyboard disclosure retains exact technical evidence');

    fs.mkdirSync(evidence, {recursive: true});
    for (const width of [1100, 800, 480, 360]) {
      await page.setViewportSize({width, height: 900});
      const geometry = await page.evaluate(() => {
        const nav = document.querySelector('.owner-nav');
        const grid = document.querySelector('.data-source-grid');
        const active = nav.querySelector('[aria-current="page"]');
        return {
          overflow: document.documentElement.scrollWidth > innerWidth,
          columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
          navRows: new Set([...nav.children].map(item => item.offsetTop)).size,
          height: document.querySelector('#data-refresh').getBoundingClientRect().height,
          active: active.textContent,
          background: getComputedStyle(document.body).backgroundColor,
          border: getComputedStyle(active).borderBottomColor,
          radius: getComputedStyle(grid.firstChild).borderRadius
        };
      });
      assert.equal(geometry.overflow, false);
      assert.equal(geometry.columns, width <= 800 ? 1 : 2);
      assert.equal(geometry.navRows, 1);
      assert.ok(geometry.height >= 44);
      assert.equal(geometry.active, 'Данные');
      assert.equal(geometry.background, 'rgb(243, 241, 236)');
      assert.equal(geometry.border, 'rgb(31, 92, 87)');
      assert.equal(geometry.radius, '8px');
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({path: path.join(evidence, 'data-' + width + '.png')});
    }
    checks.push('1100/800/480/360px: frozen tokens, one narrow column, nav row, 44px target, no document overflow with disclosures open');
    for (const failure of ['error', 'malformed', 'incomplete']) {
      mode = failure;
      await page.locator('#data-refresh').click();
      await page.locator('#data-feedback [data-owner-state="error"]').waitFor();
      assert.equal(await page.locator('#data-feedback').getAttribute('role'), 'alert');
      assert.equal(await page.locator('[data-provider]').count(), 0);
      assert.equal(await page.locator('#data-clock').textContent(), '');
      assert.equal(await page.locator('#data-refresh').isDisabled(), false);
      assert.match(await page.locator('#import-queue').textContent(), /Проверка импорта/);
    }
    checks.push('503, malformed and incomplete response clear prior success and permit retry');
    mode = 'safe-text';
    await page.locator('#data-refresh').click();
    await page.locator('[data-provider="garmin"]').waitFor();
    assert.equal(await page.locator('img[src="x"]').count(), 0);
    assert.equal(await page.locator('#data-feedback').getAttribute('role'), 'status');
    assert.match(await page.locator('[data-provider="garmin"]').textContent(), /Состояние требует проверки/);
    assert.deepEqual(errors, []);
    checks.push('retry recovers; unknown reason uses plain text and never executable HTML');
    // A stalled request must stop being loading and recover without old results.
    mode = 'delay';
    release = undefined;
    await page.locator('#data-refresh').click();
    await page.locator('#data-feedback [data-owner-state="error"]').waitFor({timeout: 20000});
    assert.equal(await page.locator('#data-refresh').isDisabled(), false);
    assert.equal(await page.locator('[data-provider]').count(), 0);
    release();
    checks.push('timeout clears loading, retains unknown source state and allows retry');
    const noJS = await browser.newContext({javaScriptEnabled: false});
    const fallback = await noJS.newPage();
    await fallback.goto(base + '/imports');
    assert.equal(await fallback.locator('#data-refresh').isVisible(), false);
    assert.match(await fallback.locator('noscript').textContent(), /Свежесть источников не проверена/);
    assert.equal(await fallback.locator('#import-files').isVisible(), true);
    await noJS.close();
    checks.push('no JavaScript keeps explicit unverified freshness and working import form');
    fs.writeFileSync(path.join(evidence, 'browser-result.json'), JSON.stringify({status: 'PASS', checks}, null, 2));
    console.log(JSON.stringify({status: 'PASS', checks}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
