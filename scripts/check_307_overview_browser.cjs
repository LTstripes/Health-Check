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
    for (const width of [1100, 800, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base + '/brief?start_date=2099-01-01&end_date=2099-01-02');
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
      if (width === 390) assert.equal(geometry.localScroll, true);
      const technical = page.locator('.brief-provenance');
      await technical.locator('summary').focus();
      await page.keyboard.press('Enter');
      assert.match(await technical.innerText(), /r297-google-daily-vitals-read-v1/);
      assert.match(await technical.innerText(), /60\.123456/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      await page.keyboard.press('Enter');
      await page.screenshot({ path: path.join(evidence, 'overview-' + width + '.png'), fullPage: true });
      checks.push(width + 'px: independent source values, dates, missing/null/zero, disclosure, no page overflow');
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
