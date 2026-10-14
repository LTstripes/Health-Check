// Offline real-route synthetic HTML: exact Sleep identity and native form state.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fixtures = process.env.HEALTHCHECK_STATISTICS_FIXTURES_DIR;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.ok(fixtures && evidence);
const base = 'http://127.0.0.1:8120';
const periods = ['7', '30', 'trailing365', 'calendar_year', 'year_to_date'];
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1024, 1440]) {
      for (const scenario of ['five', 'window']) {
        const page = await browser.newPage({ viewport: { width, height: 1000 }, javaScriptEnabled: false });
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/*', route => {
          const url = new URL(route.request().url());
          if (url.origin !== base) { external.push(url.origin); return route.abort(); }
          if (url.pathname === '/static/dashboard.css') return route.fulfill({ contentType: 'text/css',
            body: fs.readFileSync(path.join(process.cwd(), 'src/healthcheck/web/static/dashboard.css'), 'utf8') });
          assert.equal(url.pathname, '/statistics');
          assert.equal(route.request().method(), 'GET');
          const period = url.searchParams.get('period') || '7';
          const explicit = url.searchParams.get('google_sleep_source_id');
          const file = explicit ? `sleep-explicit-${period}.html` : `sleep-${scenario}-${period}.html`;
          return route.fulfill({ contentType: 'text/html; charset=utf-8',
            body: fs.readFileSync(path.join(fixtures, file), 'utf8') });
        });
        const end = scenario === 'five' ? '2099-01-08' : '2099-02-08';
        await page.goto(`${base}/statistics?period=7&end_date=${end}&calendar_year=2099`);
        const sleep = page.locator('[data-statistics-metric="sleep_duration_asleep_seconds"]');
        const right = sleep.locator('article').nth(1);
        for (const period of periods) {
          await page.locator('[name="period"]').selectOption(period);
          await page.getByRole('button', { name: 'Показать', exact: true }).focus();
          await Promise.all([page.waitForURL(url => url.searchParams.get('period') === period &&
            url.searchParams.has('google_sleep_source_id')),
            page.keyboard.press('Enter')]);
          for (const field of ['garmin_source_id', 'google_source_id', 'garmin_sleep_source_id', 'google_sleep_source_id']) {
            assert.equal(await page.locator(`[name="${field}"]`).inputValue(), '');
            assert.equal(new URL(page.url()).searchParams.get(field), '');
          }
          assert.equal(await right.getByRole('heading', { name: 'Google', exact: true }).count(), 1);
          assert.equal(await sleep.locator('article').first().getByRole('heading', { name: 'Garmin', exact: true }).count(), 1);
          const value = (await right.locator('.statistics-value').innerText()).trim();
          assert.equal(value, scenario === 'five' ? '6 ч 50 мин' : period === '7' ? '1 ч 0 мин' : 'Недоступно');
          assert.equal(await right.locator('[data-sleep-source-attention]').count(),
            scenario === 'window' && period !== '7' ? 1 : 0);
          // Primary Sleep results retain identity labels without exposing UUIDs.
          const detail = right.locator('details');
          assert.equal(await detail.getAttribute('open'), null);
          const identities = await right.locator('option').evaluateAll(els => els.map(el => el.value).filter(Boolean));
          const primary = await right.innerText();
          for (const id of identities) assert.ok(!primary.includes(id));
          const l = await sleep.locator('article').first().boundingBox(), r = await right.boundingBox();
          assert.ok(l.x < r.x && Math.abs(l.y - r.y) < 1 && l.width > 300 && r.width > 300);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
          if (period === '7' || period === '30') await page.screenshot({
            path: path.join(evidence, `sleep-${scenario}-${period}-${width}.png`), fullPage: true });
          checks.push({ width, scenario, period, autoFormBlank: true, bothProviders: true });
        }
        if (scenario === 'window') {
          const detail = right.locator('details');
          await detail.locator('summary').focus(); await page.keyboard.press('Enter');
          assert.equal(await detail.getAttribute('open'), '');
          assert.equal(await right.locator('[data-sleep-source-attention]').isVisible(), true);
          const html = fs.readFileSync(path.join(fixtures, 'sleep-explicit-year_to_date.html'), 'utf8');
          const id = html.split('name="google_sleep_source_id"')[1].split('</select>')[0]
            .match(/value="([^"]+)" selected/)[1];
          await right.locator('[name="google_sleep_source_id"]').selectOption(id);
          await right.getByRole('button', { name: 'Применить источник сна', exact: true }).focus();
          await Promise.all([page.waitForURL(url => url.searchParams.get('google_sleep_source_id') === id),
            page.keyboard.press('Enter')]);
          for (const period of periods) {
            await page.locator('[name="period"]').selectOption(period);
            await page.getByRole('button', { name: 'Показать', exact: true }).click();
            await page.waitForURL(url => url.searchParams.get('period') === period);
            assert.equal(await page.locator('[name="google_source_id"]').inputValue(), '');
            assert.equal(await page.locator('[name="google_sleep_source_id"]').inputValue(), id);
            assert.equal((await right.locator('.statistics-value').innerText()).trim(), '1 ч 0 мин');
            await page.reload();
            assert.equal(await page.locator('[name="google_sleep_source_id"]').inputValue(), id);
          }
          await page.goBack();
          assert.equal(await page.locator('[name="google_sleep_source_id"]').inputValue(), id);
          checks.push({ width, explicitKeyboard: true, allPeriodsRetained: true, reloadAndBack: true });
        }
        await page.close();
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    const dirty = execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim();
    const pngs = fs.readdirSync(evidence).filter(f => f.endsWith('.png')).map(file => ({
      file, sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(evidence, file))).digest('hex'),
    }));
    fs.writeFileSync(path.join(evidence, 'sleep-selection-browser.json'), JSON.stringify({
      sha, dirty, browser: browser.version(), mode: 'offline-real-route-html', checks, errors, external, pngs,
    }, null, 2));
    console.log(JSON.stringify({ sha, dirty: Boolean(dirty), checks: checks.length, pngs: pngs.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
