/* #335 production /garmin with serve_335_activity_fixture.py. Synthetic only. */
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
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ? { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], layouts = [], errors = [], external = [];
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
    await page.goto(base + '/garmin');
    const payload = () => page.locator('#garmin-dashboard-data').textContent().then(JSON.parse);
    const sources = (await payload()).source_selection.sources;
    const sourceFor = count => sources.find(s => s.device_model === `Synthetic journal ${count}`).id;
    assert.equal(sources.length, 4);
    assert.match(await page.locator('#source-status').innerText(), /Выбери источник Garmin/);
    assert.equal(await page.locator('.activity-recent tbody tr').count(), 0);
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      for (const count of [0, 1, 5, 50]) {
        const query = new URLSearchParams({ garmin_source_id: sourceFor(count), start_date: '2098-01-01', end_date: '2098-01-02' });
        await page.goto(base + '/garmin?' + query);
        await page.evaluate(() => scrollTo(0, 0));
        const data = await payload();
        const response = await page.request.get(base + '/api/garmin/dashboard?' + query);
        assert.equal(response.status(), 200);
        assert.deepEqual(data, await response.json());
        assert.equal(data.activities.length, count);
        assert.equal(data.source_selection.selected_source_id, sourceFor(count));
        assert.equal(await page.locator('#garmin-source-id').inputValue(), sourceFor(count));
        assert.match(await page.locator('#source-status').innerText(), new RegExp(`Garmin · Synthetic journal ${count}`));
        assert.equal(await page.locator('.activity-recent tbody tr').count(), Math.min(count, 5));
        assert.equal(await page.locator('.activity-history tbody tr').count(), count);
        assert.equal(await page.locator('.activity-history').getAttribute('open'), null);
        assert.equal(await page.locator('.activity-history table').isVisible(), false);
        const ids = data.activities.map(a => a.record_id);
        assert.deepEqual(await page.locator('#activity-a option').evaluateAll(opts => opts.map(o => o.value).filter(Boolean)), ids);
        assert.deepEqual(await page.locator('#activity-b option').evaluateAll(opts => opts.map(o => o.value).filter(Boolean)), ids);
        if (count) {
          assert.equal(await page.locator('.activity-saved-summary p strong').innerText(), String(count));
          const rows = await page.locator('.activity-recent tbody tr').allTextContents();
          assert.ok(rows.every(r => /\d+ (января|февраля) 2099/.test(r)), JSON.stringify(rows));
          assert.ok(rows.every(r => !/2099-\d\d-\d\d/.test(r)));
          if (count >= 5) for (const name of ['Теннис', 'Велотренировка', 'Ходьба']) {
            assert.match(await page.locator('.activity-type-counts').innerText(), new RegExp(name));
          }
        } else {
          assert.equal(await page.locator('.activity-saved-summary').count(), 0);
          assert.match(await page.locator('.activity-owner-summary').innerText(), /Нагрузка не считается нулевой/);
        }
        assert.match(await page.locator('.activity-journal-context').innerText(), /вне периода аналитики/);
        assert.match(await page.locator('.activity-journal-context').innerText(), /Полнота тренировок по дням неизвестна/);
        const layout = await page.evaluate(() => ({ width: innerWidth,
          page: document.documentElement.scrollWidth,
          comparisonTop: document.querySelector('#activity-form').getBoundingClientRect().top,
          comparisonBottom: document.querySelector('#activity-form').getBoundingClientRect().bottom,
          gridColumns: getComputedStyle(document.querySelector('.activity-owner-grid') || document.body).gridTemplateColumns,
          background: getComputedStyle(document.body).backgroundColor,
          summaryHeight: document.querySelector('.activity-history summary').getBoundingClientRect().height,
          tables: [...document.querySelectorAll('.activity-owner-summary .table-scroll')].map(el => ({ width: el.clientWidth, scroll: el.scrollWidth })) }));
        assert.equal(layout.width, width);
        assert.ok(layout.page <= width + 1, JSON.stringify(layout));
        assert.ok(layout.comparisonBottom <= 900, JSON.stringify(layout));
        assert.equal(layout.background, 'rgb(246, 242, 233)');
        assert.ok(layout.summaryHeight >= 44);
        if (count) assert.equal(layout.gridColumns.split(' ').length, 2);
        assert.ok(layout.tables.every(t => t.scroll <= t.width + 1), JSON.stringify(layout));
        layouts.push({ count, ...layout });
        if (count === 50) await page.screenshot({ path: path.join(evidence, `activity-335-${width}.png`), fullPage: true });
        await page.locator('.activity-history summary').focus();
        await page.keyboard.press('Enter');
        assert.ok(await page.locator('.activity-history summary').evaluate(el => {
          const style = getComputedStyle(el);
          return el === document.activeElement && style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0;
        }), 'History keyboard focus must remain visible');
        assert.equal(await page.locator('.activity-history').getAttribute('open'), '');
        if (count) {
          assert.equal(await page.locator('.activity-history tbody tr:visible').count(), count);
          const recentRows = await page.locator('.activity-recent tbody tr').allTextContents();
          const fullRows = await page.locator('.activity-history tbody tr').allTextContents();
          assert.deepEqual(recentRows, fullRows.slice(0, 5));
          const table = await page.locator('.activity-history .table-scroll').evaluate(el => ({ width: el.clientWidth, scroll: el.scrollWidth }));
          assert.ok(table.scroll <= table.width + 1, JSON.stringify(table));
          if (count === 50) await page.screenshot({ path: path.join(evidence, `activity-335-history-${width}.png`) });
        }
        await page.keyboard.press('Space');
        assert.equal(await page.locator('.activity-history').getAttribute('open'), null);
        await page.locator('[data-activity-mode="training-recovery"]').click();
        await page.waitForFunction(() => !document.querySelector('#training-recovery').hidden);
        assert.equal(await page.locator('#training-recovery').isVisible(), true);
        assert.match(await page.locator('#training-recovery').innerText(), /не означает нулевую нагрузку/);
        await page.locator('a[href="#activity-comparison"]').click();
        await page.waitForFunction(() => !document.querySelector('#activity-journal').hidden);
        assert.equal(await page.locator('#activity-journal').isVisible(), true);
        assert.ok(await page.locator('#activity-form').evaluate(el => {
          const box = el.getBoundingClientRect(); return box.top >= 0 && box.bottom <= innerHeight;
        }), 'A/B shortcut must reach the form from Training/Recovery');
        if (count >= 5) {
          await page.locator('#activity-a').selectOption(ids[1]);
          await page.locator('#activity-b').selectOption(ids[0]);
          const compared = page.waitForResponse(r => r.url().includes('/api/garmin/activity-comparison?'));
          await page.locator('#activity-form button').focus();
          await page.keyboard.press('Enter');
          const exact = await (await compared).json();
          await page.waitForFunction(() => document.querySelector('#activity-result').getAttribute('aria-busy') === 'false');
          assert.deepEqual(await page.locator('#activity-result thead th').allTextContents(), ['Показатель', 'A', 'B', 'B − A', '% к A']);
          assert.deepEqual(JSON.parse(await page.locator('#activity-evidence').textContent()), exact);
          assert.equal(exact.query.reference_activity_id, ids[1]);
          const duration = exact.comparisons[0].metrics.find(m => m.metric_code === 'duration_seconds');
          assert.equal(duration.absolute_delta, duration.compared_value - duration.reference_value);
        } else {
          assert.equal(await page.locator('#activity-a').isDisabled(), true);
          assert.equal(await page.locator('#activity-form button').isDisabled(), true);
        }
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        checks.push(`${width}px/${count}: selected source, exact API payload/all selector identities, bounded summary/recent rows, human dates, collapsed keyboard history, period/coverage wording, A/B and training reachability`);
      }
    }
    await page.locator('#garmin-source-id').selectOption(sourceFor(0));
    await Promise.all([page.waitForURL(url => url.searchParams.get('garmin_source_id') === sourceFor(0)), page.locator('#source-form button').click()]);
    assert.equal((await payload()).activities.length, 0);
    assert.equal(await page.locator('#activity-result table').count(), 0);
    assert.equal(await page.locator('#activity-evidence').textContent(), '');
    assert.equal(await page.locator('.activity-recent tbody tr').count(), 0);
    checks.push('Source form reload clears prior sessions/comparison/evidence; unknown unselected and selected empty stay distinct from zero load');
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    assert.deepEqual(identity(), candidate);
    const result = { status: 'PASS', candidate, browser: await browser.version(), checks, layouts, errors, external };
    fs.writeFileSync(path.join(evidence, 'activity-335-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
