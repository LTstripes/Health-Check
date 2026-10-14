/* Real Overview, external synthetic saved samples, no provider requests. */
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
      for (const [name, start, end, expected] of [
        ['selected', '2099-01-25', '2099-01-31', '40'],
        ['one-day', '2099-01-31', '2099-01-31', '90'],
        ['zero', '2099-01-25', '2099-01-25', '0'],
        ['empty', '2099-02-02', '2099-02-05', null],
        ['long', '2097-01-01', '2099-01-31', '36'],
      ]) {
        assert.equal((await page.goto(`${base}/brief?start_date=${start}&end_date=${end}`)).status(), 200);
        const card = page.locator('[data-overview-body-battery]');
        assert.equal(await card.count(), 1);
        const selected = card.locator('[data-bb-window="selected"]');
        if (expected === null) {
          assert.equal(await selected.locator('strong').count(), 0);
          assert.match(await selected.innerText(), /нет пригодных измерений/);
        } else assert.match(await selected.innerText(), new RegExp(`среднее максимумов ${expected} баллы`));
        if (end === '2099-01-31') {
          assert.match(await card.locator('[data-bb-window="7"]').innerText(), /среднее максимумов 40 баллы/);
          assert.match(await card.locator('[data-bb-window="30"]').innerText(), /среднее максимумов 36 баллы/);
          assert.match(await card.locator('[data-bb-window="30"]').innerText(), /5 из 30 дней/);
          assert.match(await card.locator('[data-bb-window="30"]').innerText(), /без пригодного максимума: 25/);
          assert.match(await card.innerText(), /31 января 2099/);
        }
        assert.match(await card.innerText(), /полнота суток неизвестна/);
        assert.doesNotMatch(await card.innerText(), /99 баллы/);
        const geometry = await card.evaluate(el => ({
          card: el.getBoundingClientRect().toJSON(),
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
          clipped: [...el.querySelectorAll('strong, p, summary')].filter(node => {
            const rect = node.getBoundingClientRect();
            return rect.width > 0 && (rect.right > innerWidth + 1 || rect.left < 0);
          }).map(node => node.textContent),
        }));
        assert.equal(geometry.overflow, false); assert.deepEqual(geometry.clipped, []);
        await card.screenshot({ path: path.join(evidence, `${name}-card-${width}.png`) });
        await page.screenshot({ path: path.join(evidence, `${name}-${width}.png`), fullPage: true });
        const details = card.locator('[data-bb-evidence]');
        assert.equal(await details.getAttribute('open'), null);
        await details.locator('summary').focus(); await page.keyboard.press('Enter');
        assert.notEqual(await details.getAttribute('open'), null);
        assert.equal(await details.locator('summary').evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
        assert.match(await details.innerText(), /равным весом дней/);
        if (name === 'zero') assert.match(await details.innerText(), /явный ноль/);
        if (name === 'selected') {
          assert.match(await details.innerText(), /120 \/ 3|40 \/ 1/);
          assert.match(await details.innerText(), /Скалярный снимок или производный псевдоним/);
          await card.screenshot({ path: path.join(evidence, `selected-details-${width}.png`) });
        }
        await page.keyboard.press('Space');
        assert.equal(await details.getAttribute('open'), null);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        checks.push({ width, name, expected, geometry, keyboard: 'Enter/Space and focus outline passed' });
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const result = { sha: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
      browser: browser.version(), checks, errors, external };
    fs.writeFileSync(path.join(evidence, 'overview-394-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({ sha: result.sha, browser: result.browser, cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
