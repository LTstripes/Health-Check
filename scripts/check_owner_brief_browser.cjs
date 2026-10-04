/* Stage-3 focused browser acceptance against a disposable synthetic UI.
 * Requires the populated presentation fixture from tests/test_period_brief_ui.py
 * served through the real /brief template, plus the normal empty-runtime page.
 * Set HEALTHCHECK_BROWSER_BASE_URL, HEALTHCHECK_BROWSER_EXECUTABLE,
 * HEALTHCHECK_BROWSER_EVIDENCE_DIR; NODE_PATH must expose playwright.
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
const fixtureQuery = '?start_date=2099-01-01&end_date=2099-01-07';
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/brief' + fixtureQuery);
    assert.equal(await page.locator('html').getAttribute('lang'), 'ru');
    assert.equal(await page.locator('h1').textContent(), 'Обзор');
    assert.equal(await page.locator('.owner-nav [aria-current="page"]').textContent(), 'Обзор');
    assert.equal(await page.locator('.brief-comparison').count(), 7);
    assert.equal(await page.locator('.brief-statistics').count(), 5);
    assert.match(await page.locator('.brief-sleep').innerText(), /-120 с/);
    assert.match(await page.locator('.brief-sleep').innerText(), /0\.5 п\.п\./);
    assert.match(await page.locator('.brief-sleep').innerText(), /не оценка точности/);
    assert.match(await page.locator('.brief-sleep').innerText(), /Принятое сравнение недоступно/);
    assert.match(await page.locator('.brief-overview').innerText(), /0 шт\./);
    assert.match(await page.locator('.brief-overview').innerText(), /Недостаточно данных/);
    assert.equal(await page.locator('[aria-labelledby="brief-actions-heading"] li').count(), 4);
    assert.match(await page.locator('[aria-labelledby="brief-actions-heading"]').innerText(), /Свежесть неизвестна/);
    assert.match(await page.locator('[aria-labelledby="brief-actions-heading"]').innerText(), /Повторите вход/);
    for (const link of await page.locator('[aria-labelledby="brief-actions-heading"] a').all()) {
      assert.match(await link.getAttribute('href'), /^\/imports/);
    }
    const tech = page.locator('.brief-provenance');
    assert.equal(await tech.getAttribute('open'), null);
    assert.equal(await tech.locator('pre').isVisible(), false);
    assert.doesNotMatch(await page.locator('main').innerText(), /synthetic-result-hash|future_metric|refresh_overdue|Полнота данных и происхождение/);
    checks.push('Owner hierarchy, distinct evidence states, meaningful sleep units and source/action deduplication');

    const source = page.locator('.brief-source');
    assert.equal(await source.getAttribute('open'), '');
    await source.locator('select').selectOption('synthetic-one');
    await source.getByRole('button', { name: 'Выбрать источник' }).click();
    await page.waitForURL('**/brief?**garmin_source_id=synthetic-one');
    assert.match(page.url(), /start_date=2099-01-01/);
    assert.match(page.url(), /end_date=2099-01-07/);
    assert.equal(await source.getAttribute('open'), null);
    assert.match(await source.locator('summary').innerText(), /Garmin Connect/);
    checks.push('Required source choice is open; selecting a source preserves the period and collapses the control');

    const techSummary = tech.locator('summary');
    await techSummary.focus();
    await page.keyboard.press('Enter');
    assert.equal(await tech.locator('pre').isVisible(), true);
    const packet = JSON.parse(await tech.locator('pre').textContent());
    assert.equal(packet.result_hash, 'synthetic-result-hash');
    assert.equal(packet.sections.sleep.groups.length, 7);
    assert.equal(packet.owner_actions.length, 6);
    assert.equal(packet.sections.sleep.groups[0].bias, -120);
    await page.keyboard.press('Enter');
    assert.equal(await tech.locator('pre').isVisible(), false);
    assert.equal(await techSummary.evaluate(el => el === document.activeElement), true);
    checks.push('Keyboard disclosure opens exact raw evidence and closes with focus retained');

    for (const width of [1100, 800, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await techSummary.click();
      const records = page.locator('.brief-records');
      await records.locator('summary').click();
      assert.equal(await records.locator('table').first().isVisible(), true);
      const geometry = await page.evaluate(() => ({
        doc: document.documentElement.scrollWidth, view: innerWidth,
        columns: getComputedStyle(document.querySelector('.brief-overview-list')).gridTemplateColumns.split(' ').length,
        tableDisplay: getComputedStyle(document.querySelector('.brief-records table')).display,
        scroll: getComputedStyle(document.querySelector('.table-scroll')).overflowX,
        linkColor: getComputedStyle(document.querySelector('.brief-overview a')).color,
        bg: getComputedStyle(document.body).backgroundColor
      }));
      assert.ok(geometry.doc <= geometry.view + 1, JSON.stringify(geometry));
      assert.equal(geometry.columns, width <= 800 ? 1 : 3);
      assert.equal(geometry.tableDisplay, 'table');
      assert.equal(geometry.scroll, 'auto');
      assert.equal(geometry.bg, 'rgb(243, 241, 236)');
      assert.equal(geometry.linkColor, 'rgb(31, 92, 87)');
      for (const control of await page.locator('.brief-controls .button-link, .brief-controls > form button, .brief-controls > form input[type="date"], .owner-details > summary').all()) {
        const box = await control.boundingBox();
        if (box) assert.ok(box.height >= 44, `target height ${box.height} at ${width}`);
      }
      await page.screenshot({ path: path.join(evidence, `brief-stage3-${width}.png`), fullPage: true });
      await techSummary.click();
      await records.locator('summary').click();
    }
    checks.push('1100/800/390px: opened evidence and records fit; real tables scroll; 44px controls and frozen palette');

    // A delayed server-rendered navigation keeps one coherent applied period
    // until the new document commits; it never updates just a heading/card.
    let release;
    let entered;
    let appliedPeriodSnapshot;
    page.on('console', message => {
      if (message.text().startsWith('brief-applied-period:')) appliedPeriodSnapshot = message.text();
    });
    await page.getByRole('link', { name: '7 дней', exact: true }).evaluate(link => {
      link.addEventListener('click', () => console.log('brief-applied-period:' + document.querySelector('.brief-period').innerText));
    });
    const gate = new Promise(resolve => { release = resolve; });
    const requestSeen = new Promise(resolve => { entered = resolve; });
    await page.route('**/brief?preset=7*', async route => { entered(); await gate; await route.continue(); });
    const navigation = page.waitForURL('**/brief?preset=7*');
    const click = page.getByRole('link', { name: '7 дней', exact: true }).click({ noWaitAfter: true });
    await requestSeen;
    assert.match(appliedPeriodSnapshot, /2099-01-01 → 2099-01-07/);
    assert.match(page.url(), /start_date=2099-01-01/);
    release();
    await Promise.all([click, navigation]);
    assert.match(page.url(), /garmin_source_id=synthetic-one/);
    assert.match(await page.locator('.brief-period').innerText(), /7 дней/);
    assert.equal(await page.locator('.brief-empty-state').isVisible(), true);
    assert.doesNotMatch(await page.locator('main').innerText(), /-120 с/);
    checks.push('Delayed period navigation preserves applied context; new empty period clears previous comparisons');

    const error = await page.goto(base + '/brief?preset=invalid');
    assert.equal(error.status(), 400);
    assert.equal(await page.getByRole('alert').isVisible(), true);
    assert.doesNotMatch(await page.locator('main').innerText(), /-120 с|request failed/);
    assert.equal(errors.length, 0, errors.join('\n'));
    checks.push('Invalid period shows the shared Russian request error without stale success or JavaScript errors');
    fs.mkdirSync(evidence, { recursive: true });
    fs.writeFileSync(path.join(evidence, 'brief-stage3-browser.json'), JSON.stringify({ checks, errors }, null, 2));
    console.log(JSON.stringify({ checks, errors }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
