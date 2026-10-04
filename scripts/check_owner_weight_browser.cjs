/* Stage-4 narrow Chromium Weight smoke against a disposable synthetic UI.
 * Fixture: one confirmed weigh-in (single session, weight + body fat) with a
 * configured goal, served through the real / template. No uploads, provider
 * calls or database writes are performed by this check.
 * Set HEALTHCHECK_BROWSER_BASE_URL, HEALTHCHECK_BROWSER_EVIDENCE_DIR;
 * HEALTHCHECK_BROWSER_EXECUTABLE is optional (defaults to Playwright Chromium).
 * NODE_PATH must expose playwright.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
if (!base || !evidence || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) {
  throw new Error('Explicit loopback synthetic UI URL and evidence directory required');
}
const checks = [];
(async () => {
  const launchOptions = { headless: true };
  if (process.env.HEALTHCHECK_BROWSER_EXECUTABLE) {
    launchOptions.executablePath = process.env.HEALTHCHECK_BROWSER_EXECUTABLE;
  }
  const browser = await chromium.launch(launchOptions);
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
    const errors = [];
    page.on('pageerror', error => errors.push('pageerror: ' + error.message));
    page.on('console', message => {
      if (message.type() !== 'error') return;
      const url = (message.location() || {}).url || '';
      if (url.endsWith('/favicon.ico')) return;
      errors.push('console: ' + message.text());
    });

    await page.goto(base + '/');
    assert.equal(await page.locator('html').getAttribute('lang'), 'ru');
    assert.equal(await page.locator('h1').textContent(), 'Вес');
    assert.equal(await page.locator('.owner-nav [aria-current="page"]').textContent(), 'Вес');
    for (const snippet of [
      'Текущий подтверждённый вес',
      'Ряд веса',
      'Изменение за последнее время',
      'Покрытие и свежесть',
      'Последний состав тела',
      'Изменения при похожем весе',
      'Происхождение точек',
      'Технические детали',
      'Потребительский биоимпеданс',
    ]) {
      assert.match(await page.locator('main').innerText(), new RegExp(snippet.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    }
    checks.push('Russian Owner-first Weight surface loads with nav, hero and limitations');

    await page.locator('#weight-chart svg [data-series="raw"]').first().waitFor();
    assert.ok((await page.locator('#weight-chart svg [data-series="raw"]').count()) >= 1);
    assert.ok((await page.locator('#weight-chart svg [data-series="goal"]').count()) >= 1);
    assert.match(await page.locator('#trend-status').innerText(), /Тренд/);
    for (const panel of ['#rate-panel', '#coverage-panel', '#composition-latest', '#similar-panel']) {
      assert.ok(((await page.locator(panel).innerText()).trim()).length > 0, panel + ' rendered by chart JS');
    }
    assert.match(await page.locator('#composition-latest').innerText(), /Жир/);
    assert.match(await page.locator('.hero').innerText(), /81\.2/);
    assert.match(await page.locator('.hero').innerText(), /76\.0/);
    checks.push('Chart/render JS executes: raw+goal series, filled panels, current 81.2 and goal 76.0');

    const heroText = await page.locator('.hero').innerText();
    assert.doesNotMatch(heroText, /(^|\s)0(\.0)? кг/);
    const rateState = await page.locator('#rate-panel [data-owner-state]').getAttribute('data-owner-state');
    assert.ok(['insufficient', 'unavailable', 'unknown'].includes(rateState), 'rate honest state ' + rateState);
    const similarState = await page.locator('#similar-panel [data-owner-state]').getAttribute('data-owner-state');
    assert.ok(['insufficient', 'unavailable', 'unknown'].includes(similarState), 'similar honest state ' + similarState);
    checks.push('Honest missing states stay distinct and non-zero (rate ' + rateState + ', similar ' + similarState + ')');

    const tech = page.locator('main details.owner-details');
    assert.equal(await tech.getAttribute('open'), null);
    const techSummary = tech.locator('summary');
    await techSummary.focus();
    await page.keyboard.press('Enter');
    assert.equal(await tech.getAttribute('open'), '');
    assert.match(await tech.innerText(), /weight_trend_taewma_v1/);
    await page.keyboard.press('Enter');
    assert.equal(await tech.getAttribute('open'), null);
    assert.equal(await techSummary.evaluate(el => el === document.activeElement), true);
    checks.push('Technical disclosure is closed, opens exact evidence via keyboard and closes with focus retained');

    const dataLink = page.locator('main a[href^="/imports"]').first();
    await dataLink.click();
    await page.waitForURL('**/imports*');
    assert.equal(await page.locator('h1').textContent(), 'Данные');
    checks.push('Data link is reachable and lands on Данные');
    await page.goto(base + '/');
    await page.locator('#weight-chart svg [data-series="raw"]').first().waitFor();

    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1100, 800, 390]) {
      await page.setViewportSize({ width, height: 900 });
      const geometry = await page.evaluate(() => {
        const nav = document.querySelector('.owner-nav');
        const grid = document.querySelector('.grid');
        const chart = document.querySelector('#weight-chart');
        const summary = document.querySelector('main details.owner-details > summary');
        const navLink = document.querySelector('.owner-nav a');
        return {
          pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
          doc: document.documentElement.scrollWidth,
          view: innerWidth,
          columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
          navRows: new Set([...nav.children].map(item => item.offsetTop)).size,
          chartScroll: getComputedStyle(chart).overflowX,
          summaryHeight: summary.getBoundingClientRect().height,
          navHeight: navLink.getBoundingClientRect().height,
        };
      });
      assert.equal(geometry.pageOverflow, false, JSON.stringify(geometry));
      assert.equal(geometry.columns, width <= 800 ? 1 : 2, JSON.stringify(geometry));
      assert.equal(geometry.navRows, 1, JSON.stringify(geometry));
      assert.equal(geometry.chartScroll, 'auto', JSON.stringify(geometry));
      assert.ok(geometry.summaryHeight >= 44, JSON.stringify(geometry));
      assert.ok(geometry.navHeight >= 44, JSON.stringify(geometry));
      assert.match(await page.locator('.hero').innerText(), /81\.2/);
      assert.ok(((await page.locator('#rate-panel').innerText()).trim()).length > 0);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(evidence, 'weight-stage4-' + width + '.png'), fullPage: true });
    }
    checks.push('1100/800/390px: no page overflow, one narrow column, single nav row, 44px targets, honest states stay usable');

    assert.deepEqual(errors, []);
    checks.push('No console/page JavaScript errors throughout the smoke');
    fs.writeFileSync(path.join(evidence, 'weight-stage4-browser.json'), JSON.stringify({ status: 'PASS', checks, errors }, null, 2));
    console.log(JSON.stringify({ status: 'PASS', checks, errors }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
