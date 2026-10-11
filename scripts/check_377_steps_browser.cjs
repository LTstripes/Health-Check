// Offline Chromium over real Statistics route captures; all external requests blocked.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const fixtures = process.env.HEALTHCHECK_STATISTICS_FIXTURES_DIR;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.ok(fixtures && evidence);
const base = 'http://127.0.0.1:8120';
const sources = JSON.parse(fs.readFileSync(path.join(fixtures, 'steps-sources.json'), 'utf8'));
const expected = { '2099-01-02': ['value', '17'], '2099-01-03': ['value', '0'],
  '2099-01-04': ['null', 'Недоступно'], '2099-01-05': ['missing', 'Недоступно'],
  '2099-01-06': ['invalid', 'Недоступно'], '2099-01-07': ['ambiguous', 'Недоступно'],
  '2099-01-08': ['unavailable', 'Недоступно'],
  '2099-01-09': ['projection_unavailable', 'Недоступно'],
  '2099-01-10': ['value', '9007199254740993'] };
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], external = [];
  fs.mkdirSync(evidence, { recursive: true });
  async function pageFor(width, fixedFile) {
    const page = await browser.newPage({ viewport: { width, height: 1000 }, javaScriptEnabled: false });
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) { external.push(url.origin); return route.abort(); }
      if (url.pathname === '/static/dashboard.css') return route.fulfill({ contentType: 'text/css',
        body: fs.readFileSync(path.join(process.cwd(), 'src/healthcheck/web/static/dashboard.css'), 'utf8') });
      assert.equal(url.pathname, '/statistics'); assert.equal(route.request().method(), 'GET');
      const period = url.searchParams.get('period') || '7';
      const id = url.searchParams.get('garmin_source_id');
      const selection = !id ? 'unselected' : id === sources.a ? 'a' : id === sources.b ? 'b' : null;
      assert.ok(fixedFile || selection, 'unknown exact source in navigation');
      const file = fixedFile || (url.searchParams.get('end_date') === '2099-02-08'
        ? 'steps-no-latest.html' : `steps-${selection}-${period}.html`);
      return route.fulfill({ contentType: 'text/html; charset=utf-8',
        body: fs.readFileSync(path.join(fixtures, file), 'utf8') });
    });
    return page;
  }
  async function geometry(page, width) {
    const result = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > innerWidth + 1,
      navRows: new Set([...document.querySelector('.owner-nav').children].map(el => el.offsetTop)).size,
      controls: [...document.querySelectorAll('.statistics-controls input, .statistics-controls select, .statistics-controls button')].map(el => {
        const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, height: r.height };
      }),
    }));
    assert.equal(result.overflow, false); assert.equal(result.navRows, 1);
    for (const c of result.controls) assert.ok(c.left >= 0 && c.right <= width + 1 && c.height >= 44);
    assert.equal(await page.locator('.statistics-metric').count(), 6);
    for (const metric of await page.locator('.statistics-metric').all()) {
      const left = await metric.locator('article').nth(0).boundingBox();
      const right = await metric.locator('article').nth(1).boundingBox();
      assert.ok(left.x < right.x && Math.abs(left.y - right.y) < 1);
    }
    return result;
  }
  async function submit(page, predicate) {
    await page.getByRole('button', { name: 'Показать', exact: true }).focus();
    await Promise.all([page.waitForURL(predicate), page.keyboard.press('Enter')]);
  }
  try {
    for (const width of [1024, 1440]) {
      const page = await pageFor(width);
      await page.goto(`${base}/statistics?period=30&end_date=2099-01-10&calendar_year=2099`);
      const section = page.locator('[data-statistics-steps]');
      const selector = page.locator('[name="garmin_source_id"]');
      assert.equal(await selector.inputValue(), '');
      assert.equal(await section.locator('[data-steps-selection="required"]').count(), 1);
      assert.equal(await section.locator('tbody tr').count(), 0);
      await selector.selectOption(sources.a);
      await submit(page, url => url.searchParams.get('garmin_source_id') === sources.a);
      assert.equal(await section.locator('tbody tr').count(), 30);
      for (const [day, [state, value]] of Object.entries(expected)) {
        const row = section.locator(`[data-steps-date="${day}"]`);
        assert.equal(await row.getAttribute('data-steps-state'), state);
        assert.equal((await row.locator('.statistics-steps-value').innerText()).trim(), value);
      }
      assert.match(await section.innerText(), /неизвестны/);
      assert.doesNotMatch(await section.innerText(), /999|среднее|сумма|итого/i);
      const detail = section.locator('[data-steps-date="2099-01-07"] details');
      await detail.locator('summary').focus(); await page.keyboard.press('Enter');
      assert.equal(await detail.getAttribute('open'), '');
      assert.match(await detail.innerText(), /ambiguous.*divergent_saved_observations/s);
      assert.match(await detail.innerText(), /garmin-observed-daily-steps-v1/);
      assert.match(await detail.innerText(), new RegExp(sources.a));
      const geometryResult = await geometry(page, width);
      assert.equal(await detail.evaluate(el => getComputedStyle(el.parentElement).textAlign), 'left');
      await detail.locator('summary').focus(); await page.keyboard.press('Enter');
      await section.locator('[data-steps-date="2099-01-02"]').scrollIntoViewIfNeeded();
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(evidence, `steps-selected-${width}.png`), fullPage: true });
      await section.screenshot({ path: path.join(evidence, `steps-panel-${width}.png`) });
      await selector.selectOption(sources.b);
      await submit(page, url => url.searchParams.get('garmin_source_id') === sources.b);
      assert.equal((await section.locator('[data-steps-date="2099-01-10"] .statistics-steps-value').innerText()).trim(), '999');
      assert.equal(await section.locator('[data-steps-date="2099-01-03"]').getAttribute('data-steps-state'), 'projection_unavailable');
      await selector.selectOption('');
      await submit(page, url => !url.searchParams.get('garmin_source_id'));
      assert.equal(await section.locator('tbody tr').count(), 0);
      await selector.selectOption(sources.a);
      await submit(page, url => url.searchParams.get('garmin_source_id') === sources.a);
      const counts = { '7': 7, '30': 30, calendar_year: 365, trailing365: 365, year_to_date: 10 };
      for (const period of ['7', '30', 'calendar_year', 'trailing365', 'year_to_date', '7', '30']) {
        await page.locator('[name="period"]').selectOption(period);
        await submit(page, url => url.searchParams.get('period') === period);
        await page.reload();
        assert.equal(await selector.inputValue(), sources.a);
        assert.equal(await section.locator('tbody tr').count(), counts[period]);
        assert.equal((await section.locator('[data-steps-date="2099-01-10"] .statistics-steps-value').innerText()).trim(), '9007199254740993');
        await geometry(page, width);
      }
      const table = section.locator('.statistics-steps-table');
      await table.focus(); await page.keyboard.press('End');
      assert.ok(await table.evaluate(el => el.scrollHeight > el.clientHeight));
      await page.goto(`${base}/statistics?period=7&end_date=2099-02-08&calendar_year=2099&garmin_source_id=${sources.a}`);
      assert.equal(await section.locator('tr[data-steps-state="projection_unavailable"]').count(), 7);
      assert.equal(await section.locator('.statistics-steps-value').filter({ hasText: 'Недоступно' }).count(), 7);
      checks.push({ width, scenario: 'navigation', geometry: geometryResult, states: Object.keys(expected),
        explicitSelection: true, sourceSeparation: true, periods: Object.keys(counts), repeatedReload: true, noLatest: true });
      await page.close();
      for (const scenario of ['sole', 'empty', 'cap-candidate', 'cap-provenance']) {
        const fixture = await pageFor(width, `steps-${scenario}.html`);
        await fixture.goto(`${base}/statistics`);
        const steps = fixture.locator('[data-statistics-steps]');
        if (scenario.startsWith('cap')) {
          assert.equal((await steps.locator('[data-steps-date="2099-01-02"] .statistics-steps-value').innerText()).trim(), '0');
          const row = steps.locator('[data-steps-date="2099-01-03"]');
          assert.equal(await row.getAttribute('data-steps-state'), 'search_incomplete');
          assert.equal((await row.locator('.statistics-steps-value').innerText()).trim(), 'Недоступно');
          assert.equal(await steps.locator('[role="status"]').isVisible(), true);
          await row.locator('summary').focus(); await fixture.keyboard.press('Enter');
          assert.match(await row.innerText(), /limit_exceeded/);
          await geometry(fixture, width);
          await fixture.screenshot({ path: path.join(evidence, `steps-${scenario}-${width}.png`), fullPage: true });
        } else {
          assert.equal(await fixture.locator('[name="garmin_source_id"]').inputValue(), '');
          assert.equal(await steps.locator('tbody tr').count(), 0);
        }
        checks.push({ width, scenario }); await fixture.close();
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    const dirty = execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim();
    fs.writeFileSync(path.join(evidence, 'steps-browser.json'), JSON.stringify({ sha, dirty,
      browser: browser.version(), mode: 'offline-real-route-html', checks, errors, external }, null, 2));
    console.log(JSON.stringify({ sha, dirty: Boolean(dirty), cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
