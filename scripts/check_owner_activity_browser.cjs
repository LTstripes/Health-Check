/* Stage 6 narrow Chromium smoke. Use the disposable seed_activity fixture from
 * tests/test_activity_owner_ui.py, an explicit loopback URL and external evidence.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
if (!base || !evidence || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) {
  throw new Error('Explicit loopback synthetic URL and evidence directory required');
}
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    const page = await browser.newPage();
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {
      if (m.type() === 'error' && !(m.location().url || '').endsWith('/favicon.ico') &&
          !m.text().includes('503 (Service Unavailable)')) errors.push(m.text());
    });
    const query = '/garmin?metric_code=stress_daily_average&start_date=2099-01-01&end_date=2099-01-08';
    let series;
    async function geometry() {
      const g = await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth > innerWidth + 1,
        doc: document.documentElement.scrollWidth, view: innerWidth,
        navRows: new Set([...document.querySelector('.owner-nav').children].map(x => x.offsetTop)).size,
        targets: [...document.querySelectorAll('main button, main summary, [data-activity-mode]')]
          .filter(x => x.getBoundingClientRect().height).map(x => x.getBoundingClientRect().height) }));
      assert.equal(g.overflow, false, JSON.stringify(g));
      assert.equal(g.navRows, 1);
      assert.ok(g.targets.every(h => h >= 44), JSON.stringify(g.targets));
    }
    for (const width of [1100, 800, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base + query);
      assert.equal(await page.locator('html').getAttribute('lang'), 'ru');
      assert.equal(await page.locator('h1').innerText(), 'Активность');
      assert.equal(await page.locator('.owner-nav [aria-current]').innerText(), 'Активность');
      assert.equal(await page.locator('main [lang="en"]').count(), 0);
      assert.match(await page.locator('#activity-journal').innerText(), /Велотренировка/);
      assert.equal(await page.locator('#activity-ids option').count(), 2);
      await page.locator('#activity-form button').click();
      await page.waitForFunction(() => document.querySelector('#activity-result').getAttribute('aria-busy') === 'false');
      const comparison = await page.locator('#activity-result').innerText();
      assert.match(comparison, /Сопоставлено/);
      assert.match(comparison, /Не предоставлено|Не вычисляется/);
      assert.doesNotMatch(comparison, /r03-|result_hash|acute_training_load/);
      await geometry();
      await page.screenshot({ path: path.join(evidence, `sessions-${width}.png`), fullPage: true });
      await page.locator('[data-activity-mode="training-recovery"]').click();
      await page.waitForFunction(() => document.querySelector('#activity-journal').hidden);
      assert.equal(await page.locator('#activity-journal').isVisible(), false);
      assert.match(await page.locator('#training-recovery').innerText(), /Единица времени восстановления не предоставлена/);
      assert.match(await page.locator('#training-recovery').innerText(), /Производитель каждой метрики не подтверждён/);
      assert.equal(await page.locator('#series-chart svg circle').count(), 7);
      const chartPath = await page.locator('#series-chart svg path').getAttribute('d');
      assert.equal((chartPath.match(/M/g) || []).length, 2, 'missing day must break the line');
      assert.match(await page.locator('#series-summary').innerText(), /Данные доступны частично/);
      assert.match(await page.locator('#series-summary').innerText(), /явных нулей: 1/);
      assert.doesNotMatch(await page.locator('#series-summary').innerText(), /robust_z|result_hash/);
      await page.locator('#lag-form button').click();
      await page.waitForFunction(() => document.querySelector('#lag-result').getAttribute('aria-busy') === 'false');
      assert.match(await page.locator('#lag-result').innerText(), /Спирмен/);
      const tech = page.locator('details.activity-technical');
      assert.equal(await tech.getAttribute('open'), null);
      await tech.locator('summary').focus(); await page.keyboard.press('Enter');
      assert.equal(await tech.getAttribute('open'), '');
      assert.match(await tech.innerText(), /result_hash/);
      assert.match(await page.locator('#lag-evidence').innerText(), /exclusion_counts/);
      await geometry();
      await page.keyboard.press('Enter');
      assert.equal(await tech.getAttribute('open'), null);
      await geometry();
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({ path: path.join(evidence, `training-${width}.png`), fullPage: true });
      series = await page.locator('#series-evidence').textContent();
      checks.push(`${width}px: Russian sessions/training, all 3 analytics render, gap/zero/partial, keyboard disclosure, 44px targets, no overflow`);
    }
    // Force a late old completion after the latest submitted filters complete.
    let releaseOld, oldArrived;
    const oldGate = new Promise(resolve => { releaseOld = resolve; });
    const oldSeen = new Promise(resolve => { oldArrived = resolve; });
    await page.route('**/api/garmin/series?**', async route => {
      const start = new URL(route.request().url()).searchParams.get('start_date');
      const body = JSON.parse(series);
      body.result_hash = start === '2099-01-01' ? 'old-synthetic-result' : 'new-synthetic-result';
      if (start === '2099-01-01') { oldArrived(); await oldGate; }
      await route.fulfill({ json: body });
    });
    await page.locator('#series-start').fill('2099-01-01');
    await page.locator('#series-form button').click();
    await oldSeen;
    assert.match(await page.locator('#series-chart').innerText(), /Загрузка данных/);
    assert.equal(await page.locator('#series-summary').innerText(), '');
    await page.locator('#series-start').fill('2099-01-02');
    await page.locator('#series-form button').click();
    await page.waitForFunction(() => document.querySelector('#series-evidence').textContent.includes('new-synthetic-result'));
    const oldResponse = page.waitForResponse(r => r.url().includes('/api/garmin/series?') && r.url().includes('2099-01-01'));
    releaseOld(); await oldResponse;
    // Let the fetch response handlers and rendering settle without fixed sleeps.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.doesNotMatch(await page.locator('#series-evidence').innerText(), /old-synthetic-result/);
    assert.match(await page.locator('#series-context').innerText(), /2099-01-02/);
    await page.unroute('**/api/garmin/series?**');
    checks.push('Loading clears old result; latest submitted filter wins delayed-response race');
    await page.route('**/api/garmin/series?**', route => route.fulfill({ status: 503, json: {code:'synthetic_unavailable'} }));
    await page.locator('#series-form button').click();
    await page.waitForFunction(() => document.querySelector('#series-chart [role="alert"]'));
    assert.equal(await page.locator('#series-summary').innerText(), '');
    assert.match(await page.locator('#series-chart').innerText(), /Не удалось выполнить запрос/);
    await page.unroute('**/api/garmin/series?**');
    checks.push('Request failure is error with alert; no stale result survives');
    await page.locator('#garmin-source-id').selectOption('');
    await page.locator('#series-form button').click();
    assert.match(await page.locator('#series-evidence').textContent(), /Сначала примени источник/);
    checks.push('Unapplied source cannot query old activity IDs');
    await page.goto(base + '/garmin?metric_code=stress_daily_average&start_date=2099-02-01&end_date=2099-02-02#training-recovery');
    assert.equal(await page.locator('#series-chart svg').count(), 0);
    assert.match(await page.locator('#series-chart').innerText(), /Нет пригодных значений/);
    await geometry();
    checks.push('Narrow empty period is honest and usable');
    await page.locator('main a[href="/imports"]').first().click();
    await page.waitForURL('**/imports');
    assert.equal(await page.locator('h1').innerText(), 'Данные');
    checks.push('Data link reaches source status');
    assert.deepEqual(errors, []);
    const result = {status:'PASS', checks, errors};
    fs.writeFileSync(path.join(evidence, 'activity-stage6-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
