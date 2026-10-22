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
assert.equal(binding.tracked_changes, '');
const emptyBase = process.env.HEALTHCHECK_STEPS_EMPTY_BASE_URL;
const emptyBinding = process.env.HEALTHCHECK_STEPS_EMPTY_BINDING;
if (emptyBase) {
  assert.ok(/^http:\/\/127\.0\.0\.1:\d+$/.test(emptyBase) && emptyBinding);
  const manifest = JSON.parse(fs.readFileSync(emptyBinding, 'utf8'));
  assert.equal(manifest.synthetic, true); assert.equal(manifest.empty, true);
  assert.equal(manifest.sha, binding.sha); assert.equal(manifest.tracked_changes, '');
}
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      {executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE} : {})});
  const errors = [], external = [], checks = [], screenshots = [];
  fs.mkdirSync(dir, {recursive:true});
  // Capture real viewports after ordinary scrolling; a tall element screenshot can
  // composite the sticky header into the middle of an offscreen panel.
  async function capture(page, name, selector) {
    await page.evaluate(selector => {
      const element = document.querySelector(selector);
      const header = document.querySelector('header.top');
      const inset = (header ? header.getBoundingClientRect().height : 0) + 16;
      window.scrollTo(0, Math.max(0, window.scrollY + element.getBoundingClientRect().top - inset));
    }, selector);
    const file = path.join(dir, name+'.png');
    await page.screenshot({path:file});
    screenshots.push({name:path.basename(file),mode:'actual-viewport',
      sha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')});
  }
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
      await surface.locator('a[href*="google_steps_source_id='+binding.selected+'"]').focus();
      await page.keyboard.press('Enter');
      await page.waitForURL(url => url.searchParams.get('google_steps_source_id')===binding.selected);
      const value = day => surface.locator('[data-google-steps-date="'+day+'"] [data-google-steps-value]');
      assert.equal((await value('2099-01-02').textContent()).trim(),'9223372036854775807');
      assert.equal((await value('2099-01-03').textContent()).trim(),'0');
      assert.equal(await surface.locator('[data-google-steps-state="missing"]').count(),1);
      assert.equal(await surface.locator('[data-google-steps-state="null"]').count(),1);
      assert.equal(await surface.locator('[data-google-steps-state="invalid"]').count(),2);
      assert.equal(await surface.locator('[data-google-steps-state="no_observation"]').count(),1);
      const garmin = page.locator('[data-steps-chart="garmin"]');
      assert.equal(await garmin.locator('[data-steps-total]').innerText(),'20800');
      assert.equal(await garmin.locator('[data-steps-mean]').innerText(),'5200.0');
      assert.match(await garmin.locator('[data-steps-scope]').innerText(),/4 из 7/);
      const chart = surface.locator('[data-steps-chart="google"]');
      assert.equal((await chart.locator('[data-steps-total]').innerText()).trim(),'9223372036854775807');
      assert.equal((await chart.locator('[data-steps-mean]').innerText()).trim(),'4611686018427387903.5');
      assert.match(await chart.locator('[data-steps-scope]').innerText(),/2 из 7.*полнота суток не подтверждена/);
      const rows = JSON.parse(await chart.locator('[data-steps-chart-data]').textContent());
      assert.equal(rows.find(row=>row.date==='2099-01-02').value,'9223372036854775807');
      assert.equal(rows.find(row=>row.date==='2099-01-03').value,'0');
      const details = surface.locator('.steps-daily-details');
      assert.equal(await details.getAttribute('open'),null);
      await chart.locator('svg').focus();
      await page.keyboard.press('Home');
      assert.equal(await chart.locator('[data-steps-selected-value]').innerText(),'9223372036854775807');
      await page.keyboard.press('ArrowRight');
      assert.equal(await chart.locator('[data-steps-selected-value]').innerText(),'0');
      await page.keyboard.press('ArrowRight');
      assert.equal(await chart.locator('[data-steps-selected-value]').innerText(),'Нет допустимого значения');
      await chart.locator('[data-steps-day]').selectOption({index:0});
      assert.equal(await chart.locator('[data-steps-selected-value]').innerText(),'9223372036854775807');
      const svg = chart.locator('svg');
      const box = await svg.boundingBox();
      await svg.click({position:{x:box.width*20/900,y:box.height/2}});
      assert.equal(await chart.locator('[data-steps-selected-value]').innerText(),'9223372036854775807');
      await details.locator('summary').first().focus(); await page.keyboard.press('Enter');
      assert.equal(await details.getAttribute('open'),'');
      await details.locator('details summary').first().click();
      assert.match(await details.innerText(),/Coverage \/ pagination \/ timezone \/ finality: unknown/);
      await details.locator('summary').first().click();
      await surface.scrollIntoViewIfNeeded();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth));
      await capture(page,'compact-partial-garmin-'+width,'[data-statistics-steps]');
      await capture(page,'compact-partial-google-'+width,'[data-google-steps]');
      await page.locator('select[name=period]').selectOption('30');
      await page.locator('#statistics-controls button[type=submit]').click();
      await page.waitForURL(url=>url.searchParams.get('period')==='30');
      assert.equal(new URL(page.url()).searchParams.get('google_steps_source_id'),binding.selected);
      assert.equal(await page.locator('[data-google-steps-date]').count(),30);
      assert.equal(await chart.locator('[data-steps-total]').innerText(),'18446744073709551614');
      assert.equal(await chart.locator('[data-steps-mean]').innerText(),'6148914691236517204.7');
      assert.match(await chart.locator('[data-steps-scope]').innerText(),/3 из 30/);
      await surface.locator('[data-google-steps-sources] > summary').click();
      await surface.locator('a[href*="google_steps_source_id='+binding.alternate+'"]').click();
      await page.waitForURL(url=>url.searchParams.get('google_steps_source_id')===binding.alternate);
      assert.equal((await page.locator('[data-google-steps-date="2099-01-02"] [data-google-steps-value]').textContent()).trim(),'88');
      await page.goto(root+'&google_steps_source_id='+binding.alternate);
      assert.equal(await chart.locator('[data-steps-total]').innerText(),'103');
      assert.equal(await chart.locator('[data-steps-mean]').innerText(),'14.7');
      assert.match(await chart.locator('[data-steps-scope]').innerText(),/7 из 7.*полнота суток не подтверждена/);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth));
      await capture(page,'compact-filled-garmin-'+width,'[data-statistics-steps]');
      await capture(page,'compact-filled-google-'+width,'[data-google-steps]');
      await page.goto(root+'&google_steps_source_id=unknown-source');
      assert.equal(await surface.locator('[data-google-steps-reason="source_not_evidenced"]').count(),1);
      assert.equal(await surface.locator('[data-steps-total]').count(),0);
      await capture(page,'compact-unselected-'+width,'[data-statistics-steps]');
      await page.goto(root+'&steps_period=all_time&garmin_source_id='+binding.garmin_source);
      assert.equal(await surface.count(),0);
      const history = page.locator('.statistics-steps-history');
      assert.equal(await history.locator('[data-steps-provider="google"][data-steps-history-state="unsupported_window"]').count(),1);
      assert.equal(await page.locator('.statistics-steps-panels--compact').count(),0);
      assert.equal(await history.locator('[data-steps-stat="total"]').innerText(),'20\u202f800');
      assert.equal(await history.locator('[data-steps-stat="mean"]').innerText(),'5\u202f200,0');
      const historyBox = await history.boundingBox();
      const sectionBox = await page.locator('[data-statistics-steps]').boundingBox();
      const garminBox = await history.locator('[data-steps-provider="garmin"]').boundingBox();
      assert.ok(historyBox.width >= sectionBox.width*.95);
      assert.ok(garminBox.width >= sectionBox.width*.4); // existing pair, never quarter-width
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth));
      await capture(page,'steps-all-time-'+width,'.statistics-steps-history');
      checks.push({width,keyboard_source:true,exact_int64:true,zero_and_nonvalues:true,
        disclosure:true,observed_sum_mean:true,day_keyboard_mouse:true,exact_count_strings:true,
        period_preserves_source:true,independent_family:true,no_page_overflow:true,
        explicit_source_no_fallback:true,all_time_disclosed:true,all_time_full_width:true,
        all_time_single_google_placeholder:true,viewport_captures:true});
      await page.close();
      const fallback = await browser.newPage({viewport:{width,height:1000},javaScriptEnabled:false});
      fallback.on('pageerror', e => errors.push(e.message));
      await fallback.route('**/*', route => {
        if (new URL(route.request().url()).origin !== base) {
          external.push(route.request().url()); return route.abort();
        }
        return route.continue();
      });
      await fallback.goto(root+'&google_steps_source_id='+binding.selected);
      const fallbackDetails = fallback.locator('[data-google-steps] .steps-daily-details');
      await fallbackDetails.locator('summary').first().click();
      assert.equal((await fallback.locator('[data-google-steps-date="2099-01-02"] [data-google-steps-value]').innerText()).trim(),'9223372036854775807');
      assert.ok(await fallback.evaluate(() => document.documentElement.scrollWidth<=innerWidth));
      await capture(fallback,'compact-no-js-'+width,'[data-google-steps] .steps-daily-details');
      await fallback.close();
      if (emptyBase) {
        const empty = await browser.newPage({viewport:{width,height:1000},locale:'ru-RU'});
        empty.on('pageerror', e => errors.push(e.message));
        await empty.route('**/*', route => {
          if (new URL(route.request().url()).origin !== emptyBase) {
            external.push(route.request().url()); return route.abort();
          }
          return route.continue();
        });
        await empty.goto(emptyBase+'/statistics?period=7&end_date=2099-01-08');
        assert.equal(await empty.locator('[data-steps-total]').count(),0);
        assert.equal(await empty.locator('[data-google-steps-reason="no_saved_source"]').count(),1);
        assert.ok(await empty.evaluate(() => document.documentElement.scrollWidth<=innerWidth));
        await capture(empty,'compact-empty-'+width,'[data-statistics-steps]');
        await empty.close();
      }
    }
    assert.deepEqual(errors,[]); assert.deepEqual(external,[]);
    fs.writeFileSync(path.join(dir,'result.json'),JSON.stringify({binding,browser:browser.version(),checks,screenshots,errors,external},null,2));
    console.log(JSON.stringify({checks,screenshots,errors,external},null,2));
  } finally { await browser.close(); }
})().catch(e=>{ console.error(e); process.exitCode=1; });
