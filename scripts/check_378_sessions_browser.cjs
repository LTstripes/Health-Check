/* Synthetic loopback #378 desktop/keyboard/history check; evidence outside Git. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HEALTHCHECK_BASE_URL || 'http://127.0.0.1:8138';
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const identity = JSON.parse(fs.readFileSync(process.env.HEALTHCHECK_BROWSER_IDENTITY, 'utf8'));

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath:
    process.env.HEALTHCHECK_BROWSER_EXECUTABLE });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1024, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      page.on('pageerror', e => errors.push(e.message));
      await page.route('**/*', route => {
        if (new URL(route.request().url()).origin !== base) {
          external.push(route.request().url()); return route.abort();
        }
        return route.continue();
      });
      const selected = new URLSearchParams({ period: '7', end_date: identity.end,
        calendar_year: '2099', garmin_source_id: identity.source_id });
      const statisticsURL = `${base}/statistics?${selected}`;
      assert.equal((await page.goto(statisticsURL)).status(), 200);
      const link = page.locator('[data-session-drilldown="tennis_session_count"]');
      await link.focus();
      assert.equal(await link.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
      await page.screenshot({ path: path.join(evidence, `statistics-${width}.png`), fullPage: true });
      await Promise.all([page.waitForURL(/\/statistics\/sessions\?/), page.keyboard.press('Enter')]);
      const sessionsURL = page.url();
      assert.equal(await page.locator('[data-session-record]').count(), 3);
      assert.ok((await page.locator('tbody').innerText()).includes('Поле отсутствует'));
      assert.ok((await page.locator('#sessions-title').innerText()).includes('Теннис'));
      const localDates = await page.locator('tbody tr td:first-child').allTextContents();
      assert.equal(new Set(localDates).size, 1);
      assert.ok(localDates[0].includes('2099'));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: path.join(evidence, `tennis-count-${width}.png`), fullPage: true });
      const first = page.locator('tbody a').first();
      const href = await first.getAttribute('href');
      const detailParams = new URL(href, base).searchParams;
      const record = detailParams.get('record_id');
      assert.ok(identity.records.includes(record));
      assert.equal(detailParams.get('garmin_source_id'), identity.source_id);
      assert.equal(detailParams.get('start_date'), identity.start);
      assert.equal(detailParams.get('end_date'), identity.end);
      assert.equal(detailParams.get('origin_metric_code'), 'tennis_session_count');
      assert.equal(detailParams.has('metric_code'), false);
      // Reach the first detail link through Tab from the scroll region.
      await page.locator('.table-scroll').focus();
      await page.keyboard.press('Tab');
      assert.equal(await first.evaluate(el => document.activeElement === el), true);
      assert.equal(await first.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
      await Promise.all([page.waitForURL(/\/garmin\/session\?/), page.keyboard.press('Enter')]);
      assert.ok((await page.locator('#activity-session-evidence').textContent()).includes(record));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: path.join(evidence, `detail-${width}.png`), fullPage: true });
      await page.goBack();
      assert.equal(page.url(), sessionsURL);
      assert.equal(await page.locator('[data-session-record]').count(), 3);
      await page.locator('[data-statistics-return]').click();
      const restored = new URL(page.url()).searchParams;
      for (const [key, value] of selected) assert.equal(restored.get(key), value);
      await page.locator('[data-session-drilldown="tennis_duration_seconds"]').click();
      assert.equal(await page.locator('[data-session-record]').count(), 2);
      await page.screenshot({ path: path.join(evidence, `tennis-duration-${width}.png`), fullPage: true });
      await page.locator('[data-statistics-return]').click();
      await page.locator('[data-session-drilldown="activity_session_count"]').click();
      await page.getByRole('combobox', { name: 'Вид активности' }).selectOption('cycling');
      await page.getByRole('button', { name: 'Показать', exact: true }).click();
      const filteredURL = page.url();
      assert.equal(await page.locator('[data-session-record]').count(), 1);
      assert.ok((await page.locator('tbody').innerText()).includes('0.0'));
      await page.screenshot({ path: path.join(evidence, `cycling-filter-${width}.png`), fullPage: true });
      await page.locator('tbody a').click();
      await page.goBack();
      assert.equal(page.url(), filteredURL);
      assert.equal(await page.getByRole('combobox', { name: 'Вид активности' }).inputValue(), 'cycling');
      const emptyURL = new URL(filteredURL);
      emptyURL.searchParams.set('start_date', '2098-01-01');
      emptyURL.searchParams.set('end_date', '2098-01-07');
      await page.goto(emptyURL.href);
      assert.equal(await page.locator('[data-session-record]').count(), 0);
      assert.ok((await page.getByRole('status').innerText()).includes('нет допустимых сессий'));
      await page.screenshot({ path: path.join(evidence, `empty-${width}.png`), fullPage: true });
      const cappedURL = new URL(sessionsURL);
      cappedURL.searchParams.set('garmin_source_id', identity.cap_source_id);
      await page.goto(cappedURL.href);
      assert.equal(await page.locator('[data-session-record]').count(), 200);
      assert.ok((await page.getByRole('status').innerText()).includes('Список неполный'));
      assert.ok((await page.getByRole('status').innerText()).includes('как минимум ещё одна'));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: path.join(evidence, `capped-${width}.png`) });
      checks.push({ width, statisticsURL, sessionsURL, filteredURL, record,
        keyboard: true, history: true, cap: 200, sourceLocalDate: localDates[0], overflow: false });
      await page.close();
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    fs.writeFileSync(path.join(evidence, 'browser-results.json'), JSON.stringify({
      checks, errors, external, identity, checkedAt: new Date().toISOString(),
      candidate: process.env.HEALTHCHECK_CANDIDATE_SHA || 'working-tree',
    }, null, 2));
    console.log(JSON.stringify({ widths: checks.map(c => c.width), errors, external }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
