/* #379/#378 exact-candidate synthetic desktop presentation and navigation. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { cases: civilCases } = require('./check_owner_dates.cjs');
const base = process.env.HEALTHCHECK_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const identity = JSON.parse(fs.readFileSync(process.env.HEALTHCHECK_BROWSER_IDENTITY, 'utf8'));
const candidate = process.env.HEALTHCHECK_CANDIDATE_SHA;
assert.match(candidate, /^[a-f0-9]{40}$/);
assert.equal(identity.candidate, candidate);
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1024, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, timezoneId: 'Pacific/Pago_Pago' });
      page.on('pageerror', e => errors.push(e.message));
      await page.route('**/*', route => {
        if (new URL(route.request().url()).origin !== base) {
          external.push(route.request().url()); return route.abort();
        }
        return route.continue();
      });
      async function capture(name) {
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        await page.screenshot({ path: path.join(evidence, `${name}-${width}.png`), fullPage: true });
      }
      assert.equal((await page.goto(`${base}/context?from_date=2026-01-01&to_date=2099-12-31`)).status(), 200);
      const headings = await page.locator('.context-note h3').allTextContents();
      assert.equal(headings.length, 4);
      assert.ok(headings.some(h => h.includes('2 января 2099, 00:15 UTC+1400')));
      assert.ok(headings.some(h => h.includes('19:30:10.123400 UTC+0300')));
      assert.ok(headings.some(h => h.includes('8 марта 2026, 01:30 UTC-0500') && h.includes('03:30 UTC-0400')));
      const dateOnly = headings.find(h => h === 'Событие: 2 января 2099');
      assert.ok(dateOnly);
      assert.ok(headings.every(h => !h.includes("2099-01-02")));
      await capture('comments-list');
      await page.goto(`${base}/context/${identity.comments[2]}?history=1`);
      assert.equal(await page.locator('.context-note').count(), 3);
      for (const h of await page.locator('.context-note h3').allTextContents()) assert.ok(h.includes('19:30:10.123400 UTC+0300'));
      const disclosure = page.locator('.context-time-details').first();
      await disclosure.locator('summary').focus();
      await page.keyboard.press('Enter');
      assert.equal(await disclosure.getAttribute('open'), '');
      assert.ok((await disclosure.innerText()).includes('2099-01-02T19:30:10.123400+03:00'));
      assert.ok((await page.locator('.context-note').first().innerText()).includes('Europe/Moscow'));
      await capture('comments-detail-history');
      const helperCases = await page.evaluate(() => [
        window.healthcheckOwnerDate('2024-02-29'),
        window.healthcheckOwnerDate('2099-01-02T00:15+14:00', true),
        window.healthcheckOwnerDate('2099-01-02T19:30:10.123400+03:00', true),
      ]);
      assert.deepEqual(helperCases, ['29 февраля 2024', '2 января 2099, 00:15 UTC+14:00', '2 января 2099, 19:30:10.123400 UTC+03:00']);
      const civilResults = await page.evaluate(cases => cases.map(test => ({
        ...test, actual: window.healthcheckOwnerDate(test.value, test.sourcePrecision),
      })), civilCases);
      for (const test of civilResults) assert.equal(test.actual, test.expected, JSON.stringify(test.value));
      const selected = new URLSearchParams({ period: '7', end_date: identity.end,
        calendar_year: '2099', garmin_source_id: identity.source_id });
      const statisticsURL = `${base}/statistics?${selected}`;
      assert.equal((await page.goto(statisticsURL)).status(), 200);
      assert.ok((await page.locator('.statistics-window').innerText()).includes('2 января 2099 — 8 января 2099'));
      await capture('statistics');
      const link = page.locator('[data-session-drilldown="activity_session_count"]');
      await link.focus();
      assert.equal(await link.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
      await Promise.all([page.waitForURL(/\/statistics\/sessions\?/), page.keyboard.press('Enter')]);
      const sessionsURL = page.url();
      assert.equal(await page.locator('[data-session-record]').count(), 4);
      const cells = await page.locator('[data-session-metric]').allTextContents();
      for (const text of ['1 ч 5 мин 1,5 с', '12,35 км', '<0,01 с', '<0,01 км', '0 мин', '0 км', 'Источник передал null']) assert.ok(cells.includes(text), text);
      assert.ok(!(await page.locator('thead').innerText()).includes('Длительность, с'));
      await capture('sessions');
      const detailLinks = await page.locator('tbody a').evaluateAll(nodes => nodes.map(n => n.getAttribute('href')));
      for (let index = 0; index < detailLinks.length; index++) {
        const params = new URL(detailLinks[index], base).searchParams;
        assert.ok(identity.records.includes(params.get('record_id')));
        assert.equal(params.get('garmin_source_id'), identity.source_id);
        await page.goto(new URL(detailLinks[index], base).href);
        const detailText = await page.locator('.activity-detail-grid').innerText();
        const raw = await page.locator('#activity-session-evidence').textContent();
        assert.ok(raw.includes(params.get('record_id')));
        if (raw.includes('3901.5')) {
          assert.ok(detailText.includes('1 ч 5 мин 1,5 с'));
          assert.ok(detailText.includes('12,35 км'));
          await capture('activity-detail');
        } else if (raw.includes('0.001')) {
          assert.ok(detailText.includes('<0,01 с'));
          assert.ok(detailText.includes('<0,01 км'));
          await capture('activity-tiny');
        }
        await page.goBack();
        assert.equal(page.url(), sessionsURL);
      }
      await page.getByRole('combobox', { name: 'Вид активности' }).selectOption('cycling');
      await page.getByRole('button', { name: 'Показать', exact: true }).click();
      const filteredURL = page.url();
      assert.equal(await page.locator('[data-session-record]').count(), 1);
      const first = page.locator('tbody a').first();
      await page.locator('.table-scroll').focus();
      await page.keyboard.press('Tab');
      assert.equal(await first.evaluate(el => document.activeElement === el), true);
      await Promise.all([page.waitForURL(/\/garmin\/session\?/), page.keyboard.press('Enter')]);
      assert.ok((await page.locator('.activity-detail-grid').innerText()).includes('0 км'));
      await capture('activity-zero');
      await page.goBack();
      assert.equal(page.url(), filteredURL);
      assert.equal(await page.getByRole('combobox', { name: 'Вид активности' }).inputValue(), 'cycling');
      await page.locator('[data-statistics-return]').click();
      for (const [key, value] of selected) assert.equal(new URL(page.url()).searchParams.get(key), value);
      selected.set('garmin_source_id', identity.steps_source_id);
      await page.goto(`${base}/statistics?${selected}`);
      assert.ok((await page.locator('[data-statistics-steps] caption').innerText()).includes('2 января 2099 — 8 января 2099'));
      const step = page.locator('[data-steps-date="2099-01-02"]');
      assert.equal(await step.locator('time').innerText(), '2 января 2099');
      assert.equal(await step.locator('time').getAttribute('datetime'), '2099-01-02');
      assert.equal(await page.locator('[data-steps-date="2099-01-03"] .statistics-steps-value').innerText(), '0');
      assert.equal(await page.locator('[data-steps-date="2099-01-04"] .statistics-steps-value').innerText(), 'Недоступно');
      await capture('steps');
      await page.goto(`${base}/garmin?garmin_source_id=${identity.source_id}`);
      await capture('activity-journal');
      await page.goto(`${base}/?end_date=2099-01-08`);
      await page.waitForSelector('#weight-chart .weight-point');
      await page.locator('#weight-chart .weight-point').first().focus();
      assert.match(await page.locator('#observation-detail h3').innerText(), /\d{1,2} [а-я]+.? \d{4}/);
      assert.ok(!(await page.locator('#observation-detail h3').innerText()).includes('2099-01-'));
      await capture('weight');
      await page.goto(`${base}/brief`);
      const titles = await page.locator('svg title').allTextContents();
      assert.ok(titles.length > 0);
      assert.ok(titles.every(t => !/\d{4}-\d{2}-\d{2}/.test(t)));
      await capture('overview');
      await page.goto(`${base}/imports`);
      await page.waitForFunction(() => !document.querySelector('#data-refresh').disabled);
      assert.match(await page.locator('#data-clock').innerText(), /\d{1,2} [а-я]+ \d{4}/);
      await capture('data');
      // Synthetic response-only invalid dates exercise the actual Data consumer.
      await page.route('**/api/source-freshness?**', async route => {
        const response = await route.fetch();
        const payload = await response.json();
        payload.evaluated_at_utc = '2026-01-02T25:61:70+99:99';
        payload.evaluation_local_date = '2026-01-00';
        for (const item of payload.components) {
          item.facts.last_successful_refresh_utc = '2026-01-02T25:61:70+99:99';
          item.facts.latest_evidence_local_date = '2026-02-30';
        }
        await route.fulfill({response, json: payload});
      });
      await page.getByRole('button', {name: 'Проверить состояние', exact: true}).click();
      await page.waitForFunction(() => document.querySelector('#data-clock').textContent.includes('Дата не указана'));
      const chronology = await page.locator('.data-chronology').allTextContents();
      assert.ok(chronology.length > 0);
      for (const text of chronology) {
        assert.ok(text.includes('Дата не указана'));
        assert.ok(!text.includes('30 февраля') && !text.includes('0 января') && !text.includes('25:61'));
      }
      const rawFacts = await page.locator('#data-results pre').innerText();
      for (const value of ['2026-02-30', '2026-01-00', '2026-01-02T25:61:70+99:99']) assert.ok(rawFacts.includes(value));
      await capture('data-invalid');
      await page.locator('#completed-imports summary').click();
      await page.locator('#completed-imports a').first().click();
      assert.match(await page.locator('.temporal-evidence').first().innerText(), /\d{1,2} [а-я]+ \d{4}/);
      await page.locator('.candidate-select').first().check();
      assert.match(await page.locator('#commit-preview').innerText(), /\d{1,2} [а-я]+ \d{4}/);
      assert.ok(!/\d{4}-\d{2}-\d{2}/.test(await page.locator('#commit-preview').innerText()));
      await capture('import-review');
      checks.push({ width, sessionsURL, filteredURL, keyboard: true, browserBack: true,
        overflow: false, sourceLocalDates: true, nativeEvidence: true, stepsZeroMissing: true, civilValidationCases: civilResults.length,
        invalidChronologyUnavailable: true, invalidRawPreserved: true });
      await page.close();
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    fs.writeFileSync(path.join(evidence, 'browser-results.json'), JSON.stringify({
      candidate, checks, errors, external, identity, checkedAt: new Date().toISOString(),
    }, null, 2));
    console.log(JSON.stringify({ candidate, checks, errors, external }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
