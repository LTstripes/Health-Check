/* Live loopback desktop check for the saved-session detail (#345).
 * Starts at the real /garmin journal, follows a session link by keyboard,
 * asserts exact owner cards, the back-to-journal link and 1024/1440 geometry.
 * Synthetic profile only; every non-loopback request is blocked and recorded.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const base = process.env.HEALTHCHECK_BASE_URL || 'http://127.0.0.1:8120';
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const sourceId = process.env.HEALTHCHECK_ACTIVITY_SOURCE_ID;
const firstRecord = process.env.HEALTHCHECK_ACTIVITY_RECORD_ID;
const secondRecord = process.env.HEALTHCHECK_ACTIVITY_RECORD2_ID;
assert.ok(evidence && sourceId && firstRecord && secondRecord);
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1024, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin !== base) { external.push(url.origin); return route.abort(); }
        return route.continue();
      });
      const journal = await page.goto(`${base}/garmin?garmin_source_id=${sourceId}`);
      assert.equal(journal.status(), 200);
      assert.equal(await page.locator('a.activity-session-link').count() >= 2, true);
      const link = page.locator(`a.activity-session-link[href*="record_id=${firstRecord}"]`).first();
      assert.equal(await link.innerText(), 'Теннис');
      await page.screenshot({ path: path.join(evidence, `journal-${width}.png`), fullPage: true });

      // Keyboard: focus the session link, Enter opens the detail page.
      await link.focus();
      assert.equal(await link.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
      await Promise.all([page.waitForURL(/\/garmin\/session\?/), page.keyboard.press('Enter')]);
      assert.ok(page.url().includes(`record_id=${firstRecord}`));

      const cardText = async code =>
        (await page.locator(`[data-metric="${code}"]`).innerText()).replace(/\s+/g, ' ').trim();
      assert.equal((await page.locator('.owner-page-header h1').innerText()).trim(), 'Активность');
      assert.equal(await page.getByRole('link', { name: 'Активность', exact: true })
        .getAttribute('aria-current'), 'page');
      assert.equal(await page.locator('h2').filter({ hasText: 'Теннис' }).count() >= 1, true);
      assert.match(await cardText('duration_seconds'), /3901\.5 с/);
      assert.match(await cardText('duration_seconds'), /1 ч 5 мин 1\.5 с/);
      assert.match(await cardText('heart_rate_bpm'), /110\.0 уд\/мин/);
      assert.match(await cardText('max_heart_rate_bpm'), /165\.0 уд\/мин/);
      assert.match(await cardText('anaerobic_training_effect'), /1\.8 баллы/);
      assert.match(await cardText('distance_meters'), /Не предоставлено/);
      const geometry = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        navRows: new Set([...document.querySelector('.owner-nav').children]
          .map(el => el.offsetTop)).size,
        background: getComputedStyle(document.body).backgroundColor,
        cards: document.querySelectorAll('.activity-metric-card').length,
      }));
      assert.equal(geometry.overflow, false);
      assert.equal(geometry.navRows, 1);
      assert.equal(geometry.background, 'rgb(246, 242, 233)');
      assert.equal(geometry.cards, 7);
      await page.screenshot({ path: path.join(evidence, `detail-${width}.png`), fullPage: true });

      // Back to the journal preserves the exact source in the URL.
      const back = page.getByRole('link', { name: 'К журналу активности', exact: true });
      await back.focus();
      await Promise.all([page.waitForURL(/\/garmin\?garmin_source_id=/), page.keyboard.press('Enter')]);
      assert.ok(page.url().includes(`garmin_source_id=${sourceId}`));
      assert.ok(page.url().includes('#activity-journal'));
      assert.equal(await link.innerText(), 'Теннис');
      await page.screenshot({ path: path.join(evidence, `back-journal-${width}.png`), fullPage: true });

      // Second saved session: zero stays zero; absent typed evidence hides the cards.
      const second = await page.goto(
        `${base}/garmin/session?garmin_source_id=${sourceId}&record_id=${secondRecord}`);
      assert.equal(second.status(), 200);
      assert.match(await cardText('distance_meters'), /0\.0 м/);
      assert.equal(await page.locator('[data-metric="max_heart_rate_bpm"]').count(), 0);
      assert.equal(await page.locator('[data-metric="anaerobic_training_effect"]').count(), 0);
      await page.screenshot({ path: path.join(evidence, `detail-typed-absent-${width}.png`), fullPage: true });

      checks.push({ width, keyboard: true, cards: geometry.cards, typedExtrasHidden: true });
      await page.close();
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    const dirty = execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim();
    fs.writeFileSync(path.join(evidence, 'activity-detail-browser.json'), JSON.stringify(
      { sha, dirty, browser: browser.version(), mode: 'live-loopback-synthetic', base, checks, errors, external }, null, 2));
    console.log(JSON.stringify({ sha, dirty: Boolean(dirty), cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
