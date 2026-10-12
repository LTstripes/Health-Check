/* Real loopback Context UI, fresh synthetic profile. Desktop Chromium only. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
assert.ok(evidence);
const identity = () => {
  const git = args => execFileSync('git', ['-c', `safe.directory=${process.cwd().replaceAll('\\', '/')}`, ...args], { encoding: 'utf8' }).trim();
  return { sha: git(['rev-parse', 'HEAD']), tree: git(['rev-parse', 'HEAD^{tree}']), dirty: git(['status', '--porcelain']) };
};
(async () => {
  const candidate = identity();
  assert.equal(candidate.dirty, '', 'Browser checks require a clean committed candidate');
  const browser = await chromium.launch({ headless: process.env.HEALTHCHECK_BROWSER_HEADED !== '1',
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      { executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE } : {}) });
  const checks = [], errors = [], external = [];
  try {
    fs.mkdirSync(evidence, { recursive: true });
    for (const width of [1024, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, timezoneId: 'Europe/Moscow' });
      await page.route('**/*', route => {
        if (new URL(route.request().url()).origin !== base) {
          external.push(route.request().url()); return route.abort();
        }
        return route.continue();
      });
      page.on('pageerror', error => errors.push(error.message));
      let contextPosts = 0;
      page.on('request', request => {
        if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/context')) contextPosts++;
      });
      assert.equal((await page.goto(`${base}/context`)).status(), 200);
      // The shared primary tab is unique and follows the native link Tab order.
      for (const route of ['/brief', '/', '/sleep', '/garmin', '/statistics', '/imports', '/context']) {
        assert.equal((await page.goto(`${base}${route}`)).status(), 200);
        assert.equal(await page.locator('a[href="/context"]').count(), 1);
        const nav = page.locator('.owner-nav a');
        assert.equal(await nav.count(), 7);
        assert.equal(await nav.last().innerText(), 'Комментарии');
        assert.equal(await page.locator('.owner-nav [aria-current="page"]').getAttribute('href'), route);
        assert.equal(await page.locator('.owner-page-header a[href="/context"]').count(), 0);
      }
      await page.goto(`${base}/imports`);
      await page.locator('.owner-nav a[href="/imports"]').focus();
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('.owner-nav a[href="/context"]').evaluate(el => el === document.activeElement), true);
      const focus = await page.locator('.owner-nav a[href="/context"]').evaluate(el => {
        const s = getComputedStyle(el); return { style: s.outlineStyle, width: s.outlineWidth };
      });
      assert.equal(focus.style, 'solid'); assert.ok(parseFloat(focus.width) >= 2.5, 'visible outline after desktop scale rounding');
      await page.screenshot({ path: path.join(evidence, `nav-focus-${width}.png`), fullPage: true });
      await Promise.all([page.waitForURL('**/context'), page.keyboard.press('Enter')]);
      assert.equal(await page.locator('.owner-nav a.active[aria-current="page"]').innerText(), 'Комментарии');
      await page.locator('.owner-nav a[href="/context"]').focus();
      await page.keyboard.press('Shift+Tab');
      assert.equal(await page.locator('.owner-nav a[href="/imports"]').evaluate(el => el === document.activeElement), true);
      const field = name => page.locator(`#context-form [name="${name}"]`);
      const text = `\n  Synthetic ${width} ё 日本語\n<script>window.contextXss=true</script>  `;
      await field('event_date').fill('2099-01-02');
      await field('original_text').fill(text);
      await page.screenshot({ path: path.join(evidence, `date-only-${width}.png`), fullPage: true });
      await field('event_time').fill('19:30');
      // Missing zone is a server validation error; escaped draft/key must survive.
      const operation = await field('operation_id').inputValue();
      await page.getByRole('button', { name: 'Добавить комментарий', exact: true }).focus();
      await Promise.all([page.waitForURL('**/context'), page.keyboard.press('Enter')]);
      await page.getByRole('alert').waitFor();
      assert.equal(await page.locator('#context-form [name="offset"], #context-form [name="end_offset"]').count(), 0);
      assert.equal(await field('original_text').inputValue(), text);
      assert.equal(await field('operation_id').inputValue(), operation);
      await field('event_time').fill('');
      assert.equal(await page.locator('#context-zone').isVisible(), false);
      assert.equal(await page.locator('#context-form').evaluate(el => new FormData(el).has('timezone_name')), false);
      const beforeDouble = contextPosts;
      await Promise.all([page.waitForURL(/\/context\/[0-9a-f-]+\?saved=/),
        page.locator('#context-form').evaluate(form => { form.requestSubmit(); form.requestSubmit(); })]);
      assert.equal(contextPosts - beforeDouble, 1);
      assert.equal(await page.locator('.owner-nav a.active[aria-current="page"]').innerText(), 'Комментарии');
      const eventUrl = page.url().split('?')[0];
      assert.match(await page.getByRole('status').first().innerText(), /Сохранено/);
      assert.equal(await page.locator('.context-text').first().textContent(), text);
      assert.equal(await page.evaluate(() => window.contextXss), undefined);
      assert.match(await page.locator('.context-note').innerText(), /Только дата/);
      const staleForm = await page.locator('#context-form').evaluate(el => Object.fromEntries(new FormData(el)));
      // Revise and verify authoritative GET, reload, and history keyboard activation.
      await field('original_text').fill(`Synthetic corrected ${width}`);
      await field('event_time').fill('19:30');
      await field('timezone_name').selectOption('Europe/Moscow');
      await page.getByRole('button', { name: 'Сохранить исправление' }).focus();
      const oldRevision = await field('expected_revision_id').inputValue();
      await Promise.all([page.waitForURL(url => url.searchParams.get('saved') && url.searchParams.get('saved') !== oldRevision), page.keyboard.press('Enter')]);
      assert.match(await page.locator('.context-note').innerText(), /Версия 2/);
      assert.equal(await page.locator('.context-text').textContent(), `Synthetic corrected ${width}`);
      await page.reload();
      assert.match(await page.locator('.context-note').innerText(), /19:30\+03:00/);
      assert.equal(await field('original_text').inputValue(), `Synthetic corrected ${width}`);
      // Text-only revision retains exact source spelling/UTC rather than resolving again.
      await field('original_text').fill(`Synthetic text-only ${width}`);
      const previousRevision = await field('expected_revision_id').inputValue();
      await Promise.all([page.waitForURL(url => url.searchParams.get('saved') && url.searchParams.get('saved') !== previousRevision),
        page.getByRole('button', { name: 'Сохранить исправление' }).click()]);
      assert.match(await page.locator('.context-note').innerText(), /19:30\+03:00/);
      await page.getByRole('link', { name: 'История исправлений', exact: true }).focus();
      await Promise.all([page.waitForURL('**?history=1'), page.keyboard.press('Enter')]);
      assert.equal(await page.locator('.context-note').count(), 4);
      assert.match(await page.locator('.context-page').innerText(), /Предыдущая/);
      assert.equal(await page.evaluate(() => window.contextXss), undefined);
      await page.screenshot({ path: path.join(evidence, `history-${width}.png`), fullPage: true });
      // Stale browser POST fails closed, retaining the draft for comparison.
      const conflict = await page.evaluate(async ({ url, form }) => {
        form.original_text = 'Synthetic stale browser draft'; form.operation_id = crypto.randomUUID();
        const result = await fetch(url, { method: 'POST', body: new URLSearchParams(form) });
        return { status: result.status, text: await result.text() };
      }, { url: eventUrl, form: staleForm });
      assert.equal(conflict.status, 409); assert.match(conflict.text, /Synthetic stale browser draft/);
      await page.goto(`${base}/context?from_date=2099-01-02&to_date=2099-01-02`);
      assert.match(await page.locator('.context-page').innerText(), new RegExp(`Synthetic text-only ${width}`));
      // Explicit now proposes the actual browser zone; no offset/location lookup.
      assert.equal(await field('event_time').inputValue(), '');
      await page.getByRole('button', { name: 'Сейчас', exact: true }).focus();
      await page.keyboard.press('Enter');
      assert.match(await field('event_time').inputValue(), /^\d\d:\d\d$/);
      assert.equal(await field('timezone_name').inputValue(), 'Europe/Moscow');
      const geometry = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        navRows: new Set([...document.querySelector('.owner-nav').children].map(el => el.offsetTop)).size,
        background: getComputedStyle(document.body).backgroundColor,
        controls: [...document.querySelectorAll('#context-form input:not([type="hidden"]), #context-form select, #context-form textarea, #context-form button')]
          .filter(el => el.getBoundingClientRect().height).map(el => {
            const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, height: r.height };
          }),
      }));
      assert.equal(geometry.overflow, false); assert.equal(geometry.navRows, 1);
      assert.equal(geometry.background, 'rgb(246, 242, 233)');
      for (const c of geometry.controls) assert.ok(c.left >= 0 && c.right <= width + 1 && c.height >= 44);
      await page.screenshot({ path: path.join(evidence, `context-${width}.png`), fullPage: true });
      // Actual server DST gap and separately explicit start/end fold choices.
      await page.goto(`${base}/context`);
      await field('original_text').fill(`Synthetic DST draft ${width} 日本語`);
      await field('event_date').fill('2026-03-08');
      await field('event_time').fill('02:30');
      await field('timezone_name').selectOption('America/New_York');
      const dstOperation = await field('operation_id').inputValue();
      const submit = () => page.getByRole('button', { name: 'Добавить комментарий', exact: true }).click();
      await Promise.all([page.waitForResponse(r => r.request().method() === 'POST' && r.status() === 422), submit()]);
      await page.getByRole('alert').waitFor();
      assert.equal(await field('original_text').inputValue(), `Synthetic DST draft ${width} 日本語`);
      assert.equal(await field('operation_id').inputValue(), dstOperation);
      assert.equal(await page.locator('[data-fold]').count(), 0);
      await page.screenshot({ path: path.join(evidence, `dst-gap-${width}.png`), fullPage: true });
      await field('event_date').fill('2026-11-01');
      await field('event_time').fill('01:15');
      await page.locator('#context-form details summary').click();
      await field('end_date').fill('2026-11-01');
      await field('end_time').fill('01:45');
      await Promise.all([page.waitForResponse(r => r.request().method() === 'POST' && r.status() === 422), submit()]);
      await field('occurrence').waitFor();
      assert.equal(await field('end_occurrence').isVisible(), true);
      assert.equal(await field('occurrence').inputValue(), '');
      assert.equal(await field('end_occurrence').inputValue(), '');
      await page.screenshot({ path: path.join(evidence, `dst-fold-${width}.png`), fullPage: true });
      await field('occurrence').selectOption('first');
      // Browser required validation also prevents guessing the unchosen end occurrence.
      const beforeIncomplete = contextPosts;
      await submit();
      assert.equal(contextPosts, beforeIncomplete);
      await field('end_occurrence').selectOption('second');
      await Promise.all([page.waitForURL(/\/context\/[0-9a-f-]+\?saved=/), submit()]);
      assert.match(await page.locator('.context-note').innerText(), /01:15-04:00.*01:45-05:00/);
      assert.equal(await field('occurrence').inputValue(), 'first');
      assert.equal(await field('end_occurrence').inputValue(), 'second');
      await page.screenshot({ path: path.join(evidence, `dst-saved-${width}.png`), fullPage: true });
      // Changing a clock clears the old choice; typing in the other endpoint cannot revive it.
      await field('event_time').fill('01:20');
      await field('end_time').fill('01:50');
      assert.equal(await page.locator('[data-fold]').count(), 0);
      checks.push({ width, geometry, create: true, revise: true, validation: true,
        primaryNavigation: true, visibleFocus: true, tabEnterShiftTab: true, history: true, reload: true,
        stale: true, keyboard: true, doubleSubmit: true, now: true, dateOnlyOmission: true,
        dstGapDraft: true, explicitFoldEndpoints: true, textOnly: true, xss: false });
      await page.close();
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    assert.deepEqual(identity(), candidate, 'Candidate must remain unchanged during browser checks');
    fs.writeFileSync(path.join(evidence, 'context-browser.json'), JSON.stringify({ ...candidate, base, browser: browser.version(), checks, errors, external }, null, 2));
    console.log(JSON.stringify({ ...candidate, browser: browser.version(), cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
