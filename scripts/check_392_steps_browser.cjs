/* Actual synthetic loopback UI; no external request or provider access. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const dir = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const bindingPath = process.env.HEALTHCHECK_STEPS_BINDING;
assert.ok(/^http:\/\/127\.0\.0\.1:\d+$/.test(base) && dir && bindingPath);
const binding = JSON.parse(fs.readFileSync(bindingPath, 'utf8'));
assert.equal(binding.synthetic, true);
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      {executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE} : {})});
  const errors = [], external = [], checks = [], screenshots = [];
  fs.mkdirSync(dir, {recursive:true});
  try {
    for (const width of [1024, 1440]) {
      const page = await browser.newPage({viewport:{width,height:1000},locale:'ru-RU'});
      page.on('pageerror', e => errors.push(e.message));
      await page.route('**/*', route => {
        if (new URL(route.request().url()).origin !== base) {
          external.push(route.request().url()); return route.abort();
        }
        return route.continue();
      });
      const root = base+'/statistics?period=7&end_date=2099-01-08';
      await page.goto(root);
      const surface = page.locator('[data-google-steps]');
      assert.equal(await surface.locator('[data-google-steps-reason="source_selection_required"]').count(),1);
      await surface.getByRole('link', {name:'Google · google-wearables',exact:true}).focus();
      await page.keyboard.press('Enter');
      await page.waitForURL(url => url.searchParams.get('google_steps_source_id')===binding.selected);
      const value = day => surface.locator('[data-google-steps-date="'+day+'"] [data-google-steps-value]');
      assert.equal((await value('2099-01-02').innerText()).trim(),'9223372036854775807');
      assert.equal((await value('2099-01-03').innerText()).trim(),'0');
      assert.equal(await surface.locator('[data-google-steps-state="missing"]').count(),1);
      assert.equal(await surface.locator('[data-google-steps-state="null"]').count(),1);
      assert.equal(await surface.locator('[data-google-steps-state="invalid"]').count(),2);
      assert.equal(await surface.locator('[data-google-steps-state="no_observation"]').count(),1);
      const summary = surface.locator('details summary').first();
      await summary.focus(); await page.keyboard.press('Enter');
      assert.equal(await surface.locator('details').first().getAttribute('open'),'');
      assert.match(await surface.locator('details').first().innerText(),/Coverage \/ pagination \/ timezone \/ finality: unknown/);
      await page.keyboard.press('Enter');
      await surface.scrollIntoViewIfNeeded();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth));
      const screenshot = path.join(dir,'google-steps-'+width+'.png');
      await surface.screenshot({path:screenshot});
      screenshots.push({name:path.basename(screenshot),sha256:crypto.createHash('sha256').update(fs.readFileSync(screenshot)).digest('hex')});
      await page.locator('select[name=period]').selectOption('30');
      await page.locator('#statistics-controls button[type=submit]').click();
      await page.waitForURL(url=>url.searchParams.get('period')==='30');
      assert.equal(new URL(page.url()).searchParams.get('google_steps_source_id'),binding.selected);
      assert.equal(await page.locator('[data-google-steps-date]').count(),30);
      await page.locator('[data-google-steps]').getByRole('link',{name:'Google · all-sources',exact:true}).click();
      await page.waitForURL(url=>url.searchParams.get('google_steps_source_id')===binding.alternate);
      assert.equal((await page.locator('[data-google-steps-date="2099-01-02"] [data-google-steps-value]').innerText()).trim(),'88');
      await page.goto(root+'&google_steps_source_id=unknown-source');
      assert.equal(await surface.locator('[data-google-steps-reason="source_not_evidenced"]').count(),1);
      await page.goto(root+'&steps_period=all_time');
      assert.equal(await surface.locator('[data-google-steps-reason="unsupported_window"]').count(),1);
      checks.push({width,keyboard_source:true,exact_int64:true,zero_and_nonvalues:true,
        disclosure:true,period_preserves_source:true,independent_family:true,no_page_overflow:true,
        explicit_source_no_fallback:true,all_time_disclosed:true});
      await page.close();
    }
    assert.deepEqual(errors,[]); assert.deepEqual(external,[]);
    fs.writeFileSync(path.join(dir,'result.json'),JSON.stringify({binding,checks,screenshots,errors,external},null,2));
    console.log(JSON.stringify({checks,screenshots,errors,external},null,2));
  } finally { await browser.close(); }
})().catch(e=>{ console.error(e); process.exitCode=1; });

