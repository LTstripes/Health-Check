/* #375: production renderer, synthetic loopback payloads, full-history identity contract. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const root = path.join(__dirname, '..');
const git = args => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
if (!base || !evidence || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) {
  throw new Error('Explicit loopback synthetic UI URL and evidence directory required');
}
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ? { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], geometry = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1024, height: 900 }, timezoneId: 'America/Los_Angeles' });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/');
    const source = { candidate: git(['rev-parse', 'HEAD']), tree: git(['rev-parse', 'HEAD^{tree}']),
      dirty: !!git(['status', '--porcelain']), files: {} };
    for (const file of ['dashboard.js', 'dashboard.css']) {
      source.files[file] = hash(fs.readFileSync(path.join(root, 'src/healthcheck/web/static', file)));
      const response = await page.request.get(base + '/static/' + file);
      assert.equal(response.status(), 200);
      assert.equal(hash(await response.body()), source.files[file], 'served asset equals candidate source');
    }
    const original = await page.locator('#dashboard-data').textContent();
    const payload = JSON.parse(original);
    const raw = payload.series.raw_points;
    const composition = Object.values(payload.series.composition_by_group).flat();
    assert.ok(raw.length > 12 && composition.length > 1, 'full-history synthetic fixture required');
    assert.equal(await page.locator('#weight-history table').count(), 1);
    assert.equal(await page.locator('#composition-groups table').count(), 0);
    assert.equal(await page.locator('#composition-groups select').count(), 1);
    assert.equal(await page.locator('#composition-groups svg').count(), 1);
    assert.equal(await page.locator('#weight-history > details').getAttribute('open'), null);
    await page.locator('#weight-history > details > summary').focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#weight-history > details').getAttribute('open'), '');
    const headings = await page.locator('#weight-history th').allTextContents();
    assert.deepEqual(headings, ['Дата измерения', 'Вес кг', 'Жир % (источник)', 'Жир кг (расчёт)',
      'Безжировая масса кг (расчёт)', 'Мышцы кг (источник)', 'Источник/метод']);
    assert.equal(await page.locator('#weight-history th[scope="col"]').count(), 7);
    const cells = await page.locator('#weight-history tbody tr').evaluateAll(rows => rows.map(row =>
      [...row.querySelectorAll('td')].slice(0, 6).map(cell => cell.textContent)));
    assert.equal(cells.length, raw.length);
    assert.deepEqual(cells.map(row => row[0]), raw.map(point => point.observed_date).sort());
    const first = raw[0];
    const matched = composition.find(point => point.weight_measurement_id === first.evidence_id);
    await page.locator('#weight-chart [data-series="raw"]').first().focus();
    assert.match(await page.locator('#observation-detail').innerText(), new RegExp(first.observed_date));
    assert.ok((await page.locator('#observation-detail').innerText()).includes(Number(matched.estimated_lean_mass_kg).toFixed(1)));
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#weight-chart [data-series="raw"]').nth(1).evaluate(el => el === document.activeElement), true);
    checks.push('Real synthetic payload: full chronological table, semantic ID composition match, accepted weight trend and keyboard detail');
    async function renderCase(series) {
      await page.route(base + '/', async route => {
        const response = await route.fetch();
        const edited = JSON.stringify({ ...payload, series }).replace(/</g, '\\u003c');
        await route.fulfill({ response, body: (await response.text()).replace(original, edited) });
      });
      await page.goto(base + '/');
      await page.unroute(base + '/');
    }
    const dates = ['2020-02-29', '2024-12-25', '2026-04-01'];
    const w = (date, id, value = 80.125) => ({ ...first, observed_date: date, evidence_id: id, value_kg: value,
      provenance: { ...first.provenance, evidence_id: id, source_local_date: date, artifact_content_hash: '<synthetic>' } });
    const c = (date, id, index = 0) => ({ ...composition[0], observed_date: date, session_id: 'session-' + id,
      weight_measurement_id: id, body_fat_measurement_id: 'fat-' + id, compatibility_group: 'long',
      algorithm_code: 'xiaomi_home_s400_unknown_version', weight_kg: 80.125, body_fat_pct: 24.125 + index,
      estimated_fat_mass_kg: 19.33015625, estimated_lean_mass_kg: 60.79484375, source_muscle_mass_kg: null });
    const long = dates.map((date, index) => c(date, 'long-' + index, index));
    const short = [c('2026-04-01', 'short-0', 1), c('2026-04-07', 'short-1', 2)].map(point => ({ ...point,
      compatibility_group: 'short', algorithm_code: 'openscale_s400_composition_unknown', algorithm_version: 'unknown/config-1' }));
    const combined = { ...payload.series, raw_points: [...dates.map((date, index) => w(date, 'long-' + index)),
      w('2026-04-01', 'short-0'), w('2026-04-07', 'short-1'), w('2026-04-01', 'unmatched', 80.125)],
      trend_points: [], composition_by_group: { long, short } };
    await renderCase(combined);
    assert.equal(await page.locator('#weight-history tbody tr').count(), 6);
    const table = await page.locator('#weight-history tbody tr').evaluateAll(rows => rows.map(row =>
      [...row.querySelectorAll('td')].slice(0, 6).map(cell => cell.textContent)));
    assert.equal(table.filter(row => row[0] === '2026-04-01').length, 3);
    assert.deepEqual(table.find(row => row[2] === '—').slice(1), ['80.125', '—', '—', '—', '—']);
    assert.ok(table.some(row => row.includes('60.79484375')), 'table preserves exact derived value');
    const rowDetails = page.locator('#weight-history tbody details').first();
    await rowDetails.locator('summary').focus();
    await page.keyboard.press('Enter');
    const detail = JSON.parse(await rowDetails.locator('pre').textContent());
    assert.equal(detail.weight.evidence_id, 'long-0');
    assert.equal(detail.composition.session_id, 'session-long-0');
    assert.equal(detail.weight.provenance.artifact_content_hash, '<synthetic>');
    assert.equal(await rowDetails.locator('pre script').count(), 0);
    await rowDetails.locator('summary').click();
    const legend = await page.locator('.weight-method-legend').innerText();
    assert.match(legend, /Xiaomi Home.*2020.*2026/s);
    assert.match(legend, /openScale · S400 \(алгоритм состава неизвестен\).*1 апр.*7 апр/s);
    assert.doesNotMatch(legend, /xiaomi_home_s400_unknown_version|openscale_s400_composition_unknown/);
    assert.equal(await page.locator('#composition-groups [data-series="raw"]').count(), 5);
    assert.equal(await page.locator('#composition-groups path').count(), 0);
    const colors = await page.locator('#composition-groups .weight-dot').evaluateAll(dots => [...new Set(dots.map(dot => getComputedStyle(dot).fill))]);
    assert.equal(colors.length, 2);
    checks.push('Multiple methods and same-date distinct measurements remain distinct; unmatched equal date/weight has no borrowed composition; exact values and escaped full row provenance');
    fs.mkdirSync(evidence, { recursive: true });
    async function checkAxis(start, end) {
      await page.waitForFunction(() => [...document.querySelectorAll('.weight-view .chart svg')].every(svg =>
        Math.abs(svg.viewBox.baseVal.width - Math.max(260, svg.parentElement.clientWidth)) < 1 && svg.querySelector('[data-axis="x"]')));
      const axes = await page.locator('.weight-view .chart svg').evaluateAll(svgs => svgs.map(svg => ({
        labels: [...svg.querySelectorAll('[data-axis="x"]')].map(label => {
          const r = label.getBoundingClientRect(); return { date: label.dataset.date, text: label.textContent, left: r.left, right: r.right };
        }), left: svg.getBoundingClientRect().left, right: svg.getBoundingClientRect().right,
      })));
      assert.equal(axes.length, 2);
      for (const axis of axes) {
        assert.equal(axis.labels[0].date, start);
        assert.equal(axis.labels.at(-1).date, end);
        assert.ok(axis.labels.length <= 7);
        axis.labels.forEach((label, i) => {
          assert.match(label.text, /[а-я]/);
          assert.ok(label.left >= axis.left - 1 && label.right <= axis.right + 1);
          if (i) assert.ok(axis.labels[i - 1].right + 10 <= label.left);
        });
      }
      return axes;
    }
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      for (const metric of ['body_fat_pct', 'estimated_fat_mass_kg', 'estimated_lean_mass_kg', 'source_muscle_mass_kg']) {
        await page.locator('#composition-groups select').selectOption(metric);
        if (metric === 'source_muscle_mass_kg') {
          assert.equal(await page.locator('#composition-groups svg').count(), 0);
          assert.match(await page.locator('#composition-groups').innerText(), /Нет подтверждённых значений/);
        } else {
          geometry.push({ width, metric, axes: await checkAxis('2020-02-29', '2026-04-07') });
          const points = page.locator('#composition-groups [data-series="raw"]');
          await points.first().focus();
          await page.keyboard.press('ArrowRight');
          assert.equal(await points.nth(1).evaluate(el => el === document.activeElement), true);
          await page.keyboard.press('Space');
          assert.match(await page.locator('#composition-detail').innerText(), /метод 1/);
        }
      }
      await page.locator('#composition-groups select').selectOption('body_fat_pct');
      // Six-year axis: equal metric values six days apart have overlapping hit
      // targets. A pointer click must agree with hover, not the later DOM target.
      await page.locator('#composition-groups svg').evaluate(svg => svg.scrollIntoView({ block: 'center' }));
      const earlierDot = page.locator('#composition-groups [data-evidence-id="long-2"] .weight-dot');
      const center = await earlierDot.evaluate(dot => {
        const rect = dot.getBoundingClientRect();
        return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
      });
      await page.mouse.move(center.x, center.y);
      assert.match(await page.locator('#composition-detail').innerText(), /2026-04-01/);
      await page.mouse.click(center.x, center.y);
      assert.match(await page.locator('#composition-detail').innerText(), /2026-04-01/);
      assert.match(await page.locator('#composition-detail').innerText(), /Xiaomi Home.*метод 1/);
      assert.match(await page.locator('#provenance-panel').innerText(), /evidence_id: long-2/);
      assert.equal(long[2].body_fat_pct, short[1].body_fat_pct);
      const dimensions = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth,
        chart: document.querySelector('#composition-groups .chart').clientWidth,
        chartScroll: document.querySelector('#composition-groups .chart').scrollWidth,
        table: document.querySelector('.weight-history-table').clientWidth,
        tableScroll: document.querySelector('.weight-history-table').scrollWidth,
        tableOverflow: getComputedStyle(document.querySelector('.weight-history-table')).overflowX,
        hero: getComputedStyle(document.querySelector('.weight-view .hero')).display,
        minControl: document.querySelector('#composition-groups select').getBoundingClientRect().height }));
      assert.ok(dimensions.document <= width + 1);
      assert.ok(dimensions.chartScroll <= dimensions.chart + 1);
      assert.equal(dimensions.tableOverflow, 'auto');
      assert.equal(dimensions.hero, 'block');
      assert.ok(dimensions.minControl >= 44);
      geometry.push(dimensions);
      const scroll = page.locator('.weight-history-table');
      await scroll.focus();
      await page.keyboard.press('End');
      assert.equal(await scroll.evaluate(el => el === document.activeElement), true);
      await scroll.evaluate(el => { el.scrollLeft = 0; });
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(evidence, 'weight-history-' + width + '.png'), fullPage: true });
    }
    const point = page.locator('#composition-groups [data-series="raw"]').first();
    await point.focus();
    await page.setViewportSize({ width: 1024, height: 900 });
    await checkAxis('2020-02-29', '2026-04-07');
    assert.equal(await point.evaluate(el => el === document.activeElement), true);
    checks.push('1024/1440 desktop: overlapping pointer hit targets select exact visible observation date/ID/method; common full-history axes for all metrics, observed spans, no invented points/lines, keyboard/resize focus, table scroll, frozen styles/screenshots');
    // Missing vs zero, multiple methods for one exact identity, and composition-only session.
    const zero = { ...long[0], body_fat_pct: 0, estimated_fat_mass_kg: null, estimated_lean_mass_kg: null };
    const orphan = { ...short[0], observed_date: '2026-04-03', weight_measurement_id: null, weight_kg: null };
    await renderCase({ ...combined, raw_points: [w(dates[0], 'long-0')], composition_by_group: {
      long: [zero], short: [{ ...zero, algorithm_code: 'openscale_s400_composition_unknown', body_fat_pct: 21 }, orphan] } });
    assert.equal(await page.locator('#weight-history tbody tr').count(), 3);
    assert.equal(await page.locator('#composition-groups select').count(), 1);
    const negative = await page.locator('#weight-history tbody tr').evaluateAll(rows => rows.map(row =>
      [...row.querySelectorAll('td')].slice(0, 6).map(cell => cell.textContent)));
    assert.equal(negative[0][2], '0');
    assert.equal(negative[0][3], '—');
    assert.equal(negative[2][1], '—');
    assert.match(await page.locator('#weight-history tbody tr').last().locator('summary').innerText(),
      /openScale · S400 \(алгоритм состава неизвестен\)/);
    await page.locator('#composition-groups [data-series="raw"]').nth(1).focus();
    await page.keyboard.press('Enter');
    assert.match(await page.locator('#composition-detail').innerText(), /метод 2/);
    await renderCase({ ...combined, raw_points: [w('2020-02-29', 'long-0')], composition_by_group: { long: [zero] } });
    await checkAxis('2020-02-29', '2020-02-29');
    await renderCase({ ...combined, raw_points: [w('2026-04-01', 'short-0'), w('2026-04-07', 'short-1')], composition_by_group: { short } });
    await checkAxis('2026-04-01', '2026-04-07');
    await renderCase({ ...combined, raw_points: [], trend_points: [], composition_by_group: {}, trend_available: false, trend_reason: 'no_data' });
    assert.equal(await page.locator('.weight-view .chart svg').count(), 0);
    assert.equal(await page.locator('#weight-history table').count(), 0);
    assert.match(await page.locator('#weight-history').innerText(), /Это не означает ноль/);
    checks.push('Short/singleton/empty histories; explicit 0 vs missing; multiple method rows for one semantic ID; standalone composition never date-joined');
    assert.deepEqual(errors, []);
    assert.equal(git(['rev-parse', 'HEAD']), source.candidate);
    for (const file of Object.keys(source.files)) {
      assert.equal(hash(fs.readFileSync(path.join(root, 'src/healthcheck/web/static', file))), source.files[file]);
    }
    const result = { status: 'PASS', source, browser: browser.version(), checks, geometry, errors };
    fs.writeFileSync(path.join(evidence, 'weight-history-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
