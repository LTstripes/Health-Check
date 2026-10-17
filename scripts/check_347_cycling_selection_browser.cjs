// Offline production-route synthetic HTML, native forms and exact-source links.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fixtures = process.env.HEALTHCHECK_STATISTICS_FIXTURES_DIR;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const base = 'http://127.0.0.1:8120';
const periods = ['7', '30', 'trailing365', 'calendar_year', 'year_to_date'];
assert.ok(fixtures && evidence);
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1024, 1440]) {
      for (const scenario of ['unique', 'zero', 'multiple', 'conflict', 'missing', 'empty', 'capped', 'window',
        'summary-deadline-unique', 'summary-deadline-multiple']) {
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
          const explicit = url.searchParams.get('garmin_source_id');
          const file = scenario.startsWith('summary-deadline-') ? scenario : scenario === 'unique' || scenario === 'zero' ?
            `unique-${period}-${scenario === 'zero' ? 'zero' : 'value'}` :
            scenario === 'window' ? `window-${explicit ? 'explicit-' : ''}${period}` : `${scenario}-7`;
          return route.fulfill({ contentType: 'text/html; charset=utf-8',
            body: fs.readFileSync(path.join(fixtures, `cycling-${file}.html`), 'utf8') });
        });
        await page.goto(`${base}/statistics?period=7&calendar_year=2099&end_date=${scenario === 'window' ? '2099-02-08' : '2099-01-08'}`);
        const metric = page.locator('[data-statistics-metric="cycling_distance_meters"]');
        const left = metric.locator('article').first(), right = metric.locator('article').nth(1);
        assert.equal(await left.getByRole('heading', { name: 'Garmin', exact: true }).count(), 1);
        assert.equal(await right.getByRole('heading', { name: 'Google', exact: true }).count(), 1);
        assert.match(await right.innerText(), /Не собирается/);
        const value = (await left.locator('.statistics-value').innerText()).trim();
        assert.equal(value, scenario === 'unique' ? '12,35 км' : scenario === 'zero' ? '0 км' :
          scenario === 'summary-deadline-unique' ? '21 км' : scenario === 'window' ? '11 км' : 'Недоступно');
        assert.equal(await page.locator('[name="garmin_source_id"]').inputValue(), '');
        assert.equal(await metric.locator('[data-cycling-source-attention]').count(),
          ['multiple', 'conflict', 'capped', 'summary-deadline-multiple'].includes(scenario) ? 1 : 0);
        if (scenario.startsWith('summary-deadline-')) {
          const options = page.locator('[name="garmin_source_id"] option[value]:not([value=""])');
          assert.equal(await options.count(), scenario.endsWith('multiple') ? 2 : 1);
          assert.ok((await options.allTextContents()).every(label => label.trim().startsWith('Garmin')));
          if (scenario.endsWith('unique')) assert.match(await left.locator('[data-cycling-source]').innerText(), /Garmin · Vivoactive 5/);
        }
        const l = await left.boundingBox(), r = await right.boundingBox();
        assert.ok(l.x < r.x && Math.abs(l.y - r.y) < 1 && l.width > 300 && r.width > 300);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        await metric.scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(evidence, `cycling-${scenario}-${width}.png`), fullPage: true });
        await metric.screenshot({ path: path.join(evidence, `cycling-${scenario}-${width}-card.png`) });
        if (['unique', 'zero', 'window'].includes(scenario)) {
          for (const period of periods) {
            await page.locator('[name="period"]').selectOption(period);
            await page.getByRole('button', { name: 'Показать', exact: true }).focus();
            await Promise.all([page.waitForURL(url => url.searchParams.get('period') === period &&
              url.searchParams.has('garmin_source_id')), page.keyboard.press('Enter')]);
            assert.equal(await page.locator('[name="garmin_source_id"]').inputValue(), '');
            assert.equal((await left.locator('.statistics-value').innerText()).trim(),
              scenario === 'window' && period !== '7' ? 'Недоступно' : value);
          }
          if (scenario === 'window') {
            const selected = fs.readFileSync(path.join(fixtures, 'cycling-window-explicit-7.html'), 'utf8')
              .split('name="garmin_source_id"')[1].split('</select>')[0].match(/value="([^"]+)" selected/)[1];
            await page.locator('[name="garmin_source_id"]').selectOption(selected);
            await page.getByRole('button', { name: 'Применить источники', exact: true }).first().focus();
            await Promise.all([page.waitForURL(url => url.searchParams.get('garmin_source_id') === selected),
              page.keyboard.press('Enter')]);
            for (const period of periods) {
              await page.locator('[name="period"]').selectOption(period);
              await page.getByRole('button', { name: 'Показать', exact: true }).click();
              await page.waitForURL(url => url.searchParams.get('period') === period);
              assert.equal(await page.locator('[name="garmin_source_id"]').inputValue(), selected);
              assert.equal((await left.locator('.statistics-value').innerText()).trim(), '11 км');
              await page.reload();
              assert.equal(await page.locator('[name="garmin_source_id"]').inputValue(), selected);
            }
            await page.goBack();
            assert.equal(await page.locator('[name="garmin_source_id"]').inputValue(), selected);
          }
        }
        checks.push({ width, scenario, paired: true, form: true });
        await page.close();
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    const dirty = execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim();
    const pngs = fs.readdirSync(evidence).filter(f => f.endsWith('.png')).map(file => ({ file,
      sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(evidence, file))).digest('hex') }));
    fs.writeFileSync(path.join(evidence, 'cycling-browser.json'), JSON.stringify({
      sha, dirty, browser: browser.version(), mode: 'offline-production-route-html', checks, errors, external, pngs,
    }, null, 2));
    console.log(JSON.stringify({ sha, dirty: Boolean(dirty), checks: checks.length, pngs: pngs.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
