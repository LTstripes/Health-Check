/* #318: production /garmin + --activity-comparison synthetic persisted fixture.
 * Response overrides below exercise presentation states; no provider traffic.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
assert.ok(evidence);
const git = args => execFileSync('git', args, { cwd: path.join(__dirname, '..'), encoding: 'utf8' }).trim();
const identity = () => ({ sha: git(['rev-parse', 'HEAD']), tree: git(['rev-parse', 'HEAD^{tree}']),
  trackedChanges: git(['diff', '--name-only', 'HEAD']), untracked: git(['ls-files', '--others', '--exclude-standard']) });
const candidate = identity();
const endpoint = '**/api/garmin/activity-comparison?**';
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ? { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], external = [], layouts = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    const page = await browser.newPage();
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin !== base) {
        external.push(route.request().url()); return route.abort();
      }
      return route.continue();
    });
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {
      if (m.type() === 'error' && !(m.location().url || '').endsWith('/favicon.ico') &&
          !m.text().includes('503 (Service Unavailable)')) errors.push(m.text());
    });
    const row = code => page.locator(`#activity-result tr[data-metric-code="${code}"]`);
    const cells = code => row(code).locator('td').allTextContents();
    const submit = async () => {
      const response = page.waitForResponse(r => r.url().includes('/api/garmin/activity-comparison?'));
      await page.locator('#activity-form button').focus();
      await page.keyboard.press('Enter');
      const body = await (await response).json();
      await page.waitForFunction(() => document.querySelector('#activity-result').getAttribute('aria-busy') === 'false');
      return body;
    };
    async function layout(width) {
      const geometry = await page.evaluate(() => {
        const scroller = document.querySelector('#activity-result .table-scroll');
        const table = scroller.querySelector('table');
        return { view: innerWidth, page: document.documentElement.scrollWidth,
          scroller: scroller.clientWidth, scrollWidth: scroller.scrollWidth,
          table: table.getBoundingClientRect().width,
          minWidth: getComputedStyle(table).minWidth, layout: getComputedStyle(table).tableLayout,
          background: getComputedStyle(document.body).backgroundColor,
          selectColumns: getComputedStyle(document.querySelector('#activity-form')).gridTemplateColumns.split(' ').length,
          targets: [...document.querySelectorAll('#activity-form button, #activity-form select, .activity-comparison summary')]
            .map(el => el.getBoundingClientRect().height) };
      });
      assert.equal(geometry.view, width);
      assert.ok(geometry.page <= width + 1, JSON.stringify(geometry));
      assert.ok(geometry.scrollWidth <= geometry.scroller + 1, JSON.stringify(geometry));
      assert.equal(geometry.minWidth, '0px');
      assert.equal(geometry.layout, 'fixed');
      assert.equal(geometry.background, 'rgb(246, 242, 233)');
      assert.equal(geometry.selectColumns, 3);
      assert.ok(geometry.targets.every(h => h >= 44));
      if (!layouts.some(saved => JSON.stringify(saved) === JSON.stringify(geometry))) layouts.push(geometry);
    }
    let original, ids;
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal((await page.goto(base + '/garmin')).status(), 200);
      ids = await page.locator('#activity-a option').evaluateAll(options => options.map(o => o.value).filter(Boolean));
      assert.equal(ids.length, 2);
      assert.match(await page.locator('#activity-a').innerText(), /Теннис/);
      assert.equal(await page.locator('#activity-form button').isDisabled(), true);
      await page.locator('#activity-a').selectOption(ids[0]);
      await page.locator('#activity-b').selectOption(ids[0]);
      assert.match(await page.locator('#activity-selection-hint').innerText(), /одна и та же/);
      assert.equal(await page.locator('#activity-form button').isDisabled(), true);
      await page.locator('#activity-b').selectOption(ids[1]);
      assert.equal(await page.locator('#activity-selection-hint').innerText(), 'Нажми «Сравнить A и B».');
      original = await submit();
      assert.deepEqual(JSON.parse(await page.locator('#activity-evidence').textContent()), original);
      assert.equal(await page.locator('#activity-selection-hint').innerText(), '');
      assert.deepEqual(await page.locator('#activity-result thead th').allTextContents(), ['Показатель', 'A', 'B', 'B − A', '% к A']);
      assert.equal(await page.locator('#activity-result > p, #activity-result h3').count(), 0);
      assert.doesNotMatch(await page.locator('#activity-result').innerText(), /Теннис|Сессия [12] ·/);
      assert.deepEqual(await cells('duration_seconds'), ['1 ч', '1 ч 5 мин 1.3 с', '+5 мин 1.3 с', '8.4']);
      assert.deepEqual(await cells('distance_meters'), ['0', 'Не предоставлено', 'Не вычисляется', 'Не вычисляется']);
      assert.deepEqual(await cells('acute_training_load'), ['0', '10.0', '10.0', 'Не вычисляется']);
      assert.match(await row('acute_training_load').innerText(), /В сессии A указан ноль/);
      for (const code of ['power_watts', 'cadence_rpm']) assert.equal(await row(code).count(), 0);
      assert.ok(original.comparisons[0].metrics.some(m => m.metric_code === 'power_watts'));
      assert.ok(original.comparisons[0].metrics.some(m => m.metric_code === 'cadence_rpm'));
      assert.equal(original.comparisons[0].metrics.find(m => m.metric_code === 'duration_seconds').absolute_delta, 301.25);
      const tech = page.locator('.activity-technical');
      assert.equal(await tech.getAttribute('open'), null);
      await tech.locator('summary').focus(); await page.keyboard.press('Enter');
      assert.equal(await tech.getAttribute('open'), '');
      assert.match(await tech.innerText(), /3901.25|301.25/);
      assert.equal(await tech.locator('summary').evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
      await page.keyboard.press('Enter');
      await layout(width);
      await page.locator('.activity-comparison').screenshot({ path: path.join(evidence, `tennis-${width}.png`) });
      await page.screenshot({ path: path.join(evidence, `page-${width}.png`), fullPage: true });
      checks.push(`${width}px: persisted tennis response, exact JSON, compact selectors/table, duration, signed delta, zero/missing, keyboard/focus, no page/table scroll`);

      // Reversing A/B goes through the real production comparison API.
      await page.locator('#activity-a').selectOption(ids[1]);
      assert.equal(await page.locator('#activity-evidence').textContent(), '');
      assert.equal(await page.locator('#activity-result').textContent(), '');
      await page.locator('#activity-b').selectOption(ids[0]);
      const reverse = await submit();
      assert.equal(reverse.query.reference_activity_id, ids[1]);
      assert.equal(reverse.comparisons[0].metrics.find(m => m.metric_code === 'duration_seconds').absolute_delta, -301.25);
      assert.deepEqual(await cells('duration_seconds'), ['1 ч 5 мин 1.3 с', '1 ч', '−5 мин 1.3 с', '-7.7']);
      await layout(width);
      await page.locator('#activity-a').selectOption(ids[0]);
      await page.locator('#activity-b').selectOption(ids[1]);

      async function overridden(body) {
        await page.route(endpoint, route => route.fulfill({ json: body }));
        await submit();
        assert.deepEqual(JSON.parse(await page.locator('#activity-evidence').textContent()), body);
        await layout(width);
        await page.unroute(endpoint);
      }
      function withCoverage(code, a, b) {
        const body = structuredClone(original);
        for (const [id, field] of [[ids[0], a], [ids[1], b]]) {
          Object.assign(body.sessions.find(s => s.record_id === id).metric_coverage.find(m => m.metric_code === code), field);
        }
        const m = body.comparisons[0].metrics.find(m => m.metric_code === code);
        Object.assign(m, { status: 'not_computable', absolute_delta: null, percent_delta: null,
          reason: 'sides_not_comparable', percent_status: 'not_computable', percent_reason: 'sides_not_comparable' });
        return body;
      }
      for (const code of ['power_watts', 'cadence_rpm']) {
        for (const usableStatus of ['usable', 'zero']) {
          const present = { status: usableStatus, value: usableStatus === 'zero' ? 0 : 123, reason: null };
          const missing = { status: 'null', value: null, reason: 'null' };
          await overridden(withCoverage(code, present, missing));
          assert.equal(await row(code).count(), 1);
          assert.deepEqual((await cells(code)).slice(0, 2), [usableStatus === 'zero' ? '0' : '123.0', 'Не предоставлено']);
          await overridden(withCoverage(code, missing, present));
          assert.equal(await row(code).count(), 1);
          assert.deepEqual((await cells(code)).slice(0, 2), ['Не предоставлено', usableStatus === 'zero' ? '0' : '123.0']);
        }
        const unsupported = { status: 'unsupported', value: 123, reason: 'unreviewed_source_field' };
        await overridden(withCoverage(code, unsupported, unsupported));
        assert.equal(await row(code).count(), 0, 'An unusable numeric value must not reveal an optional row');
      }
      for (const [status, label] of [['missing', 'Не предоставлено'], ['null', 'Не предоставлено'],
        ['invalid', 'Некорректное значение'], ['partial', 'Данные доступны частично'],
        ['not_computable', 'Не вычисляется'], ['unknown', 'Состояние данных не определено']]) {
        const unavailable = { status, value: null, reason: status };
        await overridden(withCoverage('duration_seconds', unavailable, unavailable));
        assert.deepEqual(await cells('duration_seconds'), [label, label, 'Не вычисляется', 'Не вычисляется']);
      }
      for (const [a, b, delta, percent, expected] of [
        [0, 0, 0, null, ['0 с', '0 с', '0 с', 'Не вычисляется']],
        [60, 120, 60, 100, ['1 мин', '2 мин', '+1 мин', '100.0']],
        [60.1, 59.9, -0.2, -0.3327787022, ['1 мин 0.1 с', '59.9 с', '−0.2 с', '-0.3']],
        [0.04, 0.08, 0.04, 100, ['< 0.1 с', '< 0.1 с', '+< 0.1 с', '100.0']],
        [3599.96, 3600, 0.04, 0.0011111235, ['1 ч', '1 ч', '+< 0.1 с', '0.0']]
      ]) {
        const body = withCoverage('duration_seconds', { status: a === 0 ? 'zero' : 'usable', value: a, reason: null },
          { status: b === 0 ? 'zero' : 'usable', value: b, reason: null });
        Object.assign(body.comparisons[0].metrics.find(m => m.metric_code === 'duration_seconds'), {
          status: 'compared', reason: null, reference_value: a, compared_value: b, absolute_delta: delta,
          percent_delta: percent, percent_status: percent === null ? 'not_computable' : 'computed',
          percent_reason: percent === null ? 'zero_reference_percent' : null });
        await overridden(body);
        assert.deepEqual(await cells('duration_seconds'), expected);
      }
      checks.push(`${width}px: real reversed pair; synthetic presentation overrides cover both optional sides/zero, unsupported, missing/null/invalid/partial/unknown, fractional and subsecond duration; every response retained exactly`);
    }
    // An old response cannot reappear after the pair changes.
    let release, arrived;
    const gate = new Promise(resolve => { release = resolve; });
    const seen = new Promise(resolve => { arrived = resolve; });
    await page.route(endpoint, async route => { arrived(); await gate; await route.fulfill({ json: original }); });
    await page.locator('#activity-form button').click();
    await seen;
    assert.equal(await page.locator('#activity-evidence').textContent(), '');
    await page.locator('#activity-a').selectOption(ids[1]);
    const oldResponse = page.waitForResponse(r => r.url().includes('/api/garmin/activity-comparison?'));
    release(); await oldResponse;
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await page.locator('#activity-result').textContent(), '');
    assert.equal(await page.locator('#activity-evidence').textContent(), '');
    await page.unroute(endpoint);
    await page.locator('#activity-a').selectOption(ids[0]);
    await page.route(endpoint, route => route.fulfill({ status: 503, json: { reason: 'synthetic_unavailable' } }));
    await submit();
    assert.equal(await page.locator('#activity-result table').count(), 0);
    assert.match(await page.locator('#activity-result [role="alert"]').innerText(), /Не удалось выполнить запрос/);
    assert.match(await page.locator('#activity-evidence').textContent(), /synthetic_unavailable/);
    await page.unroute(endpoint);
    checks.push('Pair changes invalidate results/evidence and late responses; request errors do not retain an old table');
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    assert.deepEqual(identity(), candidate);
    const result = { status: 'PASS', candidate, fixture: 'persisted synthetic tennis + labelled presentation response overrides', checks, layouts, errors, external };
    fs.writeFileSync(path.join(evidence, 'activity-318-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
