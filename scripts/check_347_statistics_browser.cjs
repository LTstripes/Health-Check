/* Offline Chromium against HTML captured from the real /statistics route and B1.
 * Export with HEALTHCHECK_STATISTICS_FIXTURES_DIR while running test_statistics_ui.py.
 * Both providers and all browser network access stay blocked. Desktop only.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const fixtures = process.env.HEALTHCHECK_STATISTICS_FIXTURES_DIR;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.ok(fixtures && evidence);
const base = 'http://127.0.0.1:8120';
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1024, 1440]) {
      for (const scenario of ['full', 'sparse', 'missing', 'ambiguous']) {
        const page = await browser.newPage({ viewport: { width, height: 1000 }, javaScriptEnabled: false });
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/*', route => {
          const url = new URL(route.request().url());
          if (url.origin !== base) {
            external.push(url.origin); return route.abort();
          }
          if (url.pathname === '/static/dashboard.css') {
            return route.fulfill({ contentType: 'text/css', body: fs.readFileSync(
              path.join(process.cwd(), 'src/healthcheck/web/static/dashboard.css'), 'utf8') });
          }
          assert.equal(url.pathname, '/statistics');
          assert.equal(route.request().method(), 'GET');
          const selected = scenario === 'ambiguous' && url.searchParams.get('garmin_source_id') &&
            url.searchParams.get('google_source_id');
          const days = url.searchParams.get('days') || 7;
          const file = selected ? `ambiguous-selected-${days}.html` : `${scenario}-${days}.html`;
          return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(path.join(fixtures, file), 'utf8') });
        });
        assert.equal((await page.goto(`${base}/statistics?days=7&end_date=2099-01-08`)).status(), 200);
        assert.equal(await page.getByRole('link', { name: 'Статистика', exact: true }).getAttribute('aria-current'), 'page');
        assert.equal(await page.locator('.statistics-metric').count(), 6);
        for (const metric of await page.locator('.statistics-metric').all()) {
          const left = metric.locator('article[data-statistics-side="left"]');
          const right = metric.locator('article[data-statistics-side="right"]');
          assert.equal(await left.getByRole('heading', { name: 'Garmin', exact: true }).count(), 1);
          assert.equal(await right.getByRole('heading', { name: 'Google', exact: true }).count(), 1);
          const l = await left.boundingBox(), r = await right.boundingBox();
          assert.ok(l.x < r.x && Math.abs(l.y - r.y) < 1 && l.width > 300 && r.width > 300);
        }
        const sleep = page.locator('[data-statistics-metric="sleep_duration_asleep_seconds"]');
        if (scenario === 'full' || scenario === 'sparse') {
          assert.match(await sleep.locator('article').nth(0).innerText(), /28800/);
          assert.match(await sleep.locator('article').nth(1).innerText(), /24600/);
        } else {
          assert.equal(await sleep.getByText('Недоступно', { exact: true }).count(), 2);
        }
        if (scenario === 'sparse') {
          assert.match(await page.locator('[data-statistics-metric="cycling_distance_meters"] .statistics-value').first().innerText(), /^0(?:\.0)? м$/);
        }
        assert.match(await page.locator('[data-statistics-metric="activity_session_count"] article').nth(1).innerText(), /Не собирается/);
        assert.equal(await page.locator('.statistics-comparison').filter({ hasText: 'Google − Garmin:' }).count(), 0);
        assert.match(await page.locator('.statistics-unavailable').innerText(), /Garmin.*Недоступно.*Google.*Не собирается/s);
        const geometry = await page.evaluate(() => ({
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
          navRows: new Set([...document.querySelector('.owner-nav').children].map(el => el.offsetTop)).size,
          background: getComputedStyle(document.body).backgroundColor,
          valueFont: getComputedStyle(document.querySelector('.statistics-value')).fontFamily,
          controls: [...document.querySelectorAll('.statistics-controls input, .statistics-controls select, .statistics-controls button')].map(el => {
            const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, height: r.height };
          }),
        }));
        assert.equal(geometry.overflow, false); assert.equal(geometry.navRows, 1);
        assert.equal(geometry.background, 'rgb(246, 242, 233)');
        assert.match(geometry.valueFont, /Georgia/);
        for (const c of geometry.controls) assert.ok(c.left >= 0 && c.right <= width + 1 && c.height >= 44);
        await page.screenshot({ path: path.join(evidence, `${scenario}-${width}.png`), fullPage: true });
        for (const details of await page.locator('.statistics-details').all()) {
          const summary = details.locator('summary');
          await summary.focus(); await page.keyboard.press('Enter');
          assert.equal(await details.getAttribute('open'), '');
          assert.equal(await summary.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
        }
        assert.match(await sleep.locator('article').nth(1).innerText(), /min → seconds · minutes_times_60_v1/);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        const period = page.getByLabel('Период', { exact: true });
        await period.focus(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Tab');
        assert.equal(await period.inputValue(), '30');
        await page.getByRole('button', { name: 'Показать', exact: true }).focus();
        await Promise.all([page.waitForURL(/days=30/), page.keyboard.press('Enter')]);
        assert.match(await page.locator('.statistics-window').innerText(), /2098-12-10 — 2099-01-08 · 30 дней/);
        if (scenario === 'ambiguous') {
          for (const provider of ['Garmin', 'Google']) {
            const selector = page.getByLabel(`${provider}: источник`, { exact: true });
            assert.equal(await selector.inputValue(), '');
            const options = await selector.locator('option').allTextContents();
            assert.equal(options.length, 3);
            await selector.focus(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Tab');
            assert.ok(await selector.inputValue());
          }
          // Explicit test fixture selects the attributed Garmin and the competing Google identity.
          const selectedHtml = fs.readFileSync(path.join(fixtures, 'ambiguous-selected-30.html'), 'utf8');
          for (const provider of ['garmin', 'google']) {
            const options = selectedHtml.split(`name="${provider}_source_id"`)[1].split('</select>')[0];
            const id = options.match(/value="([^"]+)" selected/)[1];
            await page.locator(`[name="${provider}_source_id"]`).selectOption(id);
          }
          const ids = await Promise.all(['garmin', 'google'].map(p => page.locator(`[name="${p}_source_id"]`).inputValue()));
          await page.getByRole('button', { name: 'Показать', exact: true }).focus();
          await Promise.all([page.waitForURL(url => url.searchParams.get('google_source_id') === ids[1]), page.keyboard.press('Enter')]);
          for (const [index, provider] of ['garmin', 'google'].entries()) assert.equal(await page.locator(`[name="${provider}_source_id"]`).inputValue(), ids[index]);
          await page.reload();
          assert.match(await sleep.locator('article').nth(0).innerText(), /28800/);
          assert.match(await sleep.locator('article').nth(1).innerText(), /Недоступно/);
          await sleep.locator('article').nth(1).locator('summary').focus(); await page.keyboard.press('Enter');
          assert.match(await sleep.locator('article').nth(1).innerText(), /ambiguous_google_main: 2/);
          await period.focus(); await page.keyboard.press('ArrowUp'); await page.keyboard.press('Tab');
          assert.equal(await period.inputValue(), '7');
          await page.getByRole('button', { name: 'Показать', exact: true }).focus();
          await Promise.all([page.waitForURL(url => url.searchParams.get('days') === '7' && url.searchParams.get('google_source_id') === ids[1]), page.keyboard.press('Enter')]);
          await page.reload();
          for (const [index, provider] of ['garmin', 'google'].entries()) assert.equal(await page.locator(`[name="${provider}_source_id"]`).inputValue(), ids[index]);
          assert.match(await page.locator('.statistics-window').innerText(), /2099-01-02 — 2099-01-08 · 7 дней/);
          assert.match(await sleep.locator('article').nth(0).innerText(), /28800/);
          assert.match(await sleep.locator('article').nth(1).innerText(), /Недоступно/);
        }
        checks.push({ width, scenario, geometry, keyboard: true, periods: [7, 30],
          selectedReloadBothPeriods: scenario === 'ambiguous', bothSides: true });
        await page.close();
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    const dirty = execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim();
    fs.writeFileSync(path.join(evidence, 'statistics-browser.json'), JSON.stringify({ sha, dirty, browser: browser.version(), mode: 'offline-real-route-html', checks, errors, external }, null, 2));
    console.log(JSON.stringify({ sha, dirty: Boolean(dirty), cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
