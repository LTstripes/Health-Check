/* #317 production source-view browser checks against serve_317_sleep_fixture.py. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
if (!base || !evidence || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) {
  throw new Error('Explicit loopback synthetic URL and external evidence directory required');
}
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    const page = await browser.newPage({ locale: 'ru-RU' });
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error' && !(message.location().url || '').endsWith('/favicon.ico')) {
        errors.push(message.text());
      }
    });
    async function geometry() {
      const g = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        navRows: new Set([...document.querySelector('.owner-nav').children].map(x => x.offsetTop)).size,
        summaries: [...document.querySelectorAll('main > details > summary, .source-sleep-details > summary')]
          .filter(el => el.getBoundingClientRect().height > 0)
          .map(el => el.getBoundingClientRect().height),
      }));
      assert.equal(g.overflow, false, JSON.stringify(g));
      assert.equal(g.navRows, 1);
      assert.ok(g.summaries.every(height => height >= 44), JSON.stringify(g));
    }
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base + '/sleep?wake_date=2099-01-02');
      const garmin = page.locator('.sleep-night');
      assert.match(await garmin.innerText(), /8 ч 0 мин.*82/s);
      assert.match(await garmin.innerText(), /2099-01-02T06:45:00Z/);
      const details = garmin.locator('.source-sleep-details');
      assert.equal(await details.getAttribute('open'), null);
      await details.locator('summary').focus();
      await page.keyboard.press('Enter');
      assert.match(await details.innerText(), /1 ч 30 мин/);
      assert.match(await details.innerText(), /0 ч 15 мин/);
      assert.match(await details.innerText(), /календарному дню/);
      await geometry();
      await page.keyboard.press('Enter');
      assert.equal(await details.getAttribute('open'), null);
      await page.screenshot({ path: path.join(evidence, `317-garmin-${width}.png`), fullPage: true });
      await page.locator('.sleep-source-switch a[href*="view=google"]').click();
      await page.waitForURL('**view=google**');
      assert.match(page.url(), /wake_date=2099-01-02/);
      const google = page.locator('.google-sleep-night');
      assert.match(await google.innerText(), /6 ч 50 мин/);
      assert.match(await google.innerText(), /2099-01-01T22:00:00Z/);
      assert.doesNotMatch(await google.innerText(), /42\.5|уд\/мин|мс/);
      assert.equal(await page.locator('[data-google-source]').count(), 2);
      assert.match(await page.locator('[data-google-vitals]').innerText(), /42\.5 мс/);
      assert.equal(await google.locator('.source-sleep-details').getAttribute('open'), null);
      await google.locator('.source-sleep-details > summary').click();
      assert.match(await google.innerText(), /1 ч 0 мин/);
      await geometry();
      await google.locator('.source-sleep-details > summary').click();
      const tech = page.locator('.sleep-technical');
      assert.equal(await tech.getAttribute('open'), null);
      await tech.locator('summary').focus();
      await page.keyboard.press('Enter');
      assert.match(await tech.innerText(), /source_eligibility|normalization_provenance/);
      assert.match(await tech.innerText(), /source_utc_offset_minutes/);
      await geometry();
      await page.keyboard.press('Enter');
      await page.screenshot({ path: path.join(evidence, `317-google-${width}.png`), fullPage: true });
      for (const [day, text] of [
        [3, /За эту дату нет сохранённых сессий Google/],
        [4, /Несколько сессий за дату; единая ночь не выбрана/],
        [5, /совместимые стадии недоступны/],
        [6, /Сохранённой сводки недостаточно/],
        [7, /0 ч 0 мин/],
        [8, /Роль основного сна не подтверждена/],
        [9, /Запись дневного сна/],
      ]) {
        await page.goto(base + `/sleep?view=google&wake_date=2099-01-${String(day).padStart(2, '0')}`);
        if ([5, 6].includes(day)) await page.locator('.source-sleep-details > summary').click();
        const visible = await page.locator('.google-sleep-night').innerText();
        assert.match(visible, text);
        if ([3, 4, 9].includes(day)) assert.doesNotMatch(visible, /6 ч 50 мин/);
        if (day === 4) {
          assert.equal(await page.locator('.source-sleep-sessions').getAttribute('open'), null);
          await page.locator('.source-sleep-sessions > summary').click();
          assert.equal(await page.locator('[data-sleep-session]').count(), 2);
          assert.match(await page.locator('.source-sleep-sessions').innerText(), /6 ч 50 мин/);
        }
        if (day === 3) assert.match(await page.locator('[data-google-vitals]').innerText(), /2 января 2099/);
        await geometry();
        await page.screenshot({ path: path.join(evidence, `317-google-day${day}-${width}.png`), fullPage: true });
      }
      await page.locator('.sleep-source-switch a[href*="view=compare"]').click();
      await page.waitForURL('**view=compare**');
      assert.equal(await page.locator('[data-source-sleep]').count(), 0);
      assert.equal(await page.locator('[data-source-series]').count(), 0);
      await geometry();
      checks.push(`${width}px: Garmin/Google source sleep, separate dated vitals, missing/ambiguous/CLASSIC/summary-only/zero/uncertain-role/nap, keyboard disclosure, unchanged empty Compare, no overflow`);
    }
    assert.deepEqual(errors, []);
    const result = { status: 'PASS', browser: browser.version(), checks, errors };
    fs.writeFileSync(path.join(evidence, '317-sleep-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
