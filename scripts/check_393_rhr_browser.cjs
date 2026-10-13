/* Real /brief routes with external synthetic storage; no external requests. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const fixture = JSON.parse(fs.readFileSync(process.env.HEALTHCHECK_RHR_FIXTURE, 'utf8'));
assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
assert.ok(evidence);
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE });
  const checks = [], errors = [], external = [], images = [];
  const git = args => execFileSync('git', args, { encoding: 'utf8' }).trim();
  const sha = git(['rev-parse', 'HEAD']), tree = git(['rev-parse', 'HEAD^{tree}']);
  assert.equal(git(['status', '--porcelain']), '', 'Browser evidence needs committed clean source');
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
    async function screenshot(locator, name) {
      const file = path.join(evidence, name);
      await locator.screenshot({ path: file });
      images.push({ file: name, sha256: crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') });
    }
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const [name, start, end, state, value, n, N] of [
        ['default', null, null, 'observed', 59, 4, 30],
        ['half', '2099-01-02', '2099-01-04', 'observed', 57, 2, 3],
        ['recurring', '2099-01-04', '2099-01-07', 'observed', 61, 3, 4],
        ['single', '2099-01-04', '2099-01-04', 'observed', 61, 1, 1],
        ['zero', '2098-12-02', '2098-12-02', 'observed', 0, 1, 1],
        ['missing', '2099-01-10', '2099-01-10', 'no_eligible_in_period', null, 0, 1],
        ['conflict', '2099-01-09', '2099-01-09', 'no_eligible_in_period', null, 0, 1],
        ['cap', '2099-01-20', '2099-01-20', 'search_incomplete', null, null, 1],
        ['empty', '2099-01-06', '2099-01-06', 'no_eligible_in_period', null, 0, 1],
        ['400', '2097-12-06', '2099-01-09', 'observed', 47, 5, 400],
        ['401', '2097-12-05', '2099-01-09', 'period_too_long', null, null, 401],
      ]) {
        const params = new URLSearchParams(fixture);
        params.delete('evaluation_local_date');
        if (start) { params.set('start_date', start); params.set('end_date', end); }
        assert.equal((await page.goto(`${base}/brief?${params}`)).status(), 200);
        const card = page.locator('[data-overview-rhr]');
        assert.equal(await card.count(), 1);
        const garmin = card.locator('[data-rhr-provider="Garmin"]');
        assert.equal(await garmin.getAttribute('data-rhr-state'), state);
        assert.equal(await garmin.locator('strong').count(), value === null ? 0 : 1);
        if (value !== null) assert.equal(await garmin.locator('strong').innerText(), `Средний пульс в покое · ${value} уд/мин`);
        if (n !== null) assert.match(await garmin.innerText(), new RegExp(`по ${n} из ${N} дней`));
        if (n === 1) assert.match(await garmin.innerText(), /одно наблюдение/);
        if (name === '401') assert.match(await garmin.innerText(), /Сузь период до 400 календарных дней включительно/);
        const dto = JSON.parse(await page.locator('[data-rhr-dto]').textContent()).items[0].dto;
        assert.equal(dto.state, state);
        assert.equal(dto.mean_display, value);
        assert.equal(dto.eligible_day_count, n);
        assert.equal(dto.requested_day_count, N);
        if (start) {
          assert.equal(dto.query.requested_start_date, start);
          assert.equal(dto.query.requested_end_date, end);
        }
        const disclosure = garmin.locator('[data-rhr-evidence]');
        assert.equal(await disclosure.getAttribute('open'), null);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        await screenshot(card, `${name}-${width}.png`);
        if (name === 'default') await screenshot(page, `overview-${width}.png`);
        await disclosure.locator('summary').focus(); await page.keyboard.press('Enter');
        assert.equal(await disclosure.locator('p').first().isVisible(), true);
        assert.match(await disclosure.innerText(), /не доказывает типичный пульс или полноту ношения/);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        if (name === 'half') {
          assert.match(await disclosure.innerText(), /56.5 уд\/мин; точное значение 113 \/ 2/);
          await screenshot(card, `details-${width}.png`);
        }
        await disclosure.locator('summary').focus(); await page.keyboard.press('Space');
        assert.equal(await disclosure.getAttribute('open'), null);
        checks.push({ width, name, state, value, n, N });
      }
      await page.goto(`${base}/brief?start_date=2099-01-02&end_date=2099-01-04&garmin_source_id=${fixture.garmin_source_id}`);
      const google = page.locator('[data-overview-rhr] [data-rhr-provider="Google"]');
      assert.equal(await google.getAttribute('data-rhr-state'), 'ambiguous');
      await google.locator('select').selectOption(fixture.google_rhr_source_id);
      await google.locator('button').click();
      const current = new URL(page.url()).searchParams;
      assert.equal(current.get('start_date'), '2099-01-02');
      assert.equal(current.get('end_date'), '2099-01-04');
      assert.equal(current.get('garmin_source_id'), fixture.garmin_source_id);
      assert.equal(current.get('google_rhr_source_id'), fixture.google_rhr_source_id);
      assert.equal(await google.getAttribute('data-rhr-state'), 'observed');
      await page.locator('.preset-links a').first().click();
      assert.equal(new URL(page.url()).searchParams.get('google_rhr_source_id'), fixture.google_rhr_source_id);
      checks.push({ width, name: 'exact-google-choice-period-preserved' });
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const result = { sha, tree, browser: browser.version(), fixture, checks, images, errors, external };
    fs.writeFileSync(path.join(evidence, 'rhr-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({ sha, tree, browser: result.browser, cases: checks.length, images: images.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
