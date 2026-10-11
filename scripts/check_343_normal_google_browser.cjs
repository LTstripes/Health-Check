/* #343 normal Google family display; synthetic loopback profile only. */
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
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    const page = await browser.newPage({ locale: 'ru-RU' });
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin === base) return route.continue();
      external.push(url.origin);
      return route.abort();
    });
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error' && !(message.location().url || '').endsWith('/favicon.ico')) {
        errors.push(message.text());
      }
    });
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base + '/sleep?wake_date=2099-01-02');
      const timeline = page.locator('[data-sleep-timeline]');
      const packet = JSON.parse(await page.locator('#sleep-timeline-data').textContent());
      assert.equal(packet.google_selection.status, 'sole_google_wearables');
      assert.deepEqual(await timeline.locator('.sleep-series-toggle').allInnerTexts(), ['Garmin', 'Google']);
      assert.equal(await timeline.locator('[data-sleep-series-toggle]').count(), 2);
      assert.equal(await timeline.locator('[data-sleep-series-group^="google:"]').count(), 1);
      const alternate = timeline.locator('[data-sleep-alternate-sources]');
      assert.equal(await alternate.getAttribute('open'), null);
      const googlePoint = timeline.locator('[data-sleep-series-group^="google:"] [data-sleep-point-state="value"]');
      await googlePoint.focus();
      const detail = await timeline.locator('#sleep-timeline-detail').innerText();
      assert.match(detail, /6 ч 50 мин/);
      assert.match(detail, /24600 с/);
      assert.match(detail, /роль|основной|неопредел/i);
      assert.doesNotMatch(detail, /Оценка сна Garmin/);
      const toggle = timeline.locator('[data-sleep-series-toggle]').nth(1);
      await toggle.uncheck();
      assert.equal(await timeline.locator('[data-sleep-series-group^="google:"]').isHidden(), true);
      await toggle.check();
      await page.screenshot({ path: path.join(evidence, `343-normal-${width}.png`), fullPage: true });
      await alternate.locator('summary').focus();
      await page.keyboard.press('Enter');
      assert.match(await alternate.innerText(), /FITBIT/);
      assert.match(await alternate.innerText(), /Нет записей сна в этом окне/);
      assert.match(await alternate.innerText(), /Нет пригодной длительности/);
      assert.ok(await alternate.locator('option[disabled]').count() >= 3);
      await alternate.locator('select').selectOption(packet.google_selection.selected_source_id);
      await alternate.locator('button').click();
      await page.waitForURL('**google_sleep_source_id=**');
      await timeline.locator('.preset-links a[href*="days=7"]').click();
      await page.waitForURL('**days=7**');
      const week = JSON.parse(await page.locator('#sleep-timeline-data').textContent());
      assert.equal(week.google_selection.selected_source_id, packet.google_selection.selected_source_id);
      assert.equal(week.google_selection.status, 'explicit');
      assert.equal(week.days, 7);
      assert.equal(await timeline.locator('[data-sleep-timeline-cell]').count(), 28);
      await page.locator('.sleep-technical > summary').click();
      const technical = await page.locator('.sleep-technical').innerText();
      assert.match(technical, /single_uncertain_session/);
      assert.match(technical, /google_family_excluded/);
      assert.match(technical, /google_nap_only/);
      assert.match(technical, /FITBIT-empty/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      await page.screenshot({ path: path.join(evidence, `343-normal-details-${width}.png`), fullPage: true });
      checks.push(`${width}px: two provider lines, sole eligible family, no pooled points, retained excluded/empty/vitals identities, uncertain role, keyboard details, toggles, 7/30 selection, no overflow`);
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    const result = { status: 'PASS', browser: browser.version(), checks, errors, external };
    fs.writeFileSync(path.join(evidence, '343-normal-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
