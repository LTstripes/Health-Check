/* Numeric correction only: accepted finite extremes in real session list/detail. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HEALTHCHECK_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const candidate = process.env.HEALTHCHECK_CANDIDATE_SHA;
const identity = JSON.parse(fs.readFileSync(process.env.HEALTHCHECK_BROWSER_IDENTITY, 'utf8'));
assert.equal(identity.candidate, candidate); assert.equal(identity.extreme_sessions, true);
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE});
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, {recursive: true});
    for (const width of [1024, 1440]) {
      const page = await browser.newPage({viewport: {width, height: 1000}});
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() :
        (external.push(route.request().url()), route.abort()));
      async function capture(name) {
        await page.evaluate(() => window.scrollTo(0, 0));
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        await page.screenshot({path: path.join(evidence, `${name}-${width}.png`), fullPage: true});
      }
      const params = new URLSearchParams({garmin_source_id: identity.source_id, start_date: identity.start,
        end_date: identity.end, metric_code: 'activity_session_count', sport: 'all'});
      const listURL = `${base}/statistics/sessions?${params}`;
      assert.equal((await page.goto(listURL)).status(), 200);
      assert.equal(await page.locator('[data-session-record]').count(), 5);
      const cells = await page.locator('[data-session-metric]').allTextContents();
      for (const text of ['≈2,78 × 10^22 ч', '≈1 × 10^27 км', '≈4,99 × 10^304 ч',
        '≈1,8 × 10^305 км', '<1 мин', '<0,01 км', '0 мин', '0 км', 'Источник передал null']) assert.ok(cells.includes(text), text);
      await capture('extreme-list');
      const links = await page.locator('tbody a').evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
      let extreme = 0, largest = 0, tiny = 0;
      for (const href of links) {
        assert.equal((await page.goto(new URL(href, base).href)).status(), 200);
        const raw = JSON.parse(await page.locator('#activity-session-evidence').textContent());
        const duration = raw.metric_coverage.find(item => item.metric_code === 'duration_seconds');
        const distance = raw.metric_coverage.find(item => item.metric_code === 'distance_meters');
        const shown = await page.locator('.activity-detail-grid').innerText();
        assert.equal(duration.unit, 'seconds'); assert.equal(distance.unit, 'meters');
        if (duration.value === 1e26) {
          assert.equal(distance.value, 1e30); assert.ok(shown.includes('≈2,78 × 10^22 ч'));
          assert.ok(shown.includes('≈1 × 10^27 км')); await capture('extreme-detail'); extreme++;
        } else if (duration.value === Number.MAX_VALUE) {
          assert.equal(distance.value, Number.MAX_VALUE); assert.ok(shown.includes('≈4,99 × 10^304 ч'));
          assert.ok(shown.includes('≈1,8 × 10^305 км')); await capture('max-finite-detail'); largest++;
        } else if (duration.value === Number.MIN_VALUE) {
          assert.equal(distance.value, Number.MIN_VALUE); assert.ok(shown.includes('<1 мин'));
          assert.ok(shown.includes('<0,01 км')); await capture('min-positive-detail'); tiny++;
        }
        await page.goBack(); assert.equal(page.url(), listURL);
      }
      assert.equal(extreme, 1); assert.equal(largest, 1); assert.equal(tiny, 1);
      checks.push({width, listAndDetail: true, finiteExtremes: true, exactRawValues: true,
        noFabricatedZero: true, browserBack: true, overflow: false});
      await page.close();
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const result = {candidate, identity, checks, errors, external, checkedAt: new Date().toISOString()};
    fs.writeFileSync(path.join(evidence, 'browser-results.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exit(1);});
