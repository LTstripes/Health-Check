/* #492/#495: production UI, explicit disposable synthetic fixture URLs only.
 * serve_owner_acceptance_fixture.py --overview-a-plus and --empty, on separate
 * loopback ports. NODE_PATH supplies isolated Playwright. No provider requests.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const root = path.join(__dirname, '..');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const empty = process.env.HEALTHCHECK_BROWSER_EMPTY_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
for (const url of [base, empty]) assert.match(url || '', /^http:\/\/127\.0\.0\.1:\d+$/);
assert.ok(evidence && !path.resolve(evidence).startsWith(root), 'External evidence directory required');
const git = args => execFileSync('git', args, {cwd: root, encoding: 'utf8'}).trim();
const sha256 = value => createHash('sha256').update(value).digest('hex');
const checks = [], screenshots = [], errors = [], forbidden = [];
const report = {candidate: {sha: git(['rev-parse', 'HEAD']), diffSha256: sha256(git(['diff', 'HEAD'])),
  trackedChanges: git(['diff', '--name-only', 'HEAD'])}, fixture: 'synthetic Stage7 overview-a-plus / empty',
  checks, screenshots, errors, forbidden};

(async () => {
  fs.mkdirSync(evidence, {recursive: true});
  const browser = await chromium.launch({headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ? {executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE} : {})});
  try {
    const context = await browser.newContext({acceptDownloads: true, timezoneId: 'Europe/Moscow'});
    await context.route('**/*', route => {
      const url = route.request().url();
      if (url.startsWith(base + '/') || url.startsWith(empty + '/') || url.startsWith('blob:')) return route.continue();
      forbidden.push(url); return route.abort();
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    report.assets = {};
    for (const name of ['dashboard.css', 'analysis_export.js']) {
      const response = await page.request.get(base + '/static/' + name);
      assert.equal(response.status(), 200);
      const expected = fs.readFileSync(path.join(root, 'src/healthcheck/web/static', name));
      assert.equal(sha256(await response.body()), sha256(expected), `Exact served asset ${name}`);
      report.assets[name] = sha256(expected);
    }
    await page.goto(base + '/');
    assert.equal(new URL(page.url()).pathname, '/brief');
    assert.equal(await page.locator('#analysis-export-form').count(), 0);
    assert.equal(await page.locator('a[href="/imports#analysis-export"]').count() > 0, true);
    await page.goto(base + '/?view=history&source=synthetic');
    assert.equal(new URL(page.url()).pathname, '/weight');
    assert.equal(new URL(page.url()).search, '?view=history&source=synthetic');
    assert.equal(await page.locator('.owner-nav [aria-current="page"]').innerText(), 'Вес');
    checks.push('Bare entry Overview; exact legacy Weight query redirect; canonical Weight active navigation');

    const routes = [
      ['overview', '/brief?start_date=2099-01-01&end_date=2099-01-08'],
      ['data', '/imports'],
      ['statistics', '/statistics?period=7&end_date=2099-01-08'],
      ['sleep', '/sleep?wake_date=2099-01-02'],
      ['activity', '/garmin?start_date=2099-01-01&end_date=2099-01-08'],
      ['compare', '/agreement'],
    ];
    for (const width of [1024, 1440]) {
      await page.setViewportSize({width, height: 960});
      for (const [state, origin] of [['filled-partial', base], ['empty', empty]]) {
        for (const [name, route] of routes) {
          const response = await page.goto(origin + route);
          assert.equal(response.status(), 200, `${state}/${name}`);
          if (name === 'data') await page.waitForFunction(() => !/Загрузка|Проверяем/.test(document.getElementById('analysis-export-status').textContent));
          await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${state}/${name}/${width} horizontal overflow`);
          assert.deepEqual(await page.locator('.owner-info > summary').evaluateAll(nodes => nodes
            .filter(el => el.getBoundingClientRect().height > 0)
            .filter(el => el.getBoundingClientRect().height < 44)
            .map(el => el.textContent.trim())), [], `${state}/${name}/${width} info target below 44px`);
          if (name === 'overview') assert.equal(await page.locator('#analysis-export-form').count(), 0);
          if (name === 'data') {
            assert.match(await page.locator('#analysis-export').innerText(), /ваши комментарии/);
            assert.equal(await page.locator('#analysis-export-form > button').innerText(), 'Скачать');
            assert.equal(await page.locator('.data-saved-diagnostics').evaluate(el => el.open), false);
          }
          if (name === 'statistics') {
            assert.equal(await page.locator('.statistics-details:not(.statistics-source-choice)[open]').count(), 0);
            assert.equal(await page.locator('[data-statistics-metric="activity_session_count"] article').count(), 1);
            if (state === 'filled-partial') assert.match(await page.locator('.statistics-denominator').allTextContents().then(a => a.join(' ')), /неполный период/);
          }
          if (name === 'sleep') assert.equal(await page.locator('[data-sleep-freshness]').evaluate(el => el.open), false);
          const filename = `${state}-${name}-${width}.png`;
          await page.screenshot({path: path.join(evidence, filename), fullPage: true});
          screenshots.push({state, page: name, width, file: filename});
          if (['overview', 'data', 'statistics'].includes(name)) {
            const top = `${state}-${name}-${width}-viewport.png`;
            await page.screenshot({path: path.join(evidence, top)});
            screenshots.push({state, page: name, width, file: top, view: 'primary viewport'});
          }
          if (name === 'statistics') {
            await page.locator('#metric-sleep_duration_asleep_seconds').scrollIntoViewIfNeeded();
            const sleep = `${state}-statistics-sleep-${width}-viewport.png`;
            await page.screenshot({path: path.join(evidence, sleep)});
            screenshots.push({state, page: name, width, file: sleep, view: 'sleep metric viewport'});
          }
        }
      }
    }
    checks.push('24 real Chrome desktop screenshots: 1024/1440, populated/partial and empty, six existing sections; no horizontal overflow');
    checks.push('Routine diagnostics initially closed; unsupported Google cards absent; real partial-window qualifier remains visible');

    await page.goto(base + '/imports#analysis-export');
    const inventoryResponse = await page.request.get(base + '/api/analysis-export/sources');
    assert.equal(inventoryResponse.headers()['cache-control'], 'no-store');
    const inventory = (await inventoryResponse.json()).sources;
    const garmin = inventory.filter(row => row.provider === 'garmin_connect');
    const google = inventory.filter(row => row.provider === 'google_health');
    await page.waitForFunction(() => !document.querySelector('select[name="garmin_source_id"]').disabled);
    assert.equal(await page.locator('#analysis-export-options').evaluate(el => el.open), garmin.length !== 1 || google.length > 1);
    if (garmin.length !== 1) await page.selectOption('[name="garmin_source_id"]', garmin[0].id);
    await page.fill('[name="end_date"]', '2099-01-08');
    await page.selectOption('[name="days"]', '7');
    const payloads = [];
    page.on('request', request => {
      if (request.url() === base + '/api/analysis-export') payloads.push(request.postDataJSON());
    });
    const downloadPromise = page.waitForEvent('download');
    const responsePromise = page.waitForResponse(r => r.url() === base + '/api/analysis-export' && r.request().method() === 'POST');
    await page.click('#analysis-export-form > button');
    const [download, response] = await Promise.all([downloadPromise, responsePromise]);
    assert.equal(response.status(), 200);
    assert.equal(response.headers()['cache-control'], 'no-store');
    assert.match(download.suggestedFilename(), /\.txt$/);
    assert.equal(payloads.length, 1);
    assert.equal(payloads[0].garmin_source_id, garmin[0].id);
    assert.equal(payloads[0].google_hrv_source_id, google.length === 1 ? google[0].id : null);
    assert.equal(payloads[0].steps_view, 'completed');
    const packet = JSON.parse((await response.json()).json);
    assert.deepEqual(Object.keys(packet.sections).sort(), ['activity','body_battery','context','hrv','rhr','sleep','steps','stress','weight'].sort());
    assert.equal(await page.locator('#analysis-export-json').evaluate(el => el.href.startsWith('blob:')), true);
    await page.fill('[name="end_date"]', '2099-01-07');
    assert.equal(await page.locator('#analysis-export-result').isVisible(), false);
    assert.equal(await page.locator('#analysis-export-json').getAttribute('href'), null);
    checks.push('One-click text download; unchanged full supported manifest, sole identity default, completed Steps, no-store, both-format atomic readiness and stale-link invalidation');

    await page.route('**/api/analysis-export/sources', route => route.fulfill({json: {sources: [
      {provider:'garmin_connect', id:'synthetic-one', label:'Synthetic Garmin 1'},
      {provider:'garmin_connect', id:'synthetic-two', label:'Synthetic Garmin 2'},
      {provider:'google_health', id:'synthetic-google-one', label:'Synthetic Google 1'},
      {provider:'google_health', id:'synthetic-google-two', label:'Synthetic Google 2'},
    ]}}));
    await page.goto(base + '/imports');
    await page.waitForFunction(() => !document.querySelector('select[name="garmin_source_id"]').disabled);
    assert.equal(await page.locator('#analysis-export-options').evaluate(el => el.open), true);
    assert.equal(await page.locator('[name="garmin_source_id"]').inputValue(), '');
    assert.equal(await page.locator('[name="google_hrv_source_id"]').inputValue(), '');
    assert.equal(await page.locator('#analysis-export-form > button').isDisabled(), true);
    checks.push('Mocked competing identities open explicit choices; no automatic pooling or arbitrary Garmin/Google identity');
    assert.deepEqual(errors, []);
    assert.deepEqual(forbidden, []);
    report.outcome = 'PASS';
  } catch (error) {
    report.outcome = 'FAIL'; report.failure = error.stack; throw error;
  } finally {
    report.browserVersion = browser.version();
    fs.writeFileSync(path.join(evidence, 'report.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
  console.log(JSON.stringify({outcome: report.outcome, checks: checks.length, screenshots: screenshots.length, evidence}));
})().catch(error => { console.error(error); process.exitCode = 1; });
