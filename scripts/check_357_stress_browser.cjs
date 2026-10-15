/* Desktop evidence over the real reader; all saved data are fabricated. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fixture = JSON.parse(fs.readFileSync(process.env.HEALTHCHECK_FIXTURE_IDENTITY, 'utf8'));
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const base = fixture.endpoint;
assert.match(base, /^http:\/\/127\.0\.0\.1:\d+$/);
assert.equal(fixture.synthetic, true);
assert.equal(fixture.sha, execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim());
for (const [name, digest] of Object.entries(fixture.loaded_files_sha256)) {
  assert.equal(crypto.createHash('sha256').update(fs.readFileSync(name)).digest('hex'), digest);
}
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE });
  const errors = [], external = [], checks = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    const page = await browser.newPage();
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin !== base) {
        external.push(route.request().url()); return route.abort();
      }
      return route.continue();
    });
    page.on('pageerror', error => errors.push(error.message));
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const name of Object.keys(fixture.sources)) {
        const query = new URLSearchParams({ start_date: '2099-01-01', end_date: fixture.selected_date,
          garmin_source_id: fixture.sources[name] });
        assert.equal((await page.goto(`${base}/brief?${query}`)).status(), 200);
        const card = page.locator('[data-overview-stress]');
        const text = await card.innerText();
        assert.match(text, /Выбранная дата · 29 января 2099/);
        assert.match(text, /1 января 2099 [—-] 28 января 2099/);
        if (['above', 'equal', 'zero'].includes(name)) {
          assert.match(text, /Среднее предыдущих 28 дней · 1 балл\./);
          assert.match(text, name === 'above' ? /На 1 балл\. выше среднего/
            : name === 'equal' ? /Совпадает со средним/ : /На 1 балл\. ниже среднего/);
        } else {
          assert.equal(await card.locator('[data-stress-mean]').count(), 0);
          assert.match(text, /Сравнение недоступно/);
          assert.match(text, name === 'early' ? /получены до окончания суток/
            : name === 'missing' ? /нет однозначного пригодного значения/ : /не менее 21/);
        }
        assert.equal(await card.locator('details').count(), 0);
        const geometry = await card.evaluate(el => ({
          bounds: el.getBoundingClientRect().toJSON(),
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
          clipped: [...el.querySelectorAll('strong, p')].filter(node => {
            const r = node.getBoundingClientRect();
            return r.width > 0 && (r.left < 0 || r.right > innerWidth + 1);
          }).map(node => node.textContent),
        }));
        assert.equal(geometry.overflow, false); assert.deepEqual(geometry.clipped, []);
        await card.screenshot({ path: path.join(evidence, `${name}-card-${width}.png`) });
        await page.screenshot({ path: path.join(evidence, `${name}-${width}.png`), fullPage: true });
        checks.push({ width, name, text, geometry });
      }
      const texts = [];
      for (const preset of ['7', '30', '90']) {
        await page.goto(`${base}/brief?preset=${preset}&garmin_source_id=${fixture.sources.above}`);
        texts.push(await page.locator('[data-overview-stress]').innerText());
      }
      assert.equal(texts[0], texts[1]); assert.equal(texts[1], texts[2]);
      checks.push({ width, name: 'preset-history-independent', presets: [7, 30, 90] });
      await page.goto(`${base}/brief?start_date=2099-01-01&end_date=2099-01-30&garmin_source_id=${fixture.sources.above}`);
      assert.match(await page.locator('[data-overview-stress]').innerText(), /Выбранная дата · 30 января 2099/);
      assert.equal(await page.locator('[data-stress-mean]').count(), 0);
      checks.push({ width, name: 'changed-end-no-fallback' });
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const result = { fixture, browser: browser.version(), checks, errors, external };
    fs.writeFileSync(path.join(evidence, 'overview-357-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({ sha: fixture.sha, browser: result.browser, cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
