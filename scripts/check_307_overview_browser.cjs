/* Focused Overview v2 checks against --overview-v2 synthetic fixture only. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
if (!base || !evidence || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) {
  throw new Error('Explicit synthetic loopback URL and external evidence directory required');
}
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    const page = await browser.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error' && !(message.location().url || '').endsWith('/favicon.ico')) {
        errors.push(message.text());
      }
    });
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base + '/brief?start_date=2099-01-01&end_date=2099-01-02');
      const sources = page.locator('[data-overview-sources]');
      assert.match(await sources.innerText(), /Вес:.*Garmin:.*Google:/s);
      assert.match(await sources.innerText(), /текущими записями в периоде — 2/);
      const sourceBox = await sources.boundingBox();
      assert.ok(sourceBox.y + sourceBox.height <= 900, 'All three sources are explicit in the first viewport');
      const block = page.locator('[data-overview-vitals]');
      assert.equal(await block.locator('thead th').count(), 4);
      assert.match(await block.locator('thead').innerText(), /Garmin/);
      assert.match(await block.locator('thead').innerText(), /Google · Fitbit Air/);
      assert.match(await block.locator('thead').innerText(), /Google · семейство устройств/);
      const rhr = block.locator('tbody tr').nth(0);
      assert.match(await rhr.locator('[data-overview-garmin]').innerText(), /52 уд\/мин/);
      assert.match(await rhr.locator('[data-overview-google]').nth(0).innerText(), /55 уд\/мин/);
      assert.match(await rhr.locator('[data-overview-google]').nth(1).innerText(), /Пульс в покое: нет текущих записей/);
      const hrv = block.locator('tbody tr').nth(1);
      assert.match(await hrv.innerText(), /60\.12 мс/);
      assert.match(await hrv.innerText(), /42\.5 мс/);
      assert.match(await hrv.innerText(), /пустое значение/);
      assert.match(await block.locator('tbody tr').nth(2).innerText(), /98 %/);
      assert.match(await block.locator('tbody tr').nth(2).innerText(), /97 %/);
      assert.match(await block.locator('tbody tr').nth(2).innerText(), /96 %/);
      const rr = block.locator('tbody tr').nth(3);
      assert.match(await rr.innerText(), /14\.12 вдохов\/мин/);
      assert.match(await rr.innerText(), /13\.5 вдохов\/мин/);
      assert.match(await rr.innerText(), /Google: явный ноль/);
      assert.match(await block.innerText(), /среднее за неделю/);
      assert.match(await block.innerText(), /Снимок; суточное среднее не подтверждено/);
      assert.match(await page.locator('[data-overview-garmin-only]').innerText(), /Стресс Garmin/);
      assert.match(await page.locator('[data-overview-garmin-only]').innerText(), /0 баллы/);
      assert.match(await page.locator('[data-overview-garmin-only]').innerText(), /65 баллы/);
      assert.equal(await page.locator('.brief-empty-state').count(), 0);
      assert.equal(await page.locator('.brief-provenance').getAttribute('open'), null);
      assert.equal(await page.locator('.brief-limitations').getAttribute('open'), null);
      assert.doesNotMatch(await page.locator('main').innerText(), /r297-google-daily-vitals-read-v1|60\.123456/);
      const geometry = await page.evaluate(() => {
        const scroll = document.querySelector('[data-overview-vitals] .table-scroll');
        return { pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
          localScroll: scroll.scrollWidth > scroll.clientWidth, overflow: getComputedStyle(scroll).overflowX };
      });
      assert.equal(geometry.pageOverflow, false, JSON.stringify(geometry));
      assert.equal(geometry.overflow, 'auto');
      const technical = page.locator('.brief-provenance');
      await technical.locator('summary').focus();
      await page.keyboard.press('Enter');
      assert.match(await technical.innerText(), /r297-google-daily-vitals-read-v1/);
      assert.match(await technical.innerText(), /60\.123456/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      await page.keyboard.press('Enter');
      await page.screenshot({ path: path.join(evidence, 'overview-' + width + '.png'), fullPage: true });
      checks.push(width + 'px: independent source values, dates, missing/null/zero, disclosure, no page overflow');
      const boundary = await page.goto(base + '/brief?start_date=2099-01-01&end_date=2100-02-05');
      assert.equal(boundary.status(), 200); // 401 inclusive days; Google begins on Jan 2.
      assert.match(await sources.innerText(), /Окно Google: 2 января 2099.*5 февраля 2100/s);
      assert.match(await page.locator('[data-overview-google-window]').innerText(), /последние 400 дней/);
      assert.match(await block.innerText(), /42\.5 мс/);
      assert.match(await block.innerText(), /Пульс в покое: нет текущих записей в окне Google/);
      const longPeriod = await page.goto(base + '/brief?start_date=2099-01-01&end_date=2101-01-01');
      assert.equal(longPeriod.status(), 200);
      assert.match(await sources.innerText(), /Google: нет текущих записей в окне Google/);
      assert.match(await sources.innerText(), /Окно Google: 28 ноября 2099.*1 января 2101/s);
      assert.match(await block.innerText(), /52 уд\/мин/); // Garmin keeps the full selected period.
      assert.doesNotMatch(await block.innerText(), /42\.5 мс|55 уд\/мин/);
      assert.match(await block.innerText(), /Google · HRV: нет текущих записей в окне Google/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      await page.screenshot({ path: path.join(evidence, 'overview-long-period-' + width + '.png'), fullPage: true });
      checks.push(width + 'px: >400-day custom period stays 200, explicit bounded Google dates, Garmin full-period values');
    }
    await page.goto(base + '/brief?start_date=2099-01-04&end_date=2099-01-05');
    const missing = page.locator('[data-overview-vitals]');
    assert.doesNotMatch(await missing.innerText(), /52 уд\/мин|42\.5 мс/);
    assert.match(await missing.innerText(), /Garmin: нет записи этого показателя в выбранном периоде/);
    assert.match(await missing.innerText(), /Google · HRV: нет текущих записей в выбранном периоде/);
    checks.push('Period change clears old values and keeps source/metric-specific missing states');
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(evidence, 'overview-browser.json'), JSON.stringify({status:'PASS',checks,errors}, null, 2));
    console.log(JSON.stringify({status:'PASS',checks,errors}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
