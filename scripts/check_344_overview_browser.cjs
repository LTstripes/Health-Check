/* Real /brief, synthetic saved observations only. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
assert.ok(evidence);
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
    page.on('pageerror', error => errors.push(error.message));
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const [name, month, count, lines] of [
        ['empty', 2, 0, 0], ['one', 3, 1, 0], ['three', 4, 3, 2],
        ['sparse', 5, 3, 0], ['many', 7, 31, 30]
      ]) {
        const end = month === 2 ? 28 : (month === 4 ? 30 : 31);
        const m = String(month).padStart(2, '0');
        assert.equal((await page.goto(`${base}/brief?start_date=2099-${m}-01&end_date=2099-${m}-${end}`)).status(), 200);
        const figure = page.locator('[data-overview-chart="weight"]');
        assert.equal(await figure.locator('.overview-observed').count(), count);
        assert.equal(await figure.locator('.overview-trend').count(), lines);
        const connectors = figure.locator('.overview-weight-connector');
        assert.equal(await connectors.count(), Math.max(0, count - 1));
        assert.equal(await figure.locator('.overview-weight-connector-gap').count(), name === 'sparse' ? 2 : 0);
        for (const connector of await connectors.all()) {
          assert.equal(await connector.evaluate(el => getComputedStyle(el).strokeWidth), '1px');
          const dashed = (await connector.getAttribute('class')).includes('connector-gap');
          assert.equal(await connector.evaluate(el => getComputedStyle(el).strokeDasharray !== 'none'), dashed);
        }
        assert.equal(await figure.locator('.overview-weight-latest').count(), count ? 1 : 0);
        assert.match(await figure.innerText(), /EWMA, 21 день/);
        assert.match(await figure.innerText(), /нет наблюдений, это не ноль/);
        const geometry = await figure.evaluate(el => {
          const svg = el.querySelector('svg');
          const texts = [...svg.querySelectorAll('text')].map(t => {
            const rect = t.getBoundingClientRect();
            return { text: t.textContent, x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom };
          });
          const rect = svg.getBoundingClientRect();
          return { texts, left: rect.x, right: rect.right, bottom: rect.bottom,
            overflow: document.documentElement.scrollWidth > innerWidth + 1,
            fontSize: getComputedStyle(svg.querySelector('text')).fontSize,
            observedFill: getComputedStyle(svg.querySelector('.overview-observed') || svg).fill,
            ewmaStroke: getComputedStyle(svg.querySelector('.overview-weight-ewma') || svg).stroke };
        });
        assert.equal(geometry.overflow, false);
        assert.equal(geometry.fontSize, '15px');
        for (const t of geometry.texts) {
          assert.ok(t.x >= geometry.left - 1 && t.right <= geometry.right + 1, `Clipped label ${t.text}`);
          assert.ok(t.bottom <= geometry.bottom + 1, `Clipped date ${t.text}`);
        }
        for (let i = 0; i < geometry.texts.length; i++) for (let j = i + 1; j < geometry.texts.length; j++) {
          const a = geometry.texts[i], b = geometry.texts[j];
          assert.ok(a.right <= b.x || b.right <= a.x || a.bottom <= b.y || b.bottom <= a.y, 'Axis labels overlap');
        }
        if (count) assert.notEqual(geometry.observedFill, geometry.ewmaStroke);
        await figure.screenshot({ path: path.join(evidence, `${name}-chart-${width}.png`) });
        const details = page.locator('.overview-chart-values').first();
        await details.locator('summary').focus(); await page.keyboard.press('Enter');
        assert.equal(await details.locator('table').isVisible(), true);
        await details.locator('.table-scroll').focus();
        assert.equal(await details.locator('.table-scroll').evaluate(el => el === document.activeElement), true);
        if (count) assert.match(await details.innerText(), /кг/);
        await page.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); });
        await page.screenshot({ path: path.join(evidence, `${name}-${width}.png`), fullPage: true });
        checks.push({ width, name, count, lines, geometry });
      }
      assert.equal((await page.goto(base + '/brief?start_date=2099-01-01&end_date=2099-01-07')).status(), 200);
      const sleep = page.locator('[data-overview-chart="sleep"]');
      assert.deepEqual(await sleep.locator('.overview-hour-tick').allTextContents(), ['0 ч', '2 ч', '4 ч', '6 ч']);
      assert.equal(await sleep.locator('.overview-observed').count(), 4);
      assert.equal(await sleep.locator('.overview-gap').count(), 3);
      for (const label of await sleep.locator('.overview-hour-tick').all()) {
        const bounds = await label.evaluate(el => ({ label: el.getBoundingClientRect().toJSON(), svg: el.closest('svg').getBoundingClientRect().toJSON() }));
        assert.ok(bounds.label.x >= bounds.svg.x && bounds.label.right <= bounds.svg.right);
        assert.ok(bounds.label.y >= bounds.svg.y && bounds.label.bottom <= bounds.svg.bottom);
      }
      assert.match(await page.locator('.brief-overview-list').innerText(), /Пробуждение 7 января 2099/);
      const freshness = page.locator('.overview-freshness');
      assert.equal(await freshness.count(), 2);
      for (const note of await freshness.all()) {
        const details = note.locator('details'), summary = details.locator('summary');
        assert.equal(await details.getAttribute('open'), null);
        assert.equal(await details.locator('p').isVisible(), false);
        assert.match(await summary.innerText(), /Свежесть:/);
        assert.equal(await note.locator('a').isVisible(), true);
        await summary.focus(); await page.keyboard.press('Enter');
        assert.equal(await details.locator('p').isVisible(), true);
        assert.equal(await summary.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
        await page.keyboard.press('Space');
        assert.equal(await details.getAttribute('open'), null);
      }
      const table = page.locator('.overview-chart-values').nth(1);
      await table.locator('summary').click();
      assert.match(await table.innerText(), /0 ч 0 мин/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      await page.screenshot({ path: path.join(evidence, `sleep-freshness-${width}.png`), fullPage: true });
      checks.push({ width, name: 'sleep-freshness', hourTicks: true, zeroGapsDates: true, keyboard: true });
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const result = { sha: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
      browser: browser.version(), checks, errors, external };
    fs.writeFileSync(path.join(evidence, 'overview-344-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({ sha: result.sha, browser: result.browser, cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
