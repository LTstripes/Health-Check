// Small offline desktop check over real route captures; no live server/provider.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fixtures = process.env.HEALTHCHECK_STATISTICS_FIXTURES_DIR;
const evidence = process.env.HEALTHCHECK_BROWSER_EVIDENCE_DIR;
assert.ok(fixtures && evidence);
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const base = 'http://127.0.0.1:8120';
(async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.HEALTHCHECK_BROWSER_EXECUTABLE ?
      {executablePath:process.env.HEALTHCHECK_BROWSER_EXECUTABLE} : {})});
  const checks=[], errors=[], external=[], pngs=[];
  fs.mkdirSync(evidence,{recursive:true});
  try {
    for (const width of [1024,1440]) {
      const page=await browser.newPage({viewport:{width,height:1000},javaScriptEnabled:false});
      page.on('pageerror',error=>errors.push(error.message));
      await page.route('**/*',route=>{
        const url=new URL(route.request().url());
        if(url.origin!==base){external.push(url.origin);return route.abort();}
        if(url.pathname==='/static/dashboard.css')return route.fulfill({contentType:'text/css',
          body:fs.readFileSync('src/healthcheck/web/static/dashboard.css','utf8')});
        assert.equal(url.pathname,'/statistics');
        const period=url.searchParams.get('period')||'30';
        assert.ok(['7','30','calendar_year','trailing365','year_to_date'].includes(period));
        return route.fulfill({contentType:'text/html; charset=utf-8',
          body:fs.readFileSync(path.join(fixtures,`steps-completed-${period}.html`),'utf8')});
      });
      await page.goto(`${base}/statistics?period=30&end_date=2099-01-10&calendar_year=2099`);
      const section=page.locator('[data-statistics-steps]');
      for(const [day,state,value] of [
        ['02','value','17'],['03','value','0'],['04','null','Недоступно'],
        ['05','missing','Недоступно'],['06','invalid','Недоступно'],['07','value','3'],
      ]){
        const row=section.locator(`[data-steps-date="2099-01-${day}"]`);
        assert.equal(await row.getAttribute('data-steps-state'),state);
        assert.equal((await row.locator('.statistics-steps-value').innerText()).trim(),value);
      }
      assert.match(await section.innerText(),/Последнее полученное значение/);
      assert.match(await section.innerText(),/окончательный итог не подтверждён/);
      assert.equal(await section.locator('[data-steps-date="2099-01-11"]').count(),0);
      const summary=section.locator('[data-steps-date="2099-01-07"] summary');
      await summary.focus();await page.keyboard.press('Enter');
      assert.equal(await summary.locator('..').getAttribute('open'),'');
      assert.match(await summary.locator('..').innerText(),/Europe\/Moscow/);
      assert.match(await summary.locator('..').innerText(),/unknown \/ unknown \/ unknown \/ unknown/);
      await page.keyboard.press('Enter');
      const table=section.locator('.statistics-steps-table');
      await table.focus();assert.equal(await table.evaluate(el=>el===document.activeElement),true);
      const geometry=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,
        navRows:new Set([...document.querySelector('.owner-nav').children].map(el=>el.offsetTop)).size}));
      assert.equal(geometry.overflow,false);assert.equal(geometry.navRows,1);
      const png=path.join(evidence,`steps-completed-${width}.png`);
      await section.screenshot({path:png});pngs.push({path:png,sha256:digest(png),width});
      // Preserve source/end-date controls across keyboard submission and period changes.
      const selected=await page.locator('[name="garmin_source_id"]').inputValue();
      await page.locator('[name="period"]').selectOption('7');
      await page.locator('.statistics-controls button[type="submit"]').focus();
      await Promise.all([page.waitForURL(url=>url.searchParams.get('period')==='7'),page.keyboard.press('Enter')]);
      assert.equal(await page.locator('[name="garmin_source_id"]').inputValue(),selected);
      assert.equal(await page.locator('[name="end_date"]').inputValue(),'2099-01-10');
      checks.push({width,geometry,keyboardDetails:true,keyboardTable:true,keyboardSubmit:true,
        exactSourceRetained:true,explicitRangeRetained:true,lateLowerValue:3});
      await page.close();
    }
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    const sha=execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
    const dirty=execFileSync('git',['status','--porcelain'],{encoding:'utf8'}).trim();
    const fixtureHashes=Object.fromEntries(['7','30'].map(period=>[
      `steps-completed-${period}.html`,digest(path.join(fixtures,`steps-completed-${period}.html`))]));
    fs.writeFileSync(path.join(evidence,'steps-browser.json'),JSON.stringify({sha,dirty,
      browser:browser.version(),mode:'offline-real-route-html',fixtureHashes,checks,pngs,errors,external},null,2));
    console.log(JSON.stringify({sha,dirty:Boolean(dirty),checks:checks.length,pngs,errors,external}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
