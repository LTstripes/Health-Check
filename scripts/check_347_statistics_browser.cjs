/* Offline Chromium against HTML captured from the real /statistics route and B1.
 * Export with HEALTHCHECK_STATISTICS_FIXTURES_DIR while running test_statistics_ui.py.
 * Failure captures (unavailable store, read error) assert the accepted Russian
 * alert documents, never the raw JSON 500. Both providers and all browser network
 * access stay blocked. Desktop only.
 */
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
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1024, 1440]) {
      for (const scenario of ['full', 'sparse', 'missing', 'ambiguous', 'fractional', 'zero']) {
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
          const days = url.searchParams.get('period') || url.searchParams.get('days') || 7;
          const file = selected ? `ambiguous-selected-${days}.html` : `${scenario}-${days}.html`;
          return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(path.join(fixtures, file), 'utf8') });
        });
        assert.equal((await page.goto(`${base}/statistics?days=7&end_date=2099-01-08`)).status(), 200);
        assert.equal(await page.getByRole('link', { name: 'Статистика', exact: true }).getAttribute('aria-current'), 'page');
        assert.equal(await page.locator('.statistics-metric').count(), 6);
        assert.equal(await page.locator('.statistics-controls [name$="_source_id"]').count(), 0);
        assert.equal(await page.locator('.statistics-source-choice').count(), 2);
        assert.equal(await page.locator('.statistics-source-choice[open]').count(), scenario === 'ambiguous' ? 2 : 0);
        assert.equal(await page.locator('[data-source-attention]').count(), scenario === 'ambiguous' ? 2 : 0);
        const formData = await page.locator('#statistics-controls').evaluate(form =>
          [...new FormData(form).keys()]);
        assert.ok(formData.includes('garmin_source_id') && formData.includes('google_source_id'));
        if (scenario === 'ambiguous') {
          const detail = page.locator('.statistics-source-choice').first();
          await detail.locator('summary').press('Enter');
          assert.equal(await detail.getAttribute('open'), null);
          assert.equal(await page.locator('[data-source-attention]').first().isVisible(), true);
          await detail.locator('summary').press('Enter');
        }
        for (const metric of await page.locator('.statistics-metric').all()) {
          const left = metric.locator('article[data-statistics-side="left"]');
          const right = metric.locator('article[data-statistics-side="right"]');
          assert.equal(await left.getByRole('heading', { name: 'Garmin', exact: true }).count(), 1);
          assert.equal(await right.getByRole('heading', { name: 'Google', exact: true }).count(), 1);
          const l = await left.boundingBox(), r = await right.boundingBox();
          assert.ok(l.x < r.x && Math.abs(l.y - r.y) < 1 && l.width > 300 && r.width > 300);
        }
        const sleep = page.locator('[data-statistics-metric="sleep_duration_asleep_seconds"]');
        const headline = code => page.locator(`[data-statistics-metric="${code}"] .statistics-value`).first();
        if (scenario === 'full' || scenario === 'sparse') {
          assert.equal((await sleep.locator('.statistics-value').nth(0).innerText()).trim(), '8 ч 0 мин');
          assert.equal((await sleep.locator('.statistics-value').nth(1).innerText()).trim(), '6 ч 50 мин');
        } else if (scenario === 'fractional') {
          assert.equal((await headline('sleep_duration_asleep_seconds').innerText()).trim(), '8 ч 0 мин 30,5 с');
          // B1 rejects fractional Google minutes; formatting must preserve that exclusion.
          assert.equal((await sleep.locator('.statistics-value').nth(1).innerText()).trim(), 'Недоступно');
          assert.equal((await headline('cycling_distance_meters').innerText()).trim(), '12,35 км');
          assert.equal((await headline('tennis_duration_seconds').innerText()).trim(), '1 ч 1 мин 1,25 с');
        } else if (scenario === 'zero') {
          assert.equal((await headline('sleep_duration_asleep_seconds').innerText()).trim(), '0 мин');
          assert.equal((await headline('tennis_duration_seconds').innerText()).trim(), '0 мин');
        } else {
          assert.equal(await sleep.getByText('Недоступно', { exact: true }).count(), 2);
        }
        if (scenario === 'sparse') {
          assert.equal((await headline('cycling_distance_meters').innerText()).trim(), '0 км');
        }
        if (!['missing', 'ambiguous'].includes(scenario)) {
          assert.equal((await headline('activity_session_count').innerText()).trim(), '2 сессий');
          assert.equal((await headline('tennis_session_count').innerText()).trim(), '1 сессий');
          assert.match(await headline('activity_type_counts').innerText(), /cycling: 1 сессий/);
          assert.doesNotMatch(await headline('activity_type_counts').innerText(), /\.0/);
          if (scenario !== 'fractional' && scenario !== 'sparse') {
            assert.equal((await headline('cycling_distance_meters').innerText()).trim(), '21 км');
          }
          if (scenario === 'full' || scenario === 'sparse') {
            assert.equal((await headline('tennis_duration_seconds').innerText()).trim(), '1 ч 0 мин');
          }
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
          if (await details.getAttribute('open') !== null) await summary.press('Enter');
          await summary.focus(); await page.keyboard.press('Enter');
          assert.equal(await details.getAttribute('open'), '');
          assert.equal(await summary.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
        }
        assert.match(await sleep.locator('article').nth(1).innerText(), /min → seconds · minutes_times_60_v1/);
        if (!['missing', 'ambiguous'].includes(scenario)) {
          const rawSleep = scenario === 'fractional' ? '28830.5' : scenario === 'zero' ? '0.0' : '28800.0';
          const rawNumerator = scenario === 'full' ? '201600.0' : rawSleep;
          assert.ok((await sleep.locator('details').first().innerText()).includes(`${rawSleep} / ${rawNumerator} · seconds`));
          const distanceDetails = page.locator('[data-statistics-metric="cycling_distance_meters"] details').first();
          assert.match(await distanceDetails.innerText(), /meters → meters · identity_v1/);
          if (scenario === 'fractional') assert.match(await distanceDetails.innerText(), /12345\.6 \/ 12345\.6 · meters/);
          if (scenario === 'fractional') assert.match(await sleep.locator('details').nth(1).innerText(), /metric_invalid: 1/);
        }
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        const period = page.getByLabel('Период', { exact: true });
        await period.focus(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Tab');
        assert.equal(await period.inputValue(), '30');
        await page.getByRole('button', { name: 'Показать', exact: true }).focus();
        await Promise.all([page.waitForURL(/period=30/), page.keyboard.press('Enter')]);
        assert.match(await page.locator('.statistics-window').innerText(), /10 декабря 2098 — 8 января 2099 · 30 дней/);
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
          await page.getByRole('button', { name: 'Применить источники', exact: true }).first().focus();
          await Promise.all([page.waitForURL(url => url.searchParams.get('google_source_id') === ids[1]), page.keyboard.press('Enter')]);
          for (const [index, provider] of ['garmin', 'google'].entries()) assert.equal(await page.locator(`[name="${provider}_source_id"]`).inputValue(), ids[index]);
          await page.reload();
          assert.equal((await headline('sleep_duration_asleep_seconds').innerText()).trim(), '8 ч 0 мин');
          assert.match(await sleep.locator('article').nth(1).innerText(), /Недоступно/);
          await sleep.locator('article').nth(1).locator('summary').focus(); await page.keyboard.press('Enter');
          assert.match(await sleep.locator('article').nth(1).innerText(), /ambiguous_google_main: 2/);
          await period.focus(); await page.keyboard.press('ArrowUp'); await page.keyboard.press('Tab');
          assert.equal(await period.inputValue(), '7');
          await page.getByRole('button', { name: 'Показать', exact: true }).focus();
          await Promise.all([page.waitForURL(url => url.searchParams.get('period') === '7' && url.searchParams.get('google_source_id') === ids[1]), page.keyboard.press('Enter')]);
          await page.reload();
          for (const [index, provider] of ['garmin', 'google'].entries()) assert.equal(await page.locator(`[name="${provider}_source_id"]`).inputValue(), ids[index]);
          assert.match(await page.locator('.statistics-window').innerText(), /2 января 2099 — 8 января 2099 · 7 дней/);
          assert.equal((await headline('sleep_duration_asleep_seconds').innerText()).trim(), '8 ч 0 мин');
          assert.match(await sleep.locator('article').nth(1).innerText(), /Недоступно/);
        }
        checks.push({ width, scenario, geometry, keyboard: true, periods: [7, 30],
          selectedReloadBothPeriods: scenario === 'ambiguous', bothSides: true });
        await page.close();
      }
    }
    for (const width of [1024, 1440]) {
      for (const days of [7, 30]) {
        for (const scenario of ['sole', 'explicit_missing', 'eligible', 'conflict', 'empty', 'other_family', 'outside', 'zero']) {
          const page = await browser.newPage({ viewport: { width, height: 1000 }, javaScriptEnabled: false });
          await page.route('**/*', route => {
            const url = new URL(route.request().url());
            if (url.origin !== base) { external.push(url.origin); return route.abort(); }
            if (url.pathname === '/static/dashboard.css') return route.fulfill({ contentType: 'text/css',
              body: fs.readFileSync(path.join(process.cwd(), 'src/healthcheck/web/static/dashboard.css'), 'utf8') });
            return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(
              path.join(fixtures, `source-${scenario}-${days}.html`), 'utf8') });
          });
          await page.goto(`${base}/statistics`);
          const selector = page.locator('[name="google_source_id"]');
          const selected = await selector.inputValue();
          assert.equal(Boolean(selected), ['sole', 'explicit_missing', 'zero'].includes(scenario));
          const options = await selector.locator('option').allTextContents();
          assert.equal(new Set(options).size, options.length);
          for (const provider of ['garmin', 'google']) {
            const detail = page.locator('.statistics-source-headings details').nth(provider === 'garmin' ? 0 : 1);
            if (await detail.getAttribute('open') !== null) await detail.locator('summary').press('Enter');
            const ids = await page.locator(`[name="${provider}_source_id"] option`).evaluateAll(
              elements => elements.map(el => el.value).filter(Boolean));
            const primary = await page.locator('main').innerText();
            for (const id of ids) assert.ok(!primary.includes(id), 'UUID leaked outside collapsed details');
            await detail.locator('summary').focus(); await page.keyboard.press('Enter');
            const text = await detail.innerText();
            for (const id of ids) assert.ok(text.includes(id), 'Exact identity absent from disclosure');
            await detail.locator('summary').press('Enter');
          }
          const sleep = page.locator('[data-statistics-metric="sleep_duration_asleep_seconds"]');
          const value = (await sleep.locator('.statistics-value').nth(1).innerText()).trim();
          assert.equal(value, scenario === 'sole' ? '6 ч 50 мин' : scenario === 'zero' ? '0 мин' : 'Недоступно');
          const left = await sleep.locator('article').nth(0).boundingBox();
          const right = await sleep.locator('article').nth(1).boundingBox();
          assert.ok(left.x < right.x && Math.abs(left.y - right.y) < 1);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
          if (days === 7) await page.screenshot({ path: path.join(evidence, `source-${scenario}-${width}.png`), fullPage: true });
          checks.push({ width, days, sourceScenario: scenario, exactIdentityDisclosure: true, bothSides: true });
          await page.close();
        }
      }
    }
    // #347 read-failure parity: the real route's error documents must render as
    // the accepted Russian alert (role=alert, Статистика shell section), never
    // the raw JSON 500. HTML captured by test_statistics_ui.py.
    for (const width of [1024, 1440]) {
      for (const [file, status, message] of [
        ['unavailable-503.html', 503, 'Локальное хранилище данных не готово.'],
        ['read-error-500.html', 500, 'Не удалось выполнить запрос. Попробуй повторить его.'],
      ]) {
        const failure = await browser.newPage({ viewport: { width, height: 1000 }, javaScriptEnabled: false });
        failure.on('pageerror', error => errors.push(error.message));
        await failure.route('**/*', route => {
          const url = new URL(route.request().url());
          if (url.origin !== base) { external.push(url.origin); return route.abort(); }
          if (url.pathname === '/static/dashboard.css') {
            return route.fulfill({ contentType: 'text/css', body: fs.readFileSync(
              path.join(process.cwd(), 'src/healthcheck/web/static/dashboard.css'), 'utf8') });
          }
          assert.equal(url.pathname, '/statistics');
          return route.fulfill({ status, contentType: 'text/html; charset=utf-8',
            body: fs.readFileSync(path.join(fixtures, file), 'utf8') });
        });
        assert.equal((await failure.goto(`${base}/statistics?days=7&end_date=2099-01-08`)).status(), status);
        assert.equal(await failure.getByRole('link', { name: 'Статистика', exact: true }).getAttribute('aria-current'), 'page');
        const alert = failure.getByRole('alert');
        assert.equal(await alert.isVisible(), true);
        const alertText = (await alert.innerText()).replace(/\s+/g, ' ');
        assert.match(alertText, /Не удалось/);
        assert.ok(alertText.includes(message), `${file}: owner message ${message}`);
        assert.doesNotMatch(await failure.locator('main').innerText(), /request failed|synthetic Stage-7|no such table|OperationalError/);
        assert.equal(await failure.locator('details[open]').count(), 0);
        const geometry = await failure.evaluate(() => ({
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
          navRows: new Set([...document.querySelector('.owner-nav').children].map(el => el.offsetTop)).size,
          background: getComputedStyle(document.body).backgroundColor,
          heading: document.querySelector('.owner-page-header h1').innerText,
        }));
        assert.equal(geometry.overflow, false, `${file}: overflow`);
        assert.equal(geometry.navRows, 1, `${file}: nav rows`);
        assert.equal(geometry.background, 'rgb(246, 242, 233)', `${file}: background`);
        assert.equal(geometry.heading, 'Статистика', `${file}: heading`);
        await failure.screenshot({ path: path.join(evidence, `failure-${status}-${width}.png`), fullPage: true });
        checks.push({ width, failure: file, status, ownerMessage: message });
        await failure.close();
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    const dirty = execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim();
    const pngs = fs.readdirSync(evidence).filter(file => file.endsWith('.png')).map(file => ({
      file, sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(evidence, file))).digest('hex'),
    }));
    fs.writeFileSync(path.join(evidence, 'statistics-browser.json'), JSON.stringify({ sha, dirty, browser: browser.version(), mode: 'offline-real-route-html', checks, errors, external, pngs }, null, 2));
    console.log(JSON.stringify({ sha, dirty: Boolean(dirty), cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
