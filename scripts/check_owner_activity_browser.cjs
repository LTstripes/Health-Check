/* #309 Garmin Activity Chromium checks. Use the disposable seed_activity fixture from
 * tests/test_activity_owner_ui.py, an explicit loopback URL and external evidence.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
function candidateIdentity() {
  const git = args => execFileSync('git', args, { cwd: path.join(__dirname, '..'), encoding: 'utf8' }).trim();
  return { sha: git(['rev-parse', 'HEAD']), tree: git(['rev-parse', 'HEAD^{tree}']),
    trackedChanges: git(['diff', '--name-only', 'HEAD']), untracked: git(['ls-files', '--others', '--exclude-standard']) };
}
const candidate = candidateIdentity();
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const emptyBase = process.env.HEALTHCHECK_BROWSER_EMPTY_URL;
const multiBase = process.env.HEALTHCHECK_BROWSER_MULTI_URL;
if (!evidence || [base, emptyBase, multiBase].some(url => !url || !/^http:\/\/127\.0\.0\.1:\d+$/.test(url))) {
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
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base + query);
      assert.equal(await page.locator('html').getAttribute('lang'), 'ru');
      assert.equal(await page.locator('h1').innerText(), 'Активность');
      assert.equal(await page.locator('.owner-nav [aria-current]').innerText(), 'Активность');
      assert.equal(await page.locator('main [lang="en"]').count(), 0);
      assert.match(await page.locator('#activity-journal').innerText(), /Велотренировка/);
      assert.match(await page.locator('#activity-journal').innerText(), /1 января 2099/);
      assert.doesNotMatch(await page.locator('#activity-journal').innerText(), /2099-01-01/);
      assert.equal(await page.locator('#source-form, #garmin-source-id').count(), 0);
      assert.match(await page.locator('main').innerText(), /Сессии Google пока не загружаются/);
      assert.equal(await page.locator('.activity-technical').count(), 1);
      const ids = await page.locator('#activity-a option').evaluateAll(options => options.map(o => o.value).filter(Boolean));
      assert.equal(ids.length, 2);
      assert.equal(await page.locator('#activity-form button').isDisabled(), true);
      await page.locator('#activity-a').selectOption(ids[0]);
      assert.match(await page.locator('#activity-selection-hint').innerText(), /Теперь выбери другую сессию B/);
      await page.locator('#activity-b').selectOption(ids[0]);
      assert.equal(await page.locator('#activity-form button').isDisabled(), true);
      assert.match(await page.locator('#activity-selection-hint').innerText(), /одна и та же/);
      await page.locator('#activity-b').selectOption(ids[1]);
      assert.equal(await page.locator('#activity-form button').isEnabled(), true);
      await page.locator('#activity-form button').focus();
      await page.keyboard.press('Enter');
      await page.waitForFunction(() => document.querySelector('#activity-result').getAttribute('aria-busy') === 'false');
      const comparison = await page.locator('#activity-result').innerText();
      assert.match(comparison, /Сопоставлено/);
      assert.match(comparison, /Не предоставлено|Не вычисляется/);
      assert.match(comparison, /B минус A/);
      assert.match(comparison, /Сессия A.*Сессия B/s);
      assert.match(comparison, /Сессия A: значение не предоставлено; Сессия B: значение не предоставлено/);
      assert.doesNotMatch(comparison, /r03-|result_hash|acute_training_load/);
      const initial = JSON.parse(await page.locator('#activity-evidence').textContent());
      assert.equal(initial.query.reference_activity_id, ids[0]);
      assert.deepEqual([...initial.query.activity_record_ids].sort(), [...ids].sort());
      const load = initial.comparisons[0].metrics.find(m => m.metric_code === 'acute_training_load');
      assert.equal(load.absolute_delta, 10);
      assert.equal(load.percent_reason, 'zero_reference_percent');
      assert.match(comparison, /В сессии A указан ноль/);
      await geometry();
      await page.evaluate(() => scrollTo(0, 0));
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
      assert.equal(await page.locator('.activity-lags').getAttribute('open'), null);
      await page.locator('.activity-lags > summary').click();
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
      checks.push(`${width}px: Garmin-only single source, explicit A/B flow, duplicate guard, zero-reference explanation, real service result, Russian training, keyboard submit/disclosure, 44px targets, no overflow`);
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
    assert.match(await page.locator('#series-context').innerText(), /2 января 2099/);
    await page.unroute('**/api/garmin/series?**');
    checks.push('Loading clears old result; latest submitted filter wins delayed-response race');
    await page.route('**/api/garmin/series?**', route => route.fulfill({ status: 503, json: {code:'synthetic_unavailable'} }));
    await page.locator('#series-form button').click();
    await page.waitForFunction(() => document.querySelector('#series-chart [role="alert"]'));
    assert.equal(await page.locator('#series-summary').innerText(), '');
    assert.match(await page.locator('#series-chart').innerText(), /Не удалось выполнить запрос/);
    await page.unroute('**/api/garmin/series?**');
    checks.push('Request failure is error with alert; no stale result survives');
    await page.goto(base + query);
    const ids = await page.locator('#activity-a option').evaluateAll(options => options.map(o => o.value).filter(Boolean));
    async function choosePair(a, b) {
      await page.locator('#activity-a').selectOption(a);
      await page.locator('#activity-b').selectOption(b);
    }
    async function compare() {
      await page.locator('#activity-form button').click();
      await page.waitForFunction(() => document.querySelector('#activity-result').getAttribute('aria-busy') === 'false');
    }
    await choosePair(ids[1], ids[0]);
    await compare();
    let body = JSON.parse(await page.locator('#activity-evidence').textContent());
    const reversed = body.comparisons[0].metrics.find(m => m.metric_code === 'acute_training_load');
    assert.equal(reversed.absolute_delta, -10);
    assert.equal(reversed.percent_delta, -100);
    assert.match(await page.locator('#activity-result').innerText(), /-10\.0/);
    assert.match(await page.locator('#activity-result').innerText(), /-100\.0/);
    checks.push('Swapping A/B changes the actual service reference, delta sign and percentage basis');

    // An old comparison cannot survive a changed selection or replace a newer pair.
    let releaseComparison, comparisonArrived;
    const comparisonGate = new Promise(resolve => { releaseComparison = resolve; });
    const comparisonSeen = new Promise(resolve => { comparisonArrived = resolve; });
    await page.route('**/api/garmin/activity-comparison?**', async route => {
      const response = await route.fetch();
      const json = await response.json();
      if (new URL(route.request().url()).searchParams.get('reference_activity_id') === ids[1]) {
        comparisonArrived(); await comparisonGate;
        json.result_hash = 'delayed-old-comparison';
      } else json.result_hash = 'latest-comparison';
      await route.fulfill({ json });
    });
    await page.locator('#activity-form button').click();
    await comparisonSeen;
    assert.match(await page.locator('#activity-result').innerText(), /Загрузка данных/);
    assert.equal(await page.locator('#activity-evidence').textContent(), '');
    await choosePair(ids[0], ids[1]);
    assert.equal(await page.locator('#activity-result').innerText(), '');
    await compare();
    assert.match(await page.locator('#activity-evidence').textContent(), /latest-comparison/);
    const oldComparison = page.waitForResponse(r => r.url().includes('/api/garmin/activity-comparison?') && new URL(r.url()).searchParams.get('reference_activity_id') === ids[1]);
    releaseComparison(); await oldComparison;
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.doesNotMatch(await page.locator('#activity-evidence').textContent(), /delayed-old-comparison/);
    await page.unroute('**/api/garmin/activity-comparison?**');
    checks.push('Changing A/B clears old results and rejects delayed comparison completions');
    await page.route('**/api/garmin/activity-comparison?**', route => route.fulfill({ status: 503, json: {code:'synthetic_unavailable'} }));
    await compare();
    assert.match(await page.locator('#activity-result [role="alert"]').innerText(), /Не удалось выполнить запрос/);
    await page.unroute('**/api/garmin/activity-comparison?**');
    await compare();
    assert.match(await page.locator('#activity-result').innerText(), /Сопоставлено/);
    checks.push('Comparison error clears stale output and retry recovers');

    await page.goto(multiBase + '/garmin');
    assert.match(await page.locator('#source-status').innerText(), /Выбери источник Garmin/);
    assert.equal(await page.locator('#activity-form button').isDisabled(), true);
    const sources = await page.locator('#garmin-source-id option').evaluateAll(options => options.map(o => o.value).filter(Boolean));
    assert.equal(sources.length, 2);
    await page.locator('#garmin-source-id').selectOption(sources[0]);
    await page.locator('#source-form button').click();
    await page.waitForURL(url => url.searchParams.get('garmin_source_id') === sources[0]);
    const sourceIds = await page.locator('#activity-a option').evaluateAll(options => options.map(o => o.value).filter(Boolean));
    assert.equal(sourceIds.length, 2);
    await choosePair(sourceIds[0], sourceIds[1]);
    await compare();
    body = JSON.parse(await page.locator('#activity-evidence').textContent());
    assert.equal(body.query.garmin_source_id, sources[0]);
    let requests = 0;
    const countComparison = request => { if (request.url().includes('/api/garmin/activity-comparison?')) requests++; };
    page.on('request', countComparison);
    await page.locator('#garmin-source-id').selectOption(sources[1]);
    await page.locator('#activity-form button').click();
    assert.equal(requests, 0);
    assert.match(await page.locator('#activity-result').innerText(), /Сначала примени источник/);
    await page.locator('#source-form button').click();
    await page.waitForURL(url => url.searchParams.get('garmin_source_id') === sources[1]);
    const nextIds = await page.locator('#activity-a option').evaluateAll(options => options.map(o => o.value).filter(Boolean));
    assert.equal(nextIds.length, 2);
    assert.ok(nextIds.every(id => !sourceIds.includes(id)));
    await choosePair(nextIds[0], nextIds[1]);
    await compare();
    body = JSON.parse(await page.locator('#activity-evidence').textContent());
    assert.equal(body.query.garmin_source_id, sources[1]);
    page.off('request', countComparison);
    checks.push('Multiple sources require application; source switch resets pair and cannot query old IDs');
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(emptyBase + '/garmin');
      assert.equal(await page.locator('#source-form').count(), 0);
      assert.equal(await page.locator('#activity-form button').isDisabled(), true);
      assert.equal(await page.locator('#activity-a').isDisabled(), true);
      assert.match(await page.locator('#activity-selection-hint').innerText(), /Пока их недостаточно/);
      assert.match(await page.locator('#source-status').innerText(), /Источник Garmin пока не найден/);
      await geometry();
      await page.screenshot({ path: path.join(evidence, `empty-${width}.png`), fullPage: true });
    }
    checks.push('Empty Garmin stores show an explanation and disabled comparison at all widths');
    await page.goto(base + query);
    await page.goto(base + '/garmin?metric_code=stress_daily_average&start_date=2099-02-01&end_date=2099-02-02#training-recovery');
    assert.equal(await page.locator('#series-chart svg').count(), 0);
    assert.match(await page.locator('#series-chart').innerText(), /Нет пригодных значений/);
    await geometry();
    checks.push('Desktop empty period is honest and usable');
    await page.locator('main a[href="/imports"]').first().click();
    await page.waitForURL('**/imports');
    assert.equal(await page.locator('h1').innerText(), 'Данные');
    checks.push('Data link reaches source status');
    assert.deepEqual(errors, []);
    assert.deepEqual(candidateIdentity(), candidate, 'Candidate must remain unchanged during browser checks');
    const result = {status:'PASS', candidate, checks, errors};
    fs.writeFileSync(path.join(evidence, 'activity-309-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
