/* #293: real Chromium interaction against an explicit synthetic loopback UI.
 * NODE_PATH exposes Playwright. Set HEALTHCHECK_BROWSER_BASE_URL and
 * HEALTHCHECK_BROWSER_EVIDENCE_DIR. The server fixture has confirmed weight
 * plus same-session composition; negative render cases replace only page JSON.
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
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ? { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [];
  const errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', msg => { if (msg.type() === 'error' && !(msg.location().url || '').endsWith('/favicon.ico')) errors.push(msg.text()); });
    await page.goto(base + '/');
    const original = await page.locator('#dashboard-data').textContent();
    const payload = JSON.parse(original);
    const raw = payload.series.raw_points;
    const compositions = Object.values(payload.series.composition_by_group).flat();
    assert.ok(raw.length > 1 && compositions.length > 1, 'multi-observation synthetic fixture required');
    const chartPoints = page.locator('#weight-chart [data-series="raw"]');
    assert.equal(await chartPoints.count(), raw.length);
    assert.equal(await page.locator('#weight-chart [data-axis="y"]').count(), 5);
    assert.equal(await page.locator('#weight-chart [data-axis="x"]').count(), 2);
    assert.equal(await page.locator('.bia-banner,.algorithm-banner,#composition-latest').count(), 0);
    assert.doesNotMatch(await page.locator('.hero').innerText(), /Нет кандидатов|Проверка импорта/);
    assert.equal(await page.locator('.owner-details').getAttribute('open'), null);
    const first = raw[0];
    const matched = compositions.filter(point => point.weight_measurement_id === first.evidence_id);
    assert.ok(matched.length);
    await chartPoints.first().hover();
    assert.match(await page.locator('#observation-detail').innerText(), new RegExp(first.observed_date));
    const hoverDetail = await page.locator('#observation-detail').innerText();
    await chartPoints.first().focus();
    assert.equal(await page.locator('#observation-detail').innerText(), hoverDetail);
    for (const label of ['Вес', 'Жир (источник)', 'Оценка жировой массы (Health-Check)', 'Оценка сухой массы (Health-Check)', 'Мышцы (источник, отдельная оценка)']) {
      assert.ok(hoverDetail.includes(label), label);
    }
    assert.ok(hoverDetail.includes(Number(matched[0].estimated_lean_mass_kg).toFixed(1)));
    await page.keyboard.press('ArrowRight');
    assert.equal(await chartPoints.nth(1).evaluate(el => el === document.activeElement), true);
    assert.ok((await page.locator('#observation-detail').innerText()).includes(raw[1].observed_date));
    await page.keyboard.press('Space');
    checks.push('Real payload: numeric axes; identical mouse/focus detail; arrow/Space controls; exact same-session values/origins');
    const select = page.locator('#composition-groups select').first();
    for (const key of ['estimated_fat_mass_kg', 'estimated_lean_mass_kg', 'source_muscle_mass_kg', 'body_fat_pct']) {
      await select.selectOption(key);
      const point = page.locator('#composition-groups [data-series="raw"]').first();
      await point.focus();
      assert.ok((await page.locator('#composition-detail-0').innerText()).includes('Мышцы (источник, отдельная оценка)'));
      assert.equal(await point.getAttribute('aria-controls'), 'composition-detail-0');
    }
    const tech = page.locator('.owner-details');
    await tech.locator('summary').focus();
    await page.keyboard.press('Enter');
    assert.equal(await tech.getAttribute('open'), '');
    assert.match(await tech.innerText(), /Покрытие и свежесть|weight_trend_taewma_v1/);
    await page.keyboard.press('Enter');
    assert.equal(await tech.getAttribute('open'), null);
    checks.push('Composition metric switch and local keyboard detail; closed technical disclosure opens/closes via Enter');
    fs.mkdirSync(evidence, { recursive: true });
    const geometry = [];
    for (const width of [1100, 800, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await chartPoints.first().focus();
      const dimensions = await page.evaluate(() => {
        const chart = document.querySelector('#weight-chart');
        const summary = document.querySelector('.weight-caveat summary');
        return { width: innerWidth, document: document.documentElement.scrollWidth,
          chartWidth: chart.clientWidth, chartScrollWidth: chart.scrollWidth,
          overflow: getComputedStyle(chart).overflowX, summaryHeight: summary.getBoundingClientRect().height };
      });
      assert.ok(dimensions.document <= width + 1, JSON.stringify(dimensions));
      assert.equal(dimensions.overflow, 'auto');
      assert.ok(dimensions.summaryHeight >= 44);
      if (width === 390) {
        assert.ok(dimensions.chartScrollWidth > dimensions.chartWidth);
        await page.locator('#weight-chart').evaluate(el => { el.scrollLeft = el.scrollWidth; });
        assert.ok(await page.locator('#weight-chart').evaluate(el => el.scrollLeft > 0));
      }
      geometry.push(dimensions);
      await page.locator('#weight-chart').evaluate(el => { el.scrollLeft = 0; });
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(evidence, 'weight-v2-' + width + '.png'), fullPage: true });
    }
    checks.push('1100/800/390px: no page overflow; chart scroll works; keyboard detail and 44px disclosure usable');
    // Synthetic negative cases execute the same production renderer in Chromium.
    async function renderCase(series) {
      await page.route(base + '/', async route => {
        const response = await route.fetch();
        const html = await response.text();
        const edited = JSON.stringify({ ...payload, series }).replace(/</g, '\\u003c');
        await route.fulfill({ response, body: html.replace(original, edited) });
      });
      await page.goto(base + '/');
      await page.unroute(base + '/');
    }
    const sameDate = { ...first, evidence_id: 'synthetic-unmatched', value_kg: 83.7 };
    await renderCase({ ...payload.series, raw_points: [sameDate], trend_points: [], goal_kg: null });
    await page.locator('#weight-chart [data-series="raw"]').focus();
    assert.match(await page.locator('#observation-detail').innerText(), /83\.7 кг|Состав тела для этого наблюдения недоступен/);
    assert.ok((await page.locator('#observation-detail').innerText()).includes('Состав тела для этого наблюдения недоступен'));
    assert.doesNotMatch(await page.locator('#observation-detail').innerText(), /Оценка сухой массы/);
    assert.equal(await page.locator('#weight-chart [data-series="goal"]').count(), 0);
    const zero = { ...compositions[0], weight_measurement_id: sameDate.evidence_id,
      body_fat_pct: 0, estimated_fat_mass_kg: null, estimated_lean_mass_kg: null, source_muscle_mass_kg: null };
    await renderCase({ ...payload.series, raw_points: [sameDate], trend_points: [],
      composition_by_group: { 'synthetic-private-group': [zero] } });
    assert.match(await page.locator('#observation-detail').innerText(), /0\.0%/);
    assert.match(await page.locator('#observation-detail').innerText(), /недоступно/);
    assert.doesNotMatch(await page.locator('#composition-groups').innerText(), /synthetic-private-group/);
    await page.locator('#composition-groups select').selectOption('source_muscle_mass_kg');
    assert.match(await page.locator('#composition-groups').innerText(), /Нет подтверждённых значений этого показателя/);
    await renderCase({ ...payload.series, raw_points: [sameDate], trend_points: [],
      composition_by_group: { 'synthetic-A': [zero], 'synthetic-B': [{ ...zero, body_fat_pct: 21 }] } });
    assert.equal(await page.locator('#composition-groups select').count(), 2);
    assert.doesNotMatch(await page.locator('#composition-groups').innerText(), /synthetic-A|synthetic-B/);
    await renderCase({ ...payload.series, raw_points: [], trend_points: [], composition_by_group: {}, trend_available: false, trend_reason: 'no_data' });
    assert.equal(await page.locator('#weight-chart svg').count(), 0);
    assert.match(await page.locator('#weight-chart').innerText(), /Это не означает ноль/);
    checks.push('Negative render fixtures: same-date unmatched evidence never borrows composition; explicit zero distinct from missing; single point axes; groups separate; empty state honest');
    assert.deepEqual(errors, []);
    const result = { status: 'PASS', browser: browser.version(), checks, geometry, errors };
    fs.writeFileSync(path.join(evidence, 'weight-v2-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
