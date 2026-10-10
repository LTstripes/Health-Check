/* #189 Stage 7: real browser engines, production pages, isolated synthetic stores.
 * Run serve_owner_acceptance_fixture.py on four explicit loopback ports first:
 * populated (default), --empty, --unavailable, --read-errors. Each needs a fresh
 * external HEALTHCHECK_DATA_DIR named hc189s7-*. Set BASE/EMPTY/UNAVAILABLE/FAILURE
 * URLs through HEALTHCHECK_BROWSER_*_URL, plus HEALTHCHECK_BROWSER_EVIDENCE_DIR.
 * NODE_PATH exposes Playwright; HEALTHCHECK_BROWSER_ENGINE selects chromium
 * (default), firefox or webkit; HEALTHCHECK_BROWSER_* identifies URL/evidence.
 * No provider, import, confirmation or other write request is sent by this check.
 */
const { chromium, firefox, webkit } = require('playwright');
const assert = require('node:assert/strict');
const engine = process.env.HEALTHCHECK_BROWSER_ENGINE || 'chromium';
assert.ok(['chromium', 'firefox', 'webkit'].includes(engine), 'Supported browser engine required');
const browserType = {chromium, firefox, webkit}[engine];
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
function contrast(a, b) {
  const luminance = rgb => {
    const channels = rgb.match(/\d+/g).slice(0, 3).map(Number).map(v => {
      v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
    });
    return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
  };
  const [lighter, darker] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (lighter + .05) / (darker + .05);
}
// Since #343 the default /sleep view is the source timeline; the night-detail
// store/state checks below pin the retained legacy Garmin view explicitly.
const sections = [
  ['Обзор', '/brief?start_date=2099-01-01&end_date=2099-01-08'],
  ['Вес', '/'],
  ['Сон', '/sleep?view=garmin&wake_date=2099-01-02'],
  ['Активность', '/garmin?metric_code=stress_daily_average&start_date=2099-01-01&end_date=2099-01-08'],
  ['Данные', '/imports'],
  ['Сон', '/agreement'],
];
// Primary shell links in visual order for the navigation and Tab-order checks.
// Статистика joined the shell in #347; its page states have their own dedicated
// check, so the store-state matrix below keeps the original fixture sections.
const navSections = [
  ['Обзор', '/brief'], ['Вес', '/'], ['Сон', '/sleep'],
  ['Активность', '/garmin'], ['Статистика', '/statistics'], ['Данные', '/imports'],
];

(async () => {
  fs.mkdirSync(evidence, { recursive: true });
  const browser = await browserType.launch({ headless: true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ? {executablePath: process.env.HEALTHCHECK_BROWSER_EXECUTABLE} : {}) });
  const checks = [], errors = [], expectedHttpErrors = [], forbiddenRequests = [], unverified = [];
  const inducedFailures = new Set();
  let page;
  const frame = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  async function geometry(label) {
    await frame();
    const g = await page.evaluate(() => ({
      doc: document.documentElement.scrollWidth, view: innerWidth,
      rows: new Set([...document.querySelector('.owner-nav').children].map(el => el.offsetTop)).size,
      tables: [...document.querySelectorAll('table')].filter(el => el.getBoundingClientRect().height)
        .map(el => ({ display: getComputedStyle(el).display, wrapper: !!el.closest('.table-scroll') })),
      targets: [...document.querySelectorAll('.brand, .owner-nav a, main button, summary')]
        .filter(el => el.getBoundingClientRect().height).map(el => ({ text: el.textContent.trim().slice(0, 60), height: el.getBoundingClientRect().height, width: el.getBoundingClientRect().width })),
      background: getComputedStyle(document.body).backgroundColor,
      ink: getComputedStyle(document.body).color,
      type: getComputedStyle(document.body).fontFamily,
      heading: (() => {const s = getComputedStyle(document.querySelector('.owner-page-header h1')); return {font: s.fontFamily, size: s.fontSize, weight: s.fontWeight, transform: s.textTransform};})(),
      active: (() => {const s = getComputedStyle(document.querySelector('.owner-nav [aria-current]')); return {color: s.color, border: s.borderBottomColor, width: s.borderBottomWidth, weight: s.fontWeight, radius: s.borderRadius};})(),
      separator: getComputedStyle(document.querySelector('.owner-page-header')).borderBottomColor,
      surface: (() => {const el = document.createElement('span'); el.style.backgroundColor = 'var(--card)'; el.style.color = 'var(--muted)'; document.body.append(el); const s = getComputedStyle(el); const colors = {background: s.backgroundColor, muted: s.color}; el.remove(); return colors;})(),
      controls: [...document.querySelectorAll('button, input, select, table')].map(el => getComputedStyle(el).fontFamily),
      // A+ overview metric headings intentionally use --ink for their heading
      // link (accepted overview.css); every other body link uses --accent.
      links: [...document.querySelectorAll('main a:not(.button-link)')]
        .filter(el => el.getBoundingClientRect().height)
        .map(el => ({color: getComputedStyle(el).color, heading: !!el.closest('.overview-metric-heading h3')})),
    }));
    assert.ok(g.doc <= g.view + 1, label + ': ' + JSON.stringify(g));
    assert.equal(g.rows, 1, label);
    assert.equal(g.background, 'rgb(246, 242, 233)', label);
    assert.equal(g.ink, 'rgb(41, 45, 39)', label);
    assert.deepEqual(g.surface, {background: 'rgb(253, 251, 246)', muted: 'rgb(104, 108, 97)'}, label);
    assert.match(g.type, /Segoe UI.*sans-serif/, label);
    assert.deepEqual(g.heading, {font: 'Georgia, "Times New Roman", serif', size: '42px', weight: '400', transform: 'none'}, label);
    assert.deepEqual(g.active, {color: 'rgb(49, 88, 75)', border: 'rgb(49, 88, 75)', width: '2px', weight: '600', radius: '0px'}, label);
    assert.equal(g.separator, 'rgb(220, 220, 204)', label);
    assert.ok(g.controls.every(font => /Segoe UI.*sans-serif/.test(font)), label);
    assert.ok(g.links.every(link => link.color === (link.heading ? 'rgb(41, 45, 39)' : 'rgb(49, 88, 75)')), label + ': ' + JSON.stringify(g.links));
    for (const text of [g.ink, g.surface.muted, g.active.color]) {
      for (const bg of [g.background, g.surface.background, 'rgb(239, 238, 229)', 'rgb(230, 241, 239)']) {
        assert.ok(contrast(text, bg) >= 4.5, `${label}: text contrast ${text} on ${bg}`);
      }
    }
    assert.ok(contrast(g.active.color, g.background) >= 3, label + ': focus contrast');
    assert.ok(contrast('rgb(255, 255, 255)', g.active.color) >= 4.5, label + ': action text contrast');
    assert.ok(g.tables.every(table => table.display === 'table' && table.wrapper), label + ': ' + JSON.stringify(g.tables));
    assert.ok(g.targets.every(target => target.height >= 44 && target.width >= 44), label + ': ' + JSON.stringify(g.targets));
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
      // Establish keyboard modality even after pointer-operated page controls.
      await page.keyboard.press('Tab');
      await summary.focus();
      assert.equal(await summary.evaluate(el => getComputedStyle(el).outlineColor), 'rgb(49, 88, 75)', label + ': focus color');
      assert.equal(await summary.evaluate(el => getComputedStyle(el).outlineWidth), '3px', label + ': visible focus');
      await page.keyboard.press('Enter');
      assert.equal(await summary.evaluate(el => el.parentElement.open), !wasOpen, label);
      await page.keyboard.press('Space');
      assert.equal(await summary.evaluate(el => el.parentElement.open), wasOpen, label);
      assert.equal(await summary.evaluate(el => el === document.activeElement), true, label);
      // Leave all disclosures open together: exercise the full desktop evidence layout.
      if (!wasOpen) await page.keyboard.press('Enter');
      tested++;
    }
    await geometry(label + ' disclosed');
    await localScrolling(label);
    checks.push({label: label + ' keyboard disclosures', count: tested});
  }
  try {
    const context = await browser.newContext();
    await context.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
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

    // Windows WebKit can exclude even unstyled native links from Tab order.
    // Prove that engine limitation separately; never relabel it as a passed
    // sequential-focus check or alter production markup to work around it.
    let nativeLinksSkipped = false;
    if (engine === 'webkit') {
      await page.setContent('<a id="native-first" href="#target">link</a><button>button</button><input><main id="target">target</main>');
      await page.keyboard.press('Tab');
      nativeLinksSkipped = !await page.locator('#native-first').evaluate(el => el === document.activeElement);
    }

    for (const width of [1024, 1440]) {
      console.log(`Checking ${width}px navigation, populated/empty pages and request states`);
      await page.setViewportSize({width, height: 900});
      // Follow the actual primary links, including horizontal nav scrolling.
      await page.goto(base + '/brief');
      for (const [name, url] of navSections) {
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
      const skipFocused = await page.locator('.skip-link').evaluate(el => el === document.activeElement);
      if (!skipFocused && nativeLinksSkipped) {
        unverified.push({width, check: 'first Tab reaches skip link', reason: 'Windows WebKit also skips an unstyled native link; full link Tab navigation is unavailable in this engine configuration'});
        await page.locator('.skip-link').focus();
      } else assert.equal(skipFocused, true);
      if (skipFocused) {
        for (const name of ['Health-Check', 'Обзор', 'Вес', 'Сон', 'Активность', 'Статистика', 'Данные']) {
          await page.keyboard.press('Tab');
          assert.equal(await page.evaluate(() => document.activeElement.textContent.trim()), name, `${width}: shell Tab order`);
          assert.equal(await page.evaluate(() => getComputedStyle(document.activeElement).outlineWidth), '3px', `${width}: shell visible focus`);
        }
        await page.locator('.skip-link').focus();
      }
      await page.keyboard.press('Enter');
      assert.equal(await page.locator('main').evaluate(el => el === document.activeElement), true);
      checks.push(`${width}: six real nav links, brand and keyboard skip activation${skipFocused ? ', first Tab focus' : '; first Tab focus UNVERIFIED'}`);

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
            if (name === 'Активность') assert.equal(await page.locator('#activity-a option[value]:not([value=""])').count(), 0);
          }
          await page.evaluate(() => scrollTo(0, 0));
          await page.screenshot({path: path.join(evidence, `${store}-${index}-${width}.png`), fullPage: true});
          await disclosures(label);
          if (store === 'populated' && name === 'Активность') {
            const ids = await page.locator('#activity-a option').evaluateAll(options => options.map(o => o.value).filter(Boolean));
            await page.locator('#activity-a').selectOption(ids[0]);
            await page.locator('#activity-b').selectOption(ids[1]);
            await page.locator('#activity-form button').click();
            await page.waitForFunction(() => document.querySelector('#activity-result').getAttribute('aria-busy') === 'false');
            assert.match(await page.locator('#activity-result').innerText(), /Сравнение сессий: B минус A/);
            assert.deepEqual(await page.locator('#activity-result thead th').allTextContents(), ['Показатель', 'A', 'B', 'B − A', '% к A']);
            await geometry(label + ' comparison'); await localScrolling(label + ' comparison');
            await page.locator('[data-activity-mode="training-recovery"]').click();
            await page.waitForFunction(() => document.querySelector('#activity-journal').hidden);
            assert.equal(await page.locator('#activity-journal').isVisible(), false);
            assert.ok(await page.locator('#series-chart svg circle').count());
            await page.locator('.activity-lags > summary').click();
            await page.locator('#lag-form button').click();
            await page.waitForFunction(() => document.querySelector('#lag-result').getAttribute('aria-busy') === 'false');
            await geometry(label + ' training'); await localScrolling(label + ' training');
          }
          checks.push(label + ': rendering, states, desktop layout, open evidence');
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
      for (const url of ['/brief?preset=invalid', '/sleep?view=garmin&wake_date=invalid', '/garmin?start_date=invalid', '/garmin?garmin_source_id=stage7-unknown', '/imports/stage7-unknown']) {
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
    const result = {status: unverified.length ? 'PASS_WITH_LIMITATIONS' : 'PASS', candidate, engine, browser: browser.version(), widths: [1024, 1440], checks, errors, expectedHttpErrors, forbiddenRequests, unverified};
    fs.writeFileSync(path.join(evidence, 'owner-stage7-browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify({status: result.status, engine, browser: result.browser, checks: checks.length, errors, expectedHttpErrors: expectedHttpErrors.length, unverified}, null, 2));
  } catch (error) {
    if (page) await page.screenshot({path: path.join(evidence, 'failure.png')}).catch(() => {});
    fs.writeFileSync(path.join(evidence, 'owner-stage7-browser-failure.json'), JSON.stringify({status: 'FAIL', candidate, engine, browser: browser.version(), message: error.message, url: page?.url(), checks, errors, unverified}, null, 2));
    throw error;
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
