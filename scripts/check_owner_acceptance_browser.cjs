/* #189 Stage 7: real Chromium, production pages, isolated populated/empty stores.
 * Run serve_owner_acceptance_fixture.py on four explicit loopback ports first:
 * populated (default), --empty, --unavailable, --read-errors. Each needs a fresh
 * external HEALTHCHECK_DATA_DIR named hc189s7-*. Set BASE/EMPTY/UNAVAILABLE/FAILURE
 * URLs through HEALTHCHECK_BROWSER_*_URL, plus HEALTHCHECK_BROWSER_EVIDENCE_DIR.
 * NODE_PATH exposes Playwright; HEALTHCHECK_BROWSER_* identifies URL/evidence.
 * No provider, import, confirmation or other write request is sent by this check.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const empty = process.env.HEALTHCHECK_BROWSER_EMPTY_URL;
const unavailable = process.env.HEALTHCHECK_BROWSER_UNAVAILABLE_URL;
const failed = process.env.HEALTHCHECK_BROWSER_FAILURE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
for (const url of [base, empty, unavailable, failed]) assert.match(url || '', /^http:\/\/127\.0\.0\.1:\d+$/);
assert.ok(evidence, 'Explicit external evidence directory required');
function candidateIdentity() {
  const git = args => execFileSync('git', args, {cwd: path.join(__dirname, '..'), encoding: 'utf8'}).trim();
  return {sha: git(['rev-parse', 'HEAD']), tree: git(['rev-parse', 'HEAD^{tree}']),
    trackedChanges: git(['diff', '--name-only', 'HEAD']), untracked: git(['ls-files', '--others', '--exclude-standard'])};
}
const candidate = candidateIdentity();
const sections = [
  ['Обзор', '/brief?start_date=2099-01-01&end_date=2099-01-08'],
  ['Вес', '/'],
  ['Сон', '/sleep?wake_date=2099-01-02'],
  ['Активность', '/garmin?metric_code=stress_daily_average&start_date=2099-01-01&end_date=2099-01-08'],
  ['Данные', '/imports'],
  ['Сон', '/agreement'],
];

(async () => {
  fs.mkdirSync(evidence, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ? {executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE} : {}) });
  const checks = [], errors = [], expectedHttpErrors = [], forbiddenRequests = [];
  const inducedFailures = new Set();
  let page;
  const frame = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  async function geometry(label) {
    await frame();
    const g = await page.evaluate(() => ({
      doc: document.documentElement.scrollWidth, view: innerWidth,
      rows: new Set([...document.querySelector('.owner-nav').children].map(el => el.offsetTop)).size,
      grids: [...document.querySelectorAll('.grid, .data-provider-grid, .brief-overview-list')]
        .filter(el => el.getBoundingClientRect().height)
        .map(el => ({ cls: el.className, columns: getComputedStyle(el).gridTemplateColumns.split(' ').length })),
      tables: [...document.querySelectorAll('table')].filter(el => el.getBoundingClientRect().height)
        .map(el => ({ display: getComputedStyle(el).display, wrapper: !!el.closest('.table-scroll') })),
      targets: [...document.querySelectorAll('.owner-nav a, main button, summary')]
        .filter(el => el.getBoundingClientRect().height).map(el => ({ text: el.textContent.trim().slice(0, 60), height: el.getBoundingClientRect().height })),
      background: getComputedStyle(document.body).backgroundColor,
      links: [...document.querySelectorAll('main a:not(.button-link)')]
        .filter(el => el.getBoundingClientRect().height).map(el => getComputedStyle(el).color),
    }));
    assert.ok(g.doc <= g.view + 1, label + ': ' + JSON.stringify(g));
    assert.equal(g.rows, 1, label);
    assert.equal(g.background, 'rgb(243, 241, 236)', label);
    assert.ok(g.links.every(color => color === 'rgb(31, 92, 87)'), label + ': ' + JSON.stringify(g.links));
    if (g.view <= 800) assert.ok(g.grids.every(grid => grid.columns === 1), label + ': ' + JSON.stringify(g.grids));
    assert.ok(g.tables.every(table => table.display === 'table' && table.wrapper), label + ': ' + JSON.stringify(g.tables));
    assert.ok(g.targets.every(target => target.height >= 44), label + ': ' + JSON.stringify(g.targets));
  }
  async function localScrolling(label) {
    const scrolls = await page.locator('.table-scroll, .chart, .agreement-chart').evaluateAll(elements => elements
      .filter(el => el.getBoundingClientRect().height && el.scrollWidth > el.clientWidth + 1)
      .map(el => {
        const before = el.scrollLeft; el.scrollLeft = el.scrollWidth;
        const moved = el.scrollLeft > before;
        const result = {cls: el.className, moved, overflow: getComputedStyle(el).overflowX};
        el.scrollLeft = 0; return result;
      }));
    assert.ok(scrolls.every(el => el.moved && ['auto', 'scroll'].includes(el.overflow)), label + ': ' + JSON.stringify(scrolls));
    checks.push({ label: label + ' local scrolling', regions: scrolls });
  }
  async function settled() {
    if (await page.locator('#data-results').count()) {
      await page.waitForFunction(() => document.querySelector('#data-results').getAttribute('aria-busy') === 'false' && document.querySelector('#data-feedback').textContent.trim());
    }
  }
  async function disclosures(label) {
    const summaries = page.locator('details > summary');
    let tested = 0;
    for (let i = 0; i < await summaries.count(); i++) {
      const summary = summaries.nth(i);
      if (!await summary.isVisible()) continue;
      const wasOpen = await summary.evaluate(el => el.parentElement.open);
      await summary.focus();
      await page.keyboard.press('Enter');
      assert.equal(await summary.evaluate(el => el.parentElement.open), !wasOpen, label);
      await page.keyboard.press('Space');
      assert.equal(await summary.evaluate(el => el.parentElement.open), wasOpen, label);
      assert.equal(await summary.evaluate(el => el === document.activeElement), true, label);
      // Leave all disclosures open together: exercise the worst responsive layout.
      if (!wasOpen) await page.keyboard.press('Enter');
      tested++;
    }
    await geometry(label + ' disclosed');
    await localScrolling(label);
    checks.push({label: label + ' keyboard disclosures', count: tested});
  }
  try {
    const context = await browser.newContext();
    await context.route('**/favicon.ico', route => route.fulfill({status: 204}));
    context.on('request', request => {
      const url = new URL(request.url());
      if (url.hostname !== '127.0.0.1' || !['GET', 'HEAD'].includes(request.method())) {
        forbiddenRequests.push({url: request.url(), method: request.method()});
      }
    });
    page = await context.newPage();
    page.on('pageerror', error => errors.push({type: 'pageerror', message: error.message, url: page.url()}));
    page.on('console', message => {
      if (message.type() !== 'error') return;
      const item = {type: 'console', message: message.text(), url: message.location().url};
      const unavailableFreshness = item.url.startsWith(unavailable + '/api/source-freshness?') &&
        item.message.includes('status of 503');
      if ((inducedFailures.has(item.url) || unavailableFreshness) && /Failed to load resource/.test(item.message)) expectedHttpErrors.push(item);
      else errors.push(item);
    });

    for (const width of [1100, 800, 390]) {
      console.log(`Checking ${width}px navigation, populated/empty pages and request states`);
      await page.setViewportSize({width, height: 900});
      // Follow the actual primary links, including horizontal nav scrolling.
      await page.goto(base + '/brief');
      for (const [name, url] of sections.slice(0, 5)) {
        await page.locator('.owner-nav').getByRole('link', {name, exact: true}).click();
        await settled();
        assert.equal(await page.locator('h1').innerText(), name);
        assert.equal(await page.locator('.owner-nav [aria-current="page"]').innerText(), name);
        assert.equal(new URL(page.url()).pathname, new URL(url, base).pathname);
        await geometry(`${width} ${name} navigation`);
      }
      await page.locator('.brand').click();
      assert.equal(new URL(page.url()).pathname, '/brief');
      // Real first-tab skip link transfers focus to the content.
      await page.goto(base + '/brief');
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('.skip-link').evaluate(el => el === document.activeElement), true);
      await page.keyboard.press('Enter');
      assert.equal(await page.locator('main').evaluate(el => el === document.activeElement), true);
      checks.push(`${width}: five real nav links, brand and keyboard skip link`);

      for (const [store, origin] of [['populated', base], ['empty', empty]]) {
        for (const [index, [name, url]] of sections.entries()) {
          const label = `${width} ${store} ${name} ${url.split('?')[0]}`;
          assert.equal((await page.goto(origin + url)).status(), 200, label);
          await settled();
          assert.equal(await page.locator('html').getAttribute('lang'), 'ru');
          assert.equal(await page.locator('h1').innerText(), name);
          assert.equal(await page.locator('.owner-nav [aria-current]').innerText(), name);
          assert.equal(await page.locator('main [lang="en"]').count(), 0);
          assert.equal(await page.locator('main details.owner-details[open], .brief-provenance[open]').count(), 0);
          await geometry(label);
          if (store === 'empty') {
            const text = await page.locator('main').innerText();
            assert.match(text, /нет|Нет|недоступ|не определ|неизвест|не готов|не найден/);
            if (name === 'Вес') assert.doesNotMatch(await page.locator('.hero').innerText(), /(^|\s)0(?:\.0)? кг/);
            if (name === 'Сон') assert.doesNotMatch(text, /(^|\s)0(?:\.0)? (?:баллы|с|ч)/);
            if (name === 'Активность') assert.equal(await page.locator('#activity-ids option').count(), 0);
          }
          await page.evaluate(() => scrollTo(0, 0));
          await page.screenshot({path: path.join(evidence, `${store}-${index}-${width}.png`)});
          await disclosures(label);
          if (store === 'populated' && name === 'Активность') {
            await page.locator('#activity-form button').click();
            await page.waitForFunction(() => document.querySelector('#activity-result').getAttribute('aria-busy') === 'false');
            assert.match(await page.locator('#activity-result').innerText(), /Сопоставлено/);
            await geometry(label + ' comparison'); await localScrolling(label + ' comparison');
            await page.locator('[data-activity-mode="training-recovery"]').click();
            await page.waitForFunction(() => document.querySelector('#activity-journal').hidden);
            assert.equal(await page.locator('#activity-journal').isVisible(), false);
            assert.ok(await page.locator('#series-chart svg circle').count());
            await page.locator('#lag-form button').click();
            await page.waitForFunction(() => document.querySelector('#lag-result').getAttribute('aria-busy') === 'false');
            await geometry(label + ' training'); await localScrolling(label + ' training');
          }
          checks.push(label + ': rendering, states, responsive layout, open evidence');
        }
      }

      // Exercise actual fail-closed backend paths, rather than a fake HTML error.
      for (const [name, url] of sections) {
        const failureUrl = failed + url;
        inducedFailures.add(failureUrl);
        assert.equal((await page.goto(failureUrl)).status(), 500, `${name} read failure`);
        assert.match(await page.getByRole('alert').innerText(), /Не удалось/);
        assert.doesNotMatch(await page.getByRole('alert').innerText(), /request failed|synthetic Stage-7/);
        assert.equal(await page.locator('main details[open]').count(), 0);
        await geometry(`${width} ${name} backend read error`);
        await disclosures(`${width} ${name} backend read error`);
        if (name === 'Обзор') inducedFailures.add(unavailable + url);
        const unavailableResponse = await page.goto(unavailable + url);
        assert.equal(unavailableResponse.status(), name === 'Обзор' ? 503 : 200, `${name} uninitialized store`);
        await settled();
        const text = await page.locator('main').innerText();
        assert.match(text, /не готов|недоступ|не определ|неизвест/);
        if (name === 'Данные') {
          assert.match(text, /Число кандидатов неизвестно/);
          assert.doesNotMatch(text, /Загрузок пока нет|В последних загрузках нет кандидатов/);
        }
        await geometry(`${width} ${name} unavailable store`);
        checks.push(`${width} ${name}: real read-failure handler and unavailable-store state`);
      }

      // Server-rendered pages keep their applied URL until a delayed response commits.
      for (const [name, url] of sections.filter(([name]) => ['Обзор', 'Вес', 'Сон'].includes(name))) {
        await page.goto(base + url);
        const appliedUrl = page.url();
        const target = base + url + (url.includes('?') ? '&' : '?') + 'stage7_delay=1';
        let release, seen;
        const gate = new Promise(resolve => {release = resolve;});
        const arrived = new Promise(resolve => {seen = resolve;});
        await page.route(target, async route => {seen(); await gate; await route.continue();});
        const navigation = page.goto(target);
        await Promise.race([arrived, navigation.then(() => {throw new Error('Delayed route was not intercepted');})]);
        assert.equal(page.url(), appliedUrl, `${name} does not commit a new document while loading`);
        release(); await navigation; await page.unroute(target);
      }

      // Shared real validation/error documents at every viewport.
      for (const url of ['/brief?preset=invalid', '/sleep?wake_date=invalid', '/garmin?start_date=invalid', '/garmin?garmin_source_id=stage7-unknown', '/imports/stage7-unknown']) {
        inducedFailures.add(base + url);
        const response = await page.goto(base + url);
        assert.ok(response.status() >= 400, url + ' must reject invalid input');
        assert.equal(await page.getByRole('alert').isVisible(), true, url);
        assert.doesNotMatch(await page.getByRole('alert').innerText(), /preset must|request could not be parsed|request failed|not found|unknown import batch/, 'Owner error copy must be Russian');
        await geometry(`${width} error ${url}`);
      }

      // Data loading/failure/recovery retains the import surface and clears clocks.
      await page.goto(base + '/imports'); await settled();
      const packet = await (await page.request.get(base + '/api/source-freshness?evaluated_at_utc=2099-01-09T12:00:00Z&evaluation_local_date=2099-01-09')).json();
      let release, seen;
      const gate = new Promise(resolve => {release = resolve;});
      const arrived = new Promise(resolve => {seen = resolve;});
      await page.route('**/api/source-freshness?**', async route => {seen(); await gate; await route.fulfill({json: packet});});
      await page.locator('#data-refresh').click(); await arrived;
      assert.equal(await page.locator('#data-results').getAttribute('aria-busy'), 'true');
      assert.equal(await page.locator('[data-provider]').count(), 0);
      assert.equal(await page.locator('#data-clock').innerText(), '');
      assert.equal(await page.locator('#data-refresh').isDisabled(), true);
      await geometry(`${width} Data loading`); release(); await settled();
      await page.unroute('**/api/source-freshness?**');
      await page.route('**/api/source-freshness?**', route => {
        inducedFailures.add(route.request().url()); return route.fulfill({status: 503, json: {code: 'synthetic_unavailable'}});
      });
      await page.locator('#data-refresh').click(); await settled();
      assert.equal(await page.locator('#data-feedback').getAttribute('role'), 'alert');
      assert.equal(await page.locator('[data-provider]').count(), 0);
      assert.equal(await page.locator('#import-files').isVisible(), true);
      await geometry(`${width} Data failed`);
      await page.unroute('**/api/source-freshness?**');
      await page.locator('#data-refresh').click(); await settled();
      assert.equal(await page.locator('#data-feedback').getAttribute('role'), 'status');
      checks.push(`${width}: server navigation loading; five real validation/error routes; Data loading/error/retry`);
    }
    assert.deepEqual(forbiddenRequests, [], 'Only local read requests permitted');
    assert.deepEqual(errors, [], 'No unexpected console or JavaScript errors');
    assert.deepEqual(candidateIdentity(), candidate, 'Candidate must remain unchanged during verification');
    const result = {status: 'PASS', candidate, browser: browser.version(), widths: [1100, 800, 390], checks, errors, expectedHttpErrors, forbiddenRequests};
    fs.writeFileSync(path.join(evidence, 'owner-stage7-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({status: result.status, browser: result.browser, checks: checks.length, errors, expectedHttpErrors: expectedHttpErrors.length}, null, 2));
  } catch (error) {
    if (page) await page.screenshot({path: path.join(evidence, 'failure.png')}).catch(() => {});
    fs.writeFileSync(path.join(evidence, 'owner-stage7-browser-failure.json'), JSON.stringify({status: 'FAIL', message: error.message, url: page?.url(), checks, errors}, null, 2));
    throw error;
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
