/* Real /brief, persisted --overview-a-plus synthetic fixture. Desktop only. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
assert.ok(evidence);
const query = '/brief?start_date=2099-01-01&end_date=2099-01-07';
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    const page = await browser.newPage();
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin !== base) {
        external.push(route.request().url()); return route.abort();
      }
      return route.continue();
    });
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal((await page.goto(base + query)).status(), 200);
      const geometry = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        columns: getComputedStyle(document.querySelector('.brief-overview-list')).gridTemplateColumns.split(' ').length,
        bg: getComputedStyle(document.body).backgroundColor,
        valueFont: getComputedStyle(document.querySelector('.overview-value')).fontFamily,
        border: getComputedStyle(document.querySelector('.brief-overview-list > li')).borderTopWidth
      }));
      assert.deepEqual({ ...geometry, valueFont: undefined }, {
        overflow: false, columns: 3, bg: 'rgb(246, 242, 233)', valueFont: undefined, border: '0px'
      });
      assert.match(geometry.valueFont, /Georgia/);
      const primary = page.locator('.brief-overview-list');
      assert.match(await primary.locator('.overview-value').nth(0).innerText(), /74.2 кг/);
      assert.match(await primary.locator('.overview-value').nth(1).innerText(), /7 ч 20 мин/);
      assert.match(await primary.locator('.overview-value').nth(2).innerText(), /3/);
      assert.equal(await page.locator('[data-overview-chart] svg').count(), 3);
      for (const figure of await page.locator('[data-overview-chart] svg').all()) {
        assert.ok((await figure.locator('title').first().textContent()).length > 0);
        assert.match(await figure.locator('desc').textContent(), /это не ноль/);
        const box = await figure.boundingBox();
        assert.ok(box.y + box.height < 1000, 'All primary charts visible in first desktop viewport');
      }
      assert.equal(await page.locator('.brief-provenance').getAttribute('open'), null);
      assert.equal(await page.locator('.overview-all-sources').getAttribute('open'), null);
      assert.doesNotMatch(await page.locator('main').innerText(), /r297-google|result_hash|60\.123456/);
      await page.screenshot({ path: path.join(evidence, `a-plus-${width}.png`), fullPage: true });
      for (const info of await page.locator('.overview-info').all()) {
        const summary = info.locator('summary');
        await summary.focus(); await page.keyboard.press('Enter');
        assert.equal(await info.getAttribute('open'), '');
        assert.equal(await summary.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        await page.keyboard.press('Space'); assert.equal(await info.getAttribute('open'), null);
      }
      for (const detail of await page.locator('.overview-chart-values').all()) {
        await detail.locator('summary').focus(); await page.keyboard.press('Enter');
        assert.equal(await detail.locator('table').isVisible(), true);
        assert.equal(await detail.locator('.table-scroll').evaluate(el => getComputedStyle(el).overflowX), 'auto');
      }
      assert.match(await page.locator('.overview-chart-values').nth(1).innerText(), /0 ч 0 мин/);
      assert.match(await page.locator('.overview-chart-values').nth(2).innerText(), /Состояние данных не определено/);
      const all = page.locator('.overview-all-sources');
      await all.locator(':scope > summary').focus(); await page.keyboard.press('Enter');
      assert.match(await all.innerText(), /HRV Garmin — среднее за неделю; Google — за день/);
      assert.match(await all.innerText(), /42\.5 мс/);
      assert.match(await all.innerText(), /Google: явный ноль/);
      const technical = page.locator('.brief-provenance');
      await technical.locator('summary').focus(); await page.keyboard.press('Enter');
      const packet = JSON.parse(await technical.locator('.brief-packet').textContent());
      assert.equal(packet.sections.activity.coverage.sessions_in_period, 3);
      assert.match(await technical.innerText(), /weight_trend_taewma_v1/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      await page.screenshot({ path: path.join(evidence, `a-plus-expanded-${width}.png`), fullPage: true });
      checks.push(`${width}x1000: real values, three charts, gaps/zero, source separation, keyboard/focus, tables and raw packet; no overflow`);
    }
    await page.goto(base + '/brief?start_date=2099-01-01&end_date=2101-01-01');
    assert.match(await page.locator('[data-overview-sources]').innerText(), /Окно Google: 28 ноября 2099/);
    assert.match(await page.locator('.brief-overview-list').innerText(), /Окно сна:/);
    assert.match(await page.locator('.overview-secondary').innerText(), /52 уд\/мин/);
    assert.doesNotMatch(await page.locator('main').innerText(), /42\.5 мс/);
    await page.goto(base + query);
    await page.locator('.brief-custom-period > summary').click();
    await page.locator('input[name="start_date"]').fill('2099-02-01');
    await page.locator('input[name="end_date"]').fill('2099-02-07');
    await page.getByRole('button', { name: 'Применить период' }).click();
    assert.match(page.url(), /start_date=2099-02-01/);
    assert.doesNotMatch(await page.locator('.brief-overview-list').innerText(), /74\.2 кг|7 ч 20 мин/);
    assert.equal(await page.locator('.brief-priority').count(), 1); // Pending import still needs action.
    await page.getByRole('link', { name: '7 дней', exact: true }).click();
    assert.match(page.url(), /preset=7/);
    assert.match(await page.locator('.brief-period').innerText(), /7 дней/);
    checks.push('Long window keeps exact Google/sleep bounds and Garmin snapshot; date form/presets clear previous values');
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    const result = { sha, browser: browser.version(), checks, errors, external };
    fs.writeFileSync(path.join(evidence, 'a-plus-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
