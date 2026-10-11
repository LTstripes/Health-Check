/* Existing /brief RHR card, external synthetic profile, no external requests. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const fixture = JSON.parse(fs.readFileSync(process.env.HEALTHCHECK_RHR_FIXTURE, 'utf8'));
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
      for (const [name, dates, state, value] of [
        ['latest', null, 'last_eligible', '58 уд/мин'],
        ['zero', '02', 'exact', '0 уд/мин'],
        ['missing', '10', 'no_eligible_in_search', null],
        ['conflict', '09', 'ambiguous', null],
        ['cap', '01', 'search_incomplete', null],
        ['empty', '04', 'no_eligible_in_search', null],
      ]) {
        const params = new URLSearchParams(fixture);
        params.delete('evaluation_local_date');
        if (dates) { params.set('start_date', `2099-01-${dates}`); params.set('end_date', `2099-01-${dates}`); }
        assert.equal((await page.goto(`${base}/brief?${params}`)).status(), 200);
        const card = page.locator('[data-overview-rhr]');
        assert.equal(await card.count(), 1);
        const garmin = card.locator('[data-rhr-provider="Garmin"]');
        assert.equal(await garmin.getAttribute('data-rhr-state'), state);
        assert.equal(await garmin.locator('strong').count(), value ? 1 : 0);
        if (value) assert.equal(await garmin.locator('strong').innerText(), value);
        if (name === 'latest') assert.match(await garmin.innerText(), /5 дней назад/);
        if (name === 'zero') assert.match(await garmin.innerText(), /явный ноль/);
        if (name === 'cap') assert.match(await garmin.innerText(), /Поиск не завершён/);
        if (name === 'empty') assert.match(await garmin.innerText(), /не подтверждает.*никогда/);
        const disclosure = garmin.locator('[data-rhr-evidence]');
        await disclosure.locator('summary').focus(); await page.keyboard.press('Enter');
        assert.equal(await disclosure.locator('p').first().isVisible(), true);
        assert.match(await disclosure.innerText(), /дата снимка: неизвестна/);
        await page.keyboard.press('Space');
        assert.equal(await disclosure.getAttribute('open'), null);
        const dto = JSON.parse(await page.locator('[data-rhr-dto]').textContent());
        assert.equal(dto.items[0].dto.state, state);
        assert.equal(dto.items[0].dto.query.mode, dates ? 'explicit_period' : 'default_latest');
        if (name === 'latest') {
          assert.equal(dto.items[0].dto.newer_exclusions.length, 2);
          assert.equal(dto.items[0].dto.newer_exclusions[1].record_ids.length, 2);
        }
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        await card.screenshot({ path: path.join(evidence, `${name}-${width}.png`) });
        checks.push({ width, name, state });
      }
      await page.goto(`${base}/brief?garmin_source_id=${fixture.garmin_source_id}`);
      const google = page.locator('[data-overview-rhr] [data-rhr-provider="Google"]');
      assert.equal(await google.getAttribute('data-rhr-state'), 'ambiguous');
      await google.locator('select').selectOption(fixture.google_rhr_source_id);
      await google.locator('button').click();
      assert.equal(await google.getAttribute('data-rhr-state'), 'last_eligible');
      assert.ok(new URL(page.url()).searchParams.has('google_rhr_source_id'));
      await page.locator('.preset-links a').first().click();
      assert.equal(new URL(page.url()).searchParams.get('google_rhr_source_id'), fixture.google_rhr_source_id);
      assert.equal(await page.locator('[data-overview-rhr]').getAttribute('data-rhr-mode'), 'explicit_period');
      checks.push({ width, name: 'google-choice-period-preserved' });
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const result = { sha: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
      browser: browser.version(), fixture, checks, errors, external };
    fs.writeFileSync(path.join(evidence, 'rhr-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({ sha: result.sha, browser: result.browser, cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
