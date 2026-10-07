/* Owner Sleep v2 browser acceptance against the external synthetic acceptance fixture. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
if (!base || !evidence || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) {
  throw new Error('Explicit loopback synthetic URL and evidence directory required');
}
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    const page = await browser.newPage({locale: 'ru-RU'});
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {
      if (m.type() === 'error' && !(m.location().url || '').endsWith('/favicon.ico')) errors.push(m.text());
    });
    async function geometry() {
      const g = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        navRows: new Set([...document.querySelector('.owner-nav').children].map(x => x.offsetTop)).size,
        target: document.querySelector('main details summary').getBoundingClientRect().height,
      }));
      assert.equal(g.overflow, false, JSON.stringify(g));
      assert.equal(g.navRows, 1);
      assert.ok(g.target >= 44);
    }
    for (const width of [1100, 800, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base + '/sleep?wake_date=2099-01-02');
      assert.equal(await page.locator('.sleep-night [data-night-row]').count(), 1);
      assert.match(await page.locator('.sleep-night [data-night-row]').innerText(), /8 ч 0 мин.*82/s);
      assert.equal(await page.locator('[data-google-vitals]').count(), 0);
      assert.equal(await page.locator('.sleep-night [data-owner-state="present"]').count(), 0);
      const history = page.locator('.sleep-records');
      assert.equal(await history.getAttribute('open'), null);
      await history.locator('summary').click();
      assert.equal(await history.locator('[data-night-row]').count(), 0); // selected date appears only once
      await history.locator('summary').click();
      for (const view of ['garmin', 'google', 'compare']) {
        if (view !== 'garmin') {
          await page.locator(`.sleep-source-switch a[href*="view=${view}"]`).click();
          await page.waitForURL(`**view=${view}**`);
        }
        assert.match(page.url(), /wake_date=2099-01-02/);
        assert.equal(await page.locator('.sleep-source-switch [aria-current]').innerText(),
          {garmin: 'Garmin', google: 'Google', compare: 'Сравнить'}[view]);
        assert.equal(await page.locator('html').getAttribute('lang'), 'ru');
        assert.equal(await page.locator('h1').innerText(), 'Сон');
        assert.equal(await page.locator('main [lang="en"]').count(), 0);
        const tech = page.locator('.sleep-technical');
        assert.equal(await page.getByText('Технические детали', {exact: true}).count(), 1);
        assert.equal(await tech.getAttribute('open'), null);
        const visible = await page.locator('main').innerText();
        assert.doesNotMatch(visible, /result_hash|Sleep Agreement|bias|rmse|Точность устройств/);
        if (view === 'google') {
          assert.equal(await page.locator('.sleep-night').count(), 0);
          assert.equal(await page.locator('[data-google-source]').count(), 2);
          assert.match(visible, /42\.5 мс/);
          assert.match(visible, /суточные показатели, а не измерения внутри сна/);
          assert.match(visible, /явный ноль/);
        }
        if (view === 'compare') {
          assert.equal(await page.locator('[data-source-series="garmin"]').count(), 1);
          assert.equal(await page.locator('[data-source-series="google"]').count(), 1);
          assert.equal(await page.locator('.sleep-comparison-chart svg circle').count(), 2);
          assert.equal(await page.locator('.sleep-comparison-chart svg rect').count(), 2);
          assert.match(visible, /семейство устройств/);
          assert.match(visible, /дневные показатели.*разный смысл/s);
          assert.match(visible, /совместимой оценки Google нет/);
          assert.doesNotMatch(visible, /28920|28800/);
          const values = page.locator('.sleep-chart-values');
          await values.locator('summary').click();
          assert.match(await values.innerText(), /8 ч 2 мин/);
          await values.locator('summary').click();
        }
        await geometry();
        await tech.locator('summary').focus();
        await page.keyboard.press('Enter');
        assert.equal(await tech.getAttribute('open'), '');
        for (const provider of ['Garmin', 'Google', 'Сравнение']) {
          assert.equal(await tech.getByRole('heading', {name: provider, exact: true}).count(), 1);
        }
        assert.match(await tech.innerText(), view === 'compare' ? /comparison_basis/ : /result_hash/);
        await geometry();
        await page.keyboard.press('Enter');
        assert.equal(await tech.getAttribute('open'), null);
        assert.equal(await tech.locator('summary').evaluate(el => el === document.activeElement), true);
        await page.evaluate(() => scrollTo(0, 0));
        await page.screenshot({path: path.join(evidence, `sleep-${view}-${width}.png`), fullPage: true});
      }
      await page.goto(base + '/agreement');
      assert.equal(await page.locator('[data-source-series]').count(), 2);
      assert.equal(await page.locator('.sleep-comparison-chart svg circle').count(), 14);
      assert.match(await page.locator('main').innerText(), /\+8 мин 30 с/);
      await geometry();
      await page.screenshot({path: path.join(evidence, `sleep-saved-comparison-${width}.png`), fullPage: true});
      await page.goto(base + '/sleep?wake_date=2099-01-03');
      const night = page.locator('.sleep-night');
      assert.match(await night.innerText(), /нет пригодного значения/);
      assert.doesNotMatch(await night.innerText(), /28800|82|0 ч/);
      assert.equal(await night.locator('[data-owner-state="unavailable"]').count(), 2);
      await geometry();
      checks.push(`${width}px: one nightly row, three source views, paired two-series chart, missing night, Russian copy, one keyboard disclosure, no overflow`);
    }
    // Gap geometry is checked independently from normal contiguous synthetic pairs.
    await page.goto(base + '/agreement');
    await page.evaluate(() => {
      const svg = document.querySelector('svg[data-sleep-comparison]');
      const chart = JSON.parse(svg.dataset.sleepComparison);
      chart.points = [chart.points[0], chart.points[2]];
      svg.dataset.sleepComparison = JSON.stringify(chart);
      svg.replaceChildren();
    });
    await page.addScriptTag({url: base + '/static/agreement.js'});
    const paths = await page.locator('[data-source-series]').evaluateAll(nodes => nodes.map(n => n.getAttribute('d')));
    assert.ok(paths.every(d => (d.match(/M/g) || []).length === 2 && !d.includes('L')));
    checks.push('Both source lines break across a missing wake date');
    await page.locator('main a[href="/imports"]').first().click();
    await page.waitForURL('**/imports');
    assert.equal(await page.locator('h1').innerText(), 'Данные');
    assert.deepEqual(errors, []);
    const result = { status: 'PASS', checks, errors };
    fs.writeFileSync(path.join(evidence, 'sleep-v2-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
