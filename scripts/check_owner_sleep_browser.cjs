/* Stage-5 narrow Chromium smoke. Run against a disposable synthetic UI seeded
 * with tests/test_sleep_owner_ui.py:seed_sleep and agreement_fixture.
 * Explicit loopback URL and external evidence directory are required.
 */
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
    const page = await browser.newPage();
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {
      if (m.type() === 'error' && !(m.location().url || '').endsWith('/favicon.ico')) {
        errors.push(m.text());
      }
    });
    for (const width of [1100, 800, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const route of ['/sleep?wake_date=2099-01-02', '/agreement']) {
        await page.goto(base + route);
        assert.equal(await page.locator('html').getAttribute('lang'), 'ru');
        assert.equal(await page.locator('h1').innerText(), 'Сон');
        assert.equal(await page.locator('.owner-nav [aria-current]').innerText(), 'Сон');
        assert.equal(await page.locator('main [lang="en"]').count(), 0);
        const content = await page.locator('main').innerText();
        assert.match(content, /Точность/);
        const tech = page.locator('main details.owner-details:not(.sleep-records)').first();
        assert.equal(await tech.getAttribute('open'), null);
        const summary = tech.locator('summary');
        await summary.focus();
        await page.keyboard.press('Enter');
        assert.equal(await tech.getAttribute('open'), '');
        assert.match(await tech.innerText(), route.startsWith('/sleep') ? /result_hash/ : /bias/);
        if (route === '/agreement') {
          assert.equal(await page.locator('.agreement-chart svg path').count(), 1);
          assert.equal(await page.locator('.agreement-chart svg rect').count(), 14);
          assert.match(content, /Семейство устройств Google/);
          assert.match(content, /основного источника|Основной источник/);
        } else {
          assert.match(content, /8 ч 0 мин/);
          assert.match(content, /82/);
          assert.match(content, /История сна/);
          assert.equal(await page.locator('[data-sleep-metric] .status-chip[data-owner-state="present"]').count(), 0);
          assert.match(content, /2 января 2099/);
          const history = page.locator(".sleep-records");
          assert.equal(await history.getAttribute("open"), null);
          await history.locator("summary").click();
          assert.equal(await history.locator("table").isVisible(), true);
          assert.doesNotMatch(await history.locator("thead").innerText(), /Состояние/);
        }
        // Check geometry with disclosure open as well as closed.
        async function geometry() {
          const g = await page.evaluate(() => ({
            overflow: document.documentElement.scrollWidth > innerWidth + 1,
            doc: document.documentElement.scrollWidth, view: innerWidth,
            navRows: new Set([...document.querySelector('.owner-nav').children].map(x => x.offsetTop)).size,
            target: document.querySelector('main details summary').getBoundingClientRect().height,
          }));
          assert.equal(g.overflow, false, JSON.stringify(g));
          assert.equal(g.navRows, 1);
          assert.ok(g.target >= 44);
        }
        await geometry();
        await summary.focus();
        await page.keyboard.press('Enter');
        assert.equal(await tech.getAttribute('open'), null);
        assert.equal(await summary.evaluate(el => el === document.activeElement), true);
        await geometry();
        await page.evaluate(() => scrollTo(0, 0));
        await page.screenshot({path: path.join(evidence, (route === '/agreement' ? 'agreement-' : 'sleep-') + width + '.png'), fullPage: true});
      }
      await page.goto(base + '/sleep?wake_date=2099-01-03');
      const night = page.locator('main > .owner-page-content > section').nth(1);
      assert.match(await night.innerText(), /нет пригодного значения/);
      assert.doesNotMatch(await night.innerText(), /28800|82\.0|(^|\s)0 с/);
      assert.equal(await night.locator('[data-owner-state="unavailable"]').count(), 2);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      checks.push(width + 'px: Russian Sleep and comparison, charts execute, closed/keyboard disclosures, open/closed no overflow, honest missing date');
    }
    await page.locator('main a[href="/imports"]').first().click();
    await page.waitForURL('**/imports');
    assert.equal(await page.locator('h1').innerText(), 'Данные');
    checks.push('Data link reaches source status surface');
    assert.deepEqual(errors, []);
    checks.push('No console or page JavaScript errors');
    const result = { status: 'PASS', checks, errors };
    fs.writeFileSync(path.join(evidence, 'sleep-stage5-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
