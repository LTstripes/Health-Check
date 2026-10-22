/* Production UI + disposable serve_493_readable_fixture.py only. No providers. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const empty = process.env.HEALTHCHECK_BROWSER_EMPTY_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
for (const url of [base, empty]) assert.match(url || '', /^http:\/\/127\.0\.0\.1:\d+$/);
assert.ok(evidence && !path.resolve(evidence).startsWith(root), 'External evidence required');
const git = args => execFileSync('git', args, {cwd: root, encoding: 'utf8'}).trim();
assert.equal(git(['status', '--porcelain']), '', 'A clean frozen candidate is required');
const sha = git(['rev-parse', 'HEAD']);
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const report = {sha, tree: git(['rev-parse', 'HEAD^{tree}']), checks: [], screenshots: [], assets: {},
  errors: [], forbidden: [], manifests: []};
for (const [name, url] of [['FILLED', base], ['EMPTY', empty]]) {
  const manifest = JSON.parse(fs.readFileSync(process.env['HEALTHCHECK_BROWSER_' + name + '_MANIFEST'], 'utf8'));
  assert.equal(manifest.sha, sha); assert.equal(manifest.port, Number(new URL(url).port));
  assert.equal(manifest.private_data, false); assert.equal(manifest.provider_calls, false);
  report.manifests.push(manifest);
}
const seconds = /(?:^|\s)\d+(?:[.,]\d+)?\s+с(?:\s|$)/u;
(async () => {
  fs.mkdirSync(evidence, {recursive: true});
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE});
  try {
    const context = await browser.newContext({timezoneId: 'Pacific/Honolulu'});
    await context.route('**/*', route => {
      const url = route.request().url();
      if (url.startsWith(base + '/') || url.startsWith(empty + '/')) return route.continue();
      report.forbidden.push(url); return route.abort();
    });
    const page = await context.newPage();
    page.on('pageerror', err => report.errors.push(err.message));
    for (const asset of ['owner_formatting.js', 'sleep_timeline.js', 'garmin_dashboard.js']) {
      const response = await page.request.get(base + '/static/' + asset);
      assert.equal(response.status(), 200);
      const bytes = await response.body();
      assert.equal(hash(bytes), hash(fs.readFileSync(path.join(root, 'src/healthcheck/web/static', asset))));
      report.assets[asset] = hash(bytes);
    }
    for (const width of [1024, 1440]) {
      await page.setViewportSize({width, height: 960});
      for (const [state, origin] of [['filled-partial', base], ['empty', empty]]) {
        const routes = [
          ['overview', '/brief?start_date=2099-01-01&end_date=2099-01-07'],
          ['selected-night', '/sleep?view=garmin&wake_date=2099-01-07'],
          ['google-night', '/sleep?view=google&wake_date=2099-01-02'],
          ['timeline', '/sleep?view=timeline&days=7&wake_date=2099-01-07'],
          ['activity', '/garmin?metric_code=sleep_duration_seconds&start_date=2099-01-01&end_date=2099-01-07'],
          ['training', '/garmin?metric_code=sleep_duration_seconds&start_date=2099-01-01&end_date=2099-01-07#training-recovery'],
          ['compare', '/agreement'],
        ];
        for (const [name, route] of routes) {
          assert.equal((await page.goto(origin + route)).status(), 200, state + '/' + name);
          await page.waitForTimeout(120);
          if (name === 'timeline' && state === 'filled-partial') {
            const point = page.locator('[data-sleep-series-group^="garmin:"] [data-sleep-point-state="value"]').last();
            await point.focus();
            const text = await page.locator('#sleep-timeline-detail').innerText();
            assert.match(text, /ч|мин/); assert.doesNotMatch(text, seconds);
            assert.doesNotMatch(text, /UUID|ID записи|precision=|Состояние записи|Кандидаты/);
            assert.equal(await page.locator('#sleep-timeline-detail details[open]').count(), 0);
          }
          if (name === 'selected-night' && state === 'filled-partial') {
            assert.match(await page.locator('.sleep-night').innerText(), /7 ч 20 мин/);
            assert.match(await page.locator('.sleep-night').innerText(), /не проверена по границам/);
          }
          if (name === 'overview' && state === 'filled-partial') {
            const sleep = page.locator('[data-overview-period-sleep]');
            // Selector is production-specific; a real positive card is mandatory.
            assert.match(await sleep.innerText(), /ч|мин/);
            assert.doesNotMatch(await sleep.innerText(), seconds);
          }
          if (name === 'activity' && state === 'filled-partial') {
            assert.match(await page.locator('.activity-saved-summary').innerText(), /трениров/);
            assert.doesNotMatch(await page.locator('.activity-saved-summary').innerText(), /tennis_v2|cycling|сессий/);
          }
          if (name === 'training') {
            const text = await page.locator('#training-recovery').innerText();
            if (state === 'filled-partial') {
              assert.match(text, /Готовность и восстановление/);
              assert.match(text, /Единица времени восстановления не предоставлена/);
            }
          }
          if (name === 'compare') {
            assert.equal(await page.locator('[data-comparison-group]').count(), 0);
            const text = await page.locator('main').innerText();
            assert.match(text, /сохранённого сравнения|Сохранённого сравнения/);
            assert.doesNotMatch(text, /Источник: Состояние данных не определено/);
          }
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
            state + '/' + name + '/' + width + ' horizontal overflow');
          const png = `${state}-${name}-${width}.png`;
          await page.screenshot({path: path.join(evidence, png), fullPage: true});
          report.screenshots.push({file: png, sha256: hash(fs.readFileSync(path.join(evidence, png)))});
          report.checks.push(state + '/' + name + '/' + width);
        }
      }
    }
    assert.deepEqual(report.errors, []); assert.deepEqual(report.forbidden, []);
    // JS minute contract and independent endpoint offset proof, under a hostile host TZ.
    const values = await page.evaluate(() => [0, .001, 59.999, 60, 89.999, 90, 3599.99, -1].map(v => window.healthcheckOwnerFormat.duration(v)));
    assert.deepEqual(values, ['0 мин', '<1 мин', '<1 мин', '1 мин', '1 мин', '2 мин', '1 ч 0 мин', 'Недоступно']);
    report.checks.push('JS duration 0/subminute/HALF_UP/invalid under Pacific/Honolulu');
    const clocks = await page.evaluate(() => {
      const start = {eligible: true, value: '2026-10-24T20:00:00Z'};
      const end = {eligible: true, value: '2026-10-25T06:00:00Z'};
      const session = {metrics: {duration: {evidence: {quality_inputs: {summary_boundary: {
        start: {precision: 'instant', measured_at_utc: start.value, source_utc_offset_minutes: 120},
        end: {precision: 'instant', measured_at_utc: end.value, source_utc_offset_minutes: 60},
      }}}}}};
      const endpoint = window.healthcheckOwnerFormat.endpoint;
      const results = [endpoint(start, session, 'sleep_start_at'), endpoint(end, session, 'sleep_end_at')];
      delete session.metrics.duration.evidence.quality_inputs.summary_boundary.end;
      results.push(endpoint(end, session, 'sleep_end_at'));
      end.eligible = false;
      results.push(endpoint(end, session, 'sleep_end_at'));
      return results;
    });
    assert.match(clocks[0], /22:00 UTC\+0200$/);
    assert.match(clocks[1], /07:00 UTC\+0100$/);
    assert.match(clocks[2], /06:00 UTC$/);
    assert.equal(clocks[3], '—');
    report.checks.push('JS exact independent DST endpoints; no borrowed end offset; no metadata eligibility promotion');
    report.outcome = 'PASS';
  } catch (err) { report.outcome = 'FAIL'; report.failure = err.stack; throw err; }
  finally { fs.writeFileSync(path.join(evidence, 'receipt.json'), JSON.stringify(report, null, 2)); await browser.close(); }
})().catch(err => { console.error(err); process.exitCode = 1; });
