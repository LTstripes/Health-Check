/* #297 focused desktop Chromium smoke for the source-explicit Google daily-vitals block.
 * Run against a disposable synthetic UI seeded with
 * tests/test_google_daily_vitals.py:seed_google_daily_vitals.
 * Explicit loopback URL and external evidence directory are required.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
if (!base || !evidence || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) {
  throw new Error('Explicit loopback synthetic URL and evidence directory required');
}
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    const page = await browser.newPage();
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {
      if (m.type() === 'error' && !(m.location().url || '').endsWith('/favicon.ico')) {
        errors.push(m.text());
      }
    });
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base + '/sleep?wake_date=2099-01-02&view=google');
      assert.equal(await page.locator('html').getAttribute('lang'), 'ru');
      assert.equal(await page.locator('h1').innerText(), 'Сон');
      const block = page.locator('[data-google-vitals]');
      assert.equal(await block.count(), 1);
      const text = await block.innerText();
      assert.match(text, /Google дневные показатели/);
      assert.equal(await page.locator('[data-google-source]').count(), 2);
      assert.equal(await page.locator('[data-google-metric]').count(), 8);
      assert.match(text, /Google · Fitbit Air/);
      assert.match(text, /Google · семейство устройств/);
      assert.doesNotMatch(text, /google-wearables/);
      assert.match(text, /42\.5 мс/);
      assert.match(text, /2 января 2099/);
      assert.equal(await block.locator('.status-chip[data-owner-state="present"]').count(), 0);
      assert.match(text, /55\.0 уд\/мин/);
      assert.match(text, /97\.0 %/);
      assert.match(text, /13\.5 вдохов\/мин/);
      assert.match(text, /0\.0 вдохов\/мин/);
      assert.match(text, /явный ноль/);
      assert.match(text, /пустое значение/);
      assert.match(text, /Нет текущих записей в окне/);
      assert.doesNotMatch(text, /daily_hrv_average_ms|r297-google-daily-vitals-read-v1|candidates/);
      const options = await block.locator('select[name="vitals_window"] option').allInnerTexts();
      assert.deepEqual(options.map(value => value.trim()), ['7 дней', '30 дней', '90 дней']);
      const geo = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
      }));
      assert.equal(geo.overflow, false, JSON.stringify(geo));
      await page.selectOption('[data-google-vitals] select[name="vitals_window"]', '7');
      await Promise.all([
        page.waitForURL(/vitals_window=7/),
        block.locator('button[type="submit"]').click(),
      ]);
      assert.match(await page.locator('[data-google-vitals]').innerText(), /27 декабря 2098 → 2 января 2099/);
      await page.goto(base + '/sleep?wake_date=2099-01-02&view=google');
      await page.screenshot({
        path: path.join(evidence, 'google-vitals-' + width + '.png'), fullPage: true,
      });
      checks.push(width + 'px: two source-explicit blocks, mixed states, bounded window switch, no overflow');
    }
    await page.setViewportSize({ width: 1100, height: 900 });
    await page.goto(base + '/sleep?view=garmin&wake_date=2099-01-03');
    assert.match(await page.locator('.sleep-night').innerText(), /нет пригодного значения/);
    await page.goto(base + '/sleep?wake_date=2099-01-03&view=google');
    const missingNight = page.locator('[data-google-vitals]');
    assert.match(await missingNight.innerText(), /42\.5 мс/);
    const googleDetails = page.locator('main details.sleep-technical');
    assert.equal(await googleDetails.getAttribute('open'), null);
    await googleDetails.locator('summary').focus();
    await page.keyboard.press('Enter');
    assert.equal(await googleDetails.getByRole('heading', {name: 'Google', exact: true}).count(), 1);
    assert.match(await googleDetails.innerText(), /r297-google-daily-vitals-read-v1/);
    assert.match(await googleDetails.innerText(), /candidates/);
    checks.push('Unpaired Google values on a missing Garmin night; exact provenance stays in disclosure');
    assert.deepEqual(errors, []);
    checks.push('No console or page JavaScript errors');
    const result = { status: 'PASS', checks, errors };
    fs.writeFileSync(path.join(evidence, 'google-vitals-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
