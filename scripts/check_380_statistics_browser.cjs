// Real-route synthetic HTML; no Owner runtime, provider or external request.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const fixtures = process.env.HEALTHCHECK_STATISTICS_FIXTURES_DIR;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const base = 'http://127.0.0.1:8120';
assert.ok(fixtures && evidence);
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1024, 1440]) {
      for (const scenario of ['sparse', 'zero', 'missing', 'ambiguous', 'incomplete']) {
        const page = await browser.newPage({ viewport: { width, height: 1000 }, javaScriptEnabled: false });
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/*', route => {
          const url = new URL(route.request().url());
          if (url.origin !== base) { external.push(url.origin); return route.abort(); }
          if (url.pathname === '/static/dashboard.css') return route.fulfill({ contentType: 'text/css',
            body: fs.readFileSync(path.join(process.cwd(), 'src/healthcheck/web/static/dashboard.css'), 'utf8') });
          assert.equal(url.pathname, '/statistics');
          assert.equal(route.request().method(), 'GET');
          const period = url.searchParams.get('period') || 'calendar_year';
          const selected = url.searchParams.get('garmin_source_id') && url.searchParams.get('google_source_id');
          const file = scenario === 'incomplete' ? 'annual-independent.html' :
            scenario === 'ambiguous' ? `annual-${selected ? 'selected' : 'ambiguous'}-${period}.html` :
            `annual-${scenario}-${period}.html`;
          return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(path.join(fixtures, file), 'utf8') });
        });
        const year = ['ambiguous', 'incomplete'].includes(scenario) ? 2099 : 2096;
        const end = year === 2096 ? '2096-02-29' : '2099-01-08';
        await page.goto(`${base}/statistics?period=calendar_year&calendar_year=${year}&end_date=${end}`);
        const period = page.locator('[name="period"]');
        assert.deepEqual(await period.locator('option').evaluateAll(els => els.map(el => el.value)),
          ['7', '30', 'trailing365', 'calendar_year', 'year_to_date']);
        assert.equal(await period.inputValue(), 'calendar_year');
        assert.match(await page.locator('.statistics-window').innerText(), new RegExp(`1 января ${year} — 31 декабря ${year}`));
        if (year === 2096) assert.match(await page.locator('.statistics-window').innerText(), /366 дней/);
        if (scenario !== 'incomplete') assert.equal(await page.locator('[name="end_date"]').inputValue(), end);
        const sleep = page.locator('[data-statistics-metric="sleep_duration_asleep_seconds"]');
        const left = sleep.locator('article').first();
        assert.equal((await left.locator('.statistics-value').innerText()).trim(),
          scenario === 'zero' ? '0 мин' : ['sparse', 'incomplete', 'ambiguous'].includes(scenario) ? '8 ч 0 мин' : 'Недоступно');
        assert.equal(await page.locator('.statistics-comparison').filter({ hasText: 'Google − Garmin:' }).count(), 0);
        if (scenario === 'incomplete') {
          const sourceHeader = page.locator('.statistics-source-headings header').first();
          assert.equal(await sourceHeader.locator('[data-source-attention]').isVisible(), true);
          assert.equal(await sourceHeader.locator('.statistics-source-choice').getAttribute('open'), '');
          assert.match(await sourceHeader.innerText(), /Полнота и доступность неизвестны/);
          await sourceHeader.locator('.statistics-source-choice summary').press('Enter');
          assert.equal(await sourceHeader.locator('[data-source-attention]').isVisible(), true);
          await sourceHeader.locator('.statistics-source-choice summary').press('Enter');
          const activity = page.locator('[data-statistics-metric="activity_session_count"] article').first();
          assert.match(await activity.innerText(), /Официальный итог и знаменатель недоступны/);
          await activity.locator('summary').click();
          assert.match(await activity.innerText(), /candidate_record_limit_exceeded/);
          assert.doesNotMatch(await activity.innerText(), /Допустимо:|None|Источник отсутствует/);
        }
        const geometry = await page.evaluate(() => ({
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
          controls: [...document.querySelectorAll('.statistics-controls input, .statistics-controls select, .statistics-controls button')].map(el => {
            const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, height: r.height };
          }),
        }));
        assert.equal(geometry.overflow, false);
        for (const c of geometry.controls) assert.ok(c.left >= 0 && c.right <= width + 1 && c.height >= 44);
        const l = await left.boundingBox(), r = await sleep.locator('article').nth(1).boundingBox();
        assert.ok(l.x < r.x && Math.abs(l.y - r.y) < 1);
        await page.screenshot({ path: path.join(evidence, `annual-${scenario}-${width}.png`), fullPage: true });
        if (scenario !== 'incomplete') {
          if (scenario === 'ambiguous') {
            const selectedHtml = fs.readFileSync(path.join(fixtures, 'annual-selected-calendar_year.html'), 'utf8');
            for (const provider of ['garmin', 'google']) {
              const options = selectedHtml.split(`name="${provider}_source_id"`)[1].split('</select>')[0];
              await page.locator(`[name="${provider}_source_id"]`).selectOption(options.match(/value="([^"]+)" selected/)[1]);
            }
          }
          const ids = await Promise.all(['garmin', 'google'].map(p => page.locator(`[name="${p}_source_id"]`).inputValue()));
          const sequence = scenario === 'ambiguous' ? ['trailing365', 'year_to_date', 'calendar_year'] :
            ['7', '30', 'trailing365', 'year_to_date', 'calendar_year'];
          for (const choice of [...sequence, ...sequence]) {
            await period.selectOption(choice);
            await Promise.all([page.waitForURL(url => url.searchParams.get('period') === choice),
              page.getByRole('button', { name: 'Показать', exact: true }).click()]);
            assert.equal(await period.inputValue(), choice);
            assert.equal(await page.locator('[name="calendar_year"]').inputValue(), String(year));
            assert.equal(await page.locator('[name="end_date"]').inputValue(), end);
            for (const [i, p] of ['garmin', 'google'].entries()) {
              assert.equal(await page.locator(`[name="${p}_source_id"]`).inputValue(), ids[i]);
              assert.equal(new URL(page.url()).searchParams.get(`${p}_source_id`), ids[i]);
            }
            await page.reload();
            assert.equal(await period.inputValue(), choice);
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
          }
          await page.goBack();
          assert.equal(await period.inputValue(), 'year_to_date');
          await page.goForward();
          assert.equal(await period.inputValue(), 'calendar_year');
          for (const [i, p] of ['garmin', 'google'].entries())
            assert.equal(await page.locator(`[name="${p}_source_id"]`).inputValue(), ids[i]);
        }
        checks.push({ width, scenario, geometry, repeatedNavigation: scenario !== 'incomplete', backForward: scenario !== 'incomplete' });
        await page.close();
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    const dirty = execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim();
    fs.writeFileSync(path.join(evidence, 'annual-statistics-browser.json'), JSON.stringify({
      sha, dirty, browser: browser.version(), mode: 'offline-real-route-html', checks, errors, external,
    }, null, 2));
    console.log(JSON.stringify({ sha, dirty: Boolean(dirty), cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
