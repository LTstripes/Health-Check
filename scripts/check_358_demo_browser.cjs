/* Fixed-seed synthetic multidomain demo profile browser checks (#358).
 *
 * First seed and start the demo profile outside the checkout:
 *   $env:HEALTHCHECK_DATA_DIR = Join-Path $env:LOCALAPPDATA "Health-Check\multidomain-synthetic-demo"
 *   uv run python -m healthcheck.cli seed-demo
 *   uv run python -m healthcheck.cli serve --app ui --port 8126
 * then run this script with HEALTHCHECK_BROWSER_BASE_URL=http://127.0.0.1:8126,
 * HEALTHCHECK_BROWSER_EVIDENCE_DIR=<external evidence dir> and (when needed)
 * HEALTHCHECK_BROWSER_EXECUTABLE.  All assertions and screenshots use only the
 * seeded synthetic demo profile; see docs/SYNTHETIC_DEMO.md.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
if (!base || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) {
  throw new Error('Explicit loopback HEALTHCHECK_BROWSER_BASE_URL required');
}
if (!evidence) throw new Error('HEALTHCHECK_BROWSER_EVIDENCE_DIR required');
const git = args => execFileSync('git', args, { cwd: path.join(__dirname, '..'), encoding: 'utf8' }).trim();

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1024, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, locale: 'ru-RU' });
      await page.route('**/*', route => {
        if (new URL(route.request().url()).origin !== base) {
          external.push(route.request().url()); return route.abort();
        }
        return route.continue();
      });
      page.on('pageerror', e => errors.push(`${width}px: ${e.message}`));
      page.on('console', m => {
        if (m.type() === 'error' && !(m.location().url || '').endsWith('/favicon.ico')) {
          errors.push(`${width}px: ${m.text()}`);
        }
      });
      const settle = async label => {
        const g = await page.evaluate(() => ({
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
          lang: document.documentElement.lang,
        }));
        assert.equal(g.overflow, false, `${label} overflows horizontally at ${width}px`);
        assert.equal(g.lang, 'ru', `${label} is not the owner Russian UI at ${width}px`);
      };
      const shoot = async name => {
        await page.evaluate(() => scrollTo(0, 0));
        await page.screenshot({ path: path.join(evidence, `${name}-${width}.png`), fullPage: true });
      };
      const open = async (label, url) => {
        const response = await page.goto(base + url);
        assert.equal(response.status(), 200, `${label} did not return 200 at ${width}px`);
      };

      // 1. Weight: the existing six-month synthetic batch on the real brief.
      await open('brief', '/brief?start_date=2026-01-01&end_date=2026-07-31');
      const weight = page.locator('[data-overview-chart="weight"]');
      assert.equal(await weight.locator('.overview-observed').count(), 26);
      assert.match(await weight.innerText(), /EWMA, 21 день/);
      await settle('brief');
      await shoot('demo-weight-brief');

      // 2. Garmin sleep: fixed full night with all four stage intervals.
      await open('garmin sleep', '/sleep?wake_date=2026-10-10&view=garmin');
      const garminNight = page.locator('.sleep-night');
      const garminNightText = await garminNight.innerText();
      assert.match(garminNightText, /Длительность сна/);
      assert.match(garminNightText, /\d+ ч \d+ мин/);
      assert.match(garminNightText, /Оценка Garmin/);
      assert.equal(await page.locator('[data-night-row]').count(), 25);
      const garminStages = garminNight.locator('details.source-sleep-details');
      await garminStages.locator('summary').click();
      const garminStagesText = await garminStages.innerText();
      assert.match(garminStagesText, /Быстрый сон \(REM\)[\s\S]{0,160}\d+ ч \d+ мин/);
      assert.match(garminStagesText, /Бодрствование внутри сессии[\s\S]{0,160}\d+ мин/);
      await settle('garmin sleep');
      await shoot('demo-sleep-garmin-full');

      // 3. Garmin sleep: a missing fixed night stays a missing state.
      await open('garmin sleep missing', '/sleep?wake_date=2026-10-08&view=garmin');
      const missingText = await page.locator('.sleep-night').innerText();
      assert.match(missingText, /нет пригодного значения/);
      assert.doesNotMatch(missingText, /\d+ ч \d+ мин/);
      assert.equal(await page.locator('[data-night-row]').count(), 24);
      await settle('garmin sleep missing');
      await shoot('demo-sleep-garmin-missing');

      // 4. Google sleep: independent source label with its own duration.
      await open('google sleep', '/sleep?wake_date=2026-10-04&view=google');
      const googleNight = page.locator('.google-sleep-night');
      assert.match(await googleNight.innerText(), /Google/);
      const googleDuration = googleNight.locator(
        '[data-source-sleep-metric="sleep_duration_asleep_seconds"] .source-sleep-value');
      assert.match(await googleDuration.innerText(), /\d+ ч \d+ мин/);
      await settle('google sleep');
      await shoot('demo-sleep-google');

      // 5. Google sleep: the partial fixed night keeps a non-value state.
      await open('google sleep partial', '/sleep?wake_date=2026-09-23&view=google');
      const partialCell = page.locator('.google-sleep-night').locator(
        '[data-source-sleep-metric="sleep_duration_asleep_seconds"]');
      const partialText = await partialCell.innerText();
      assert.match(partialText, /нет пригодного значения|недостаточно сохранённых данных/);
      assert.doesNotMatch(partialText, /\d+ ч \d+ мин/);
      await settle('google sleep partial');
      await shoot('demo-sleep-google-partial');

      // 6. Comparison: no fabricated agreement without a published run.
      await open('sleep comparison', '/sleep?wake_date=2026-10-10&view=compare');
      const compareText = await page.locator('main').innerText();
      assert.match(compareText, /Нет доступного сохранённого сравнения\./);
      assert.doesNotMatch(compareText, /\+\d+ мин \d+ с/);
      await settle('sleep comparison');
      await shoot('demo-sleep-compare');
      const compareTechnical = page.locator('details.sleep-technical');
      await compareTechnical.locator('summary').click();
      assert.match(await compareTechnical.innerText(), /Разность: Google − Garmin/);

      // 7. Activity: tennis and cycling sessions from the fixed seed.
      await open('activity', '/garmin');
      assert.equal(await page.locator('.activity-recent tbody tr').count(), 5);
      assert.equal(await page.locator('.activity-history tbody tr').count(), 6);
      const typeCounts = await page.locator('.activity-type-counts').innerText();
      assert.match(typeCounts, /Велотренировка\s+3/);
      assert.match(typeCounts, /Теннис\s+2/);
      assert.match(typeCounts, /Ходьба\s+1/);
      await settle('activity');
      await shoot('demo-activity');

      // 8. Dated Context notes with synthetic labels.
      await open('context', '/context');
      assert.equal(await page.locator('.context-note').count(), 6);
      const firstNote = await page.locator('.context-note').first().innerText();
      assert.match(firstNote, /Синтетическое демо:/);
      assert.match(firstNote, /synthetic-demo \(confirmed, cli\)/);
      await settle('context');
      await shoot('demo-context');

      // 9. Overview: the same synthetic profile stays visually labelled data.
      await open('overview', '/');
      assert.match(await page.locator('main').innerText(), /76\.2/);
      await settle('overview');
      await shoot('demo-overview');

      checks.push(`${width}px: weight brief, Garmin full/missing nights, Google full/partial nights, comparison boundary, tennis/cycling activity, dated context, overview`);
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    const result = {
      status: 'PASS',
      sha: git(['rev-parse', 'HEAD']),
      tree: git(['rev-parse', 'HEAD^{tree}']),
      browser: browser.version(),
      widths: [1024, 1440],
      checks,
      errors,
      external,
    };
    fs.writeFileSync(path.join(evidence, 'demo-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({ sha: result.sha, browser: result.browser, cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
