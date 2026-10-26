/* Offline desktop smoke from small real-route synthetic captures; no server/DB copy. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fixtures = process.env.HC535_CAPTURE_DIR;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.ok(fixtures && evidence);
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const names = ['overview-steps', 'overview-filled', 'overview-empty', 'overview-partial',
  'overview-no-completed'];
const files = names.map(name => path.join(fixtures, `${name}.html`));
// Five route responses suffice. Refuse accidental large input, never truncate it.
assert.ok(files.reduce((sum, file) => sum + fs.statSync(file).size, 0) < 2 * 1024 * 1024);
const base = 'http://127.0.0.1:8120';
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      {executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE} : {})});
  const checks = [], errors = [], external = [];
  fs.mkdirSync(evidence, {recursive: true});
  try {
    for (const width of [1024, 1440]) {
      const page = await browser.newPage({viewport: {width, height: 1000}});
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin !== base) { external.push(url.origin); return route.abort(); }
        if (url.pathname.startsWith('/static/')) {
          const relative = url.pathname.slice('/static/'.length);
          assert.match(relative, /^[a-zA-Z0-9_.-]+$/);
          return route.fulfill({path: path.join('src/healthcheck/web/static', relative)});
        }
        assert.equal(url.pathname, '/brief');
        const name = url.searchParams.get('fixture');
        assert.ok(names.includes(name));
        return route.fulfill({contentType: 'text/html; charset=utf-8',
          body: fs.readFileSync(path.join(fixtures, `${name}.html`), 'utf8')});
      });
      for (const name of names) {
        await page.goto(`${base}/brief?fixture=${name}`);
        const trigger = page.locator('.brief-period');
        await trigger.focus();
        assert.equal(await trigger.evaluate(el => el === document.activeElement), true);
        const tooltip = page.locator('#overview-period-scope');
        await tooltip.waitFor({state: 'visible'});
        assert.equal(await tooltip.getAttribute('role'), 'tooltip');
        assert.equal(await trigger.getAttribute('aria-describedby'), 'overview-period-scope');
        if (name === 'overview-steps') {
          const steps = page.locator('[data-overview-steps]');
          for (const [provider, mean, count] of [['Garmin', '5.0', 2], ['Google', '20.0', 3]]) {
            const item = steps.locator(`[data-steps-provider="${provider}"]`);
            assert.equal((await item.locator('strong').innerText()).trim(), mean);
            const details = item.locator('details');
            await details.locator('summary').focus(); await page.keyboard.press('Enter');
            assert.equal(await details.getAttribute('open'), '');
            assert.match(await details.innerText(), new RegExp(`${count} из 7`));
            await page.keyboard.press('Enter');
          }
        }
        const columns = await page.locator('.overview-secondary').evaluate(el =>
          getComputedStyle(el).gridTemplateColumns.split(' ').length);
        assert.equal(columns, 4);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        assert.equal(overflow, false);
        checks.push({width, name, columns, overflow, keyboardTooltip: true});
      }
      await page.screenshot({path: path.join(evidence, `overview-535-${width}.png`), fullPage: true});
      await page.close();
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const result = {sha: execFileSync('git', ['rev-parse', 'HEAD'], {encoding: 'utf8'}).trim(),
      mode: 'offline-real-route-synthetic', browser: browser.version(),
      fixtureHashes: Object.fromEntries(files.map(file => [path.basename(file), digest(file)])),
      checks, errors, external};
    fs.writeFileSync(path.join(evidence, 'overview-535-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({checks: checks.length, errors, external}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
