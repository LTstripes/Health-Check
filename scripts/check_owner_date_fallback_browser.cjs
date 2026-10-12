/* Affected Data presentation only: missing versus supplied-invalid date labels. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {cases} = require('./check_owner_dates.cjs');
const base = process.env.HEALTHCHECK_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const candidate = process.env.HEALTHCHECK_CANDIDATE_SHA;
const identity = JSON.parse(fs.readFileSync(process.env.HEALTHCHECK_BROWSER_IDENTITY, 'utf8'));
assert.equal(identity.candidate, candidate);
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE});
  const errors = [], external = [], checks = [];
  try {
    fs.mkdirSync(evidence, {recursive: true});
    for (const width of [1024, 1440]) {
      const page = await browser.newPage({viewport: {width, height: 1000}, timezoneId: 'Pacific/Pago_Pago'});
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() :
        (external.push(route.request().url()), route.abort()));
      assert.equal((await page.goto(`${base}/imports`)).status(), 200);
      await page.waitForFunction(() => !document.querySelector('#data-refresh').disabled);
      const matrix = await page.evaluate(cases => cases.map(test =>
        ({...test, actual: window.healthcheckOwnerDate(test.value, test.sourcePrecision)})), cases);
      for (const test of matrix) assert.equal(test.actual, test.expected, JSON.stringify(test.value));
      const missing = await page.evaluate(() => [undefined, null, ''].map(value => window.healthcheckOwnerDate(value)));
      assert.deepEqual(missing, ['Дата не указана', 'Дата не указана', 'Дата не указана']);
      await page.route('**/api/source-freshness?**', async route => {
        const response = await route.fetch();
        const payload = await response.json();
        payload.evaluated_at_utc = '2026-01-02T25:61:70+99:99';
        payload.evaluation_local_date = '2026-01-00';
        for (const item of payload.components) {
          item.facts.last_successful_refresh_utc = null;
          item.facts.latest_evidence_local_date = '2026-02-30';
        }
        await route.fulfill({response, json: payload});
      });
      await page.getByRole('button', {name: 'Проверить состояние', exact: true}).click();
      await page.waitForFunction(() => document.querySelector('#data-clock').textContent.includes('Некорректная дата/время'));
      const clock = await page.locator('#data-clock').innerText();
      assert.ok(!clock.includes('Дата не указана'));
      const rows = await page.locator('.data-chronology').allTextContents();
      assert.ok(rows.length > 0);
      for (const row of rows) {
        assert.ok(row.includes('Неизвестно')); // Existing consumer label for absent chronology.
        assert.ok(row.includes('Некорректная дата/время'));
        assert.ok(!row.includes('30 февраля') && !row.includes('Дата не указана'));
      }
      const raw = page.locator('#data-results pre');
      for (const value of ['2026-02-30', '2026-01-00', '2026-01-02T25:61:70+99:99']) assert.ok((await raw.textContent()).includes(value));
      const summary = raw.locator('..').locator('summary');
      await summary.focus(); await page.keyboard.press('Enter');
      assert.equal(await raw.isVisible(), true);
      await page.keyboard.press('Enter');
      await page.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({path: path.join(evidence, `data-missing-invalid-${width}.png`), fullPage: true});
      checks.push({width, cases: matrix.length, missingDistinct: true, invalidLabel: true,
        rawPreserved: true, keyboardDisclosure: true, overflow: false});
      await page.close();
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const result = {candidate, identity, checks, errors, external, checkedAt: new Date().toISOString()};
    fs.writeFileSync(path.join(evidence, 'browser-results.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exit(1);});
