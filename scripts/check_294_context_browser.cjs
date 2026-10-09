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
(async () => {
  const browser = await chromium.launch({ headless: true,
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
      const field = name => page.locator(`#context-form [name="${name}"]`);
      const text = `\n  Synthetic ${width} ё 日本語\n<script>window.contextXss=true</script>  `;
      await field('event_date').fill('2099-01-02');
      await field('original_text').fill(text);
      await field('event_time').fill('19:30');
      // Missing offset is a server validation error; escaped draft/key must survive.
      const operation = await field('operation_id').inputValue();
      await page.getByRole('button', { name: 'Добавить комментарий', exact: true }).focus();
      await Promise.all([page.waitForURL('**/context'), page.keyboard.press('Enter')]);
      await page.getByRole('alert').waitFor();
      assert.equal(await field('original_text').inputValue(), text);
      assert.equal(await field('operation_id').inputValue(), operation);
      await field('event_time').fill('');
      const beforeDouble = contextPosts;
      await Promise.all([page.waitForURL(/\/context\/[0-9a-f-]+\?saved=/),
        page.locator('#context-form').evaluate(form => { form.requestSubmit(); form.requestSubmit(); })]);
      assert.equal(contextPosts - beforeDouble, 1);
      const eventUrl = page.url().split('?')[0];
      assert.match(await page.getByRole('status').first().innerText(), /Сохранено/);
      assert.equal(await page.locator('.context-text').first().textContent(), text);
      assert.equal(await page.evaluate(() => window.contextXss), undefined);
      assert.match(await page.locator('.context-note').innerText(), /Только дата/);
      const staleForm = await page.locator('#context-form').evaluate(el => Object.fromEntries(new FormData(el)));
      // Revise and verify authoritative GET, reload, and history keyboard activation.
      await field('original_text').fill(`Synthetic corrected ${width}`);
      await field('event_time').fill('19:30');
      await field('offset').fill('+03:00');
      await field('timezone_name').fill('Europe/Moscow');
      await page.getByRole('button', { name: 'Сохранить исправление' }).focus();
      const oldRevision = await field('expected_revision_id').inputValue();
      await Promise.all([page.waitForURL(url => url.searchParams.get('saved') && url.searchParams.get('saved') !== oldRevision), page.keyboard.press('Enter')]);
      assert.match(await page.locator('.context-note').innerText(), /Версия 2/);
      assert.equal(await page.locator('.context-text').textContent(), `Synthetic corrected ${width}`);
      await page.reload();
      assert.match(await page.locator('.context-note').innerText(), /19:30\+03:00/);
      assert.equal(await field('original_text').inputValue(), `Synthetic corrected ${width}`);
      await page.getByRole('link', { name: 'История исправлений', exact: true }).focus();
      await Promise.all([page.waitForURL('**?history=1'), page.keyboard.press('Enter')]);
      assert.equal(await page.locator('.context-note').count(), 3);
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
      assert.match(await page.locator('.context-page').innerText(), new RegExp(`Synthetic corrected ${width}`));
      // Explicit now populates offset/zone; plain initial date keeps optional fields empty.
      assert.equal(await field('event_time').inputValue(), '');
      await page.getByRole('button', { name: 'Сейчас', exact: true }).focus();
      await page.keyboard.press('Enter');
      assert.match(await field('event_time').inputValue(), /^\d\d:\d\d$/);
      assert.equal(await field('offset').inputValue(), '+03:00');
      assert.equal(await field('timezone_name').inputValue(), 'Europe/Moscow');
      const geometry = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        navRows: new Set([...document.querySelector('.owner-nav').children].map(el => el.offsetTop)).size,
        background: getComputedStyle(document.body).backgroundColor,
        controls: [...document.querySelectorAll('#context-form input:not([type="hidden"]), #context-form textarea, #context-form button')]
          .filter(el => el.getBoundingClientRect().height).map(el => {
            const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, height: r.height };
          }),
      }));
      assert.equal(geometry.overflow, false); assert.equal(geometry.navRows, 1);
      assert.equal(geometry.background, 'rgb(246, 242, 233)');
      for (const c of geometry.controls) assert.ok(c.left >= 0 && c.right <= width + 1 && c.height >= 44);
      await page.screenshot({ path: path.join(evidence, `context-${width}.png`), fullPage: true });
      checks.push({ width, geometry, create: true, revise: true, validation: true,
        history: true, reload: true, stale: true, keyboard: true, doubleSubmit: true, now: true, xss: false });
      await page.close();
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const sha = execFileSync('git', ['-c', `safe.directory=${process.cwd().replaceAll('\\', '/')}`, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    fs.writeFileSync(path.join(evidence, 'context-browser.json'), JSON.stringify({ sha, browser: browser.version(), checks, errors, external }, null, 2));
    console.log(JSON.stringify({ sha, browser: browser.version(), cases: checks.length, errors, external }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
