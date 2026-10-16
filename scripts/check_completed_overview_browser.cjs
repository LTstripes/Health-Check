/* Actual synthetic UI pixels and keyboard checks; external evidence only. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const root = path.resolve(__dirname, '..');
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
assert.ok(evidence && !path.resolve(evidence).startsWith(root));

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE });
  const errors = [], external = [], checks = [], images = [];
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
    const identity = await (await page.request.get(`${base}/__synthetic_identity`)).json();
    assert.equal(identity.synthetic, true);
    assert.equal(identity.sha, execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim());
    for (const [name, hash] of Object.entries(identity.source_hashes)) {
      assert.equal(sha256(fs.readFileSync(path.join(root, name))), hash, name);
    }
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const [name, query, duration, stress, battery, coverage] of [
        ['rolling7', 'preset=7', '6 ч 0 мин', '10 балл.', '60 балл.', '2/7'],
        ['rolling30', 'preset=30', '6 ч 0 мин', '10 балл.', '60 балл.', '2/30'],
        ['historical', 'start_date=2099-01-01&end_date=2099-01-01', '4 ч 0 мин', '0 балл.', '80 балл.', '1/1'],
        ['clipped', 'start_date=2099-01-01&end_date=2099-01-08', '6 ч 0 мин', '10 балл.', '60 балл.', '2/7'],
        ['missing', 'start_date=2099-01-04&end_date=2099-01-07', '—', '—', '—', '0/4'],
        ['today', 'start_date=2099-01-08&end_date=2099-01-08', '—', '—', '—', null],
      ]) {
        assert.equal((await page.goto(`${base}/brief?${query}`)).status(), 200);
        const sleep = page.locator('[data-overview-period-sleep]');
        const stressCard = page.locator('[data-overview-stress]');
        const bb = page.locator('[data-overview-body-battery]');
        assert.equal((await sleep.locator('.overview-value').innerText()).trim(), duration);
        assert.equal((await stressCard.locator(':scope > strong').innerText()).trim(), stress);
        assert.equal((await bb.locator('[data-bb-window] > strong').innerText()).trim(), battery);
        for (const card of [sleep, stressCard, bb]) {
          if (coverage) assert.ok((await card.locator('[data-period-coverage]').innerText()).startsWith(coverage));
          if (name === 'today') assert.match(await card.innerText(), /нет завершённых дней/);
          assert.doesNotMatch(await card.innerText(), /Выбранная дата|Максимум за сохранённый день|Сравнение недоступно|avgStressLevel|20 ч|100 балл/);
          const overflow = await card.evaluate(el => el.scrollWidth > el.clientWidth + 1);
          assert.equal(overflow, false, `${width}/${name}: card overflow`);
        }
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        const target = path.join(evidence, `${name}-${width}.png`);
        await page.screenshot({ path: target, fullPage: true });
        images.push({ file: target, sha256: sha256(fs.readFileSync(target)) });
        if (name === 'rolling7') {
          const summary = bb.locator('.overview-chart-values > summary');
          await summary.focus();
          await page.keyboard.press('Enter');
          assert.equal(await bb.locator('.overview-chart-values').getAttribute('open'), '');
          assert.match(await bb.locator('table').innerText(), /80[\s\S]*40/);
          await page.keyboard.press('Enter');
          assert.equal(await bb.locator('.overview-chart-values').getAttribute('open'), null);
        }
        checks.push({ width, name, duration, stress, battery, coverage });
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    fs.writeFileSync(path.join(evidence, 'receipt.json'), JSON.stringify({ identity, checks, images, errors, external }, null, 2));
    console.log(JSON.stringify({ checks: checks.length, images: images.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
