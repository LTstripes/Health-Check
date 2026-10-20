/* Synthetic desktop acceptance over the actual loopback UI and shared service. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.HEALTHCHECK_BROWSER_BASE_URL;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
const fixture = process.env.HEALTHCHECK_LAB_FIXTURE_DIR;
if (!base || !evidence || !fixture || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) {
  throw Error('Explicit loopback URL, external synthetic fixture/evidence paths required');
}
(async () => {
  const browser = await chromium.launch({ headless: true });
  const checks = [], errors = [];
  fs.mkdirSync(evidence, { recursive: true });
  const binding = JSON.parse(fs.readFileSync(path.join(fixture, 'server.json'), 'utf8'));
  try {
    const page = await browser.newPage({ locale: 'ru-RU', viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + '/labs');
    await page.locator('input[name=pdf]').setInputFiles(path.join(fixture, 'synthetic.pdf'));
    await page.locator('input[name=draft]').setInputFiles(path.join(fixture, 'synthetic.json'));
    await page.getByRole('button', { name: 'Загрузить в staging для проверки' }).click();
    await page.waitForURL('**/labs/review/**');
    const initial = page.url();
    await assert.equal(await page.getByRole('table').count(), 1);
    await assert.equal(await page.locator('#lab-decision input[name=ack]').isChecked(), false);
    assert.match(await page.locator('main').innerText(), /страница неизвестна/);
    checks.push('Upload produces unconfirmed review with unknown metadata and unverified source match');
    await page.getByText('Исправить поля / подготовить новую полную версию', { exact: true }).click();
    await page.getByText('r1 · Synthetic Marker', { exact: true }).click();
    await page.locator('[name="rows.0.result_raw"]').fill('< 0,0300');
    await page.locator('[name="rows.0.decimal"]').fill('0.0300');
    await page.getByRole('button', { name: 'Сохранить исправленный черновик' }).click();
    await page.waitForURL(url => url.href !== initial && url.pathname.startsWith('/labs/review/'));
    assert.match(await page.locator('main').innerText(), /0,0300/);
    const corrected = page.url();
    await page.locator('input[name=selected][value=r3]').uncheck();
    await page.locator('#lab-decision input[name=partial]').check();
    await page.locator('#lab-decision input[name=ack]').check();
    await page.getByRole('button', { name: 'Подтвердить выбранные результаты' }).click();
    await page.getByRole('status').waitFor();
    assert.match(await page.locator('main').innerText(), /частичный/);
    checks.push('Correction creates fresh staged draft; explicit partial confirmation accepts selected rows');
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('link', { name: 'Скачать оригинал PDF', exact: true }).click();
    const download = await downloadEvent;
    const downloaded = path.join(evidence, 'downloaded-original.pdf');
    await download.saveAs(downloaded);
    assert.deepEqual(fs.readFileSync(downloaded), fs.readFileSync(path.join(fixture, 'synthetic.pdf')));
    checks.push('Original attachment is byte-identical');
    // The initial, unused interpretation still holds the complete original snapshot.
    await page.goto(initial);
    assert.match(await page.locator('main').innerText(), /Сохранены: r2/);
    assert.match(await page.locator('main').innerText(), /Изменены: r1/);
    assert.match(await page.locator('main').innerText(), /Добавлены: r3/);
    await page.locator('#lab-decision input[name=ack]').check();
    await page.getByRole('button', { name: /Revise report/ }).click();
    await page.getByRole('status').waitFor();
    checks.push('Full snapshot Revise shows retained/changed/added rows and uses separate explicit acceptance');
    await page.goto(corrected);
    assert.match(await page.locator('main').innerText(), /уже использован/);
    assert.equal(await page.locator('#lab-decision').count(), 0);
    checks.push('Consumed interpretation cannot append another confirmation');
    for (const width of [1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(initial);
      const geometry = await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth > innerWidth + 1,
        navRows: new Set([...document.querySelector('.owner-nav').children].map(x => x.offsetTop)).size }));
      assert.equal(geometry.overflow, false, JSON.stringify(geometry));
      assert.equal(geometry.navRows, 1, JSON.stringify(geometry));
      await page.screenshot({ path: path.join(evidence, `review-${width}.png`), fullPage: true });
      await page.goto(base + '/labs');
      await page.screenshot({ path: path.join(evidence, `list-${width}.png`), fullPage: true });
      checks.push(`Desktop review/list ${width}px without document overflow or wrapped navigation`);
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(evidence, 'browser.json'), JSON.stringify({ status: 'PASS', binding,
      browser: browser.version(), checks, errors }, null, 2));
    console.log(JSON.stringify({ status: 'PASS', checks, browser: browser.version(), binding }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
