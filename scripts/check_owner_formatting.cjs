/* Production display helpers, with no browser, providers or data writes. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = vm.createContext({window: {}});
for (const file of ['owner_dates.js', 'owner_formatting.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/healthcheck/web/static', file), 'utf8'), context);
}
const {number, plural, duration} = context.window.healthcheckOwnerFormat;
for (const [value, expected] of [[0, '0'], [1, '1'], [1000, '1\u202f000'], [-1000.25, '−1\u202f000,25'],
  [1.25, '1,25'], [1.000001, '1,000001'], [null, 'Не предоставлено'], [false, 'Не предоставлено']]) {
  assert.equal(number(value, 6), expected);
}
assert.equal(number(2.5, 1, true), '+2,5');
assert.equal(number(-0.001, 1, true), '0');
for (const [n, expected] of [[0, 'дней'], [1, 'день'], [2, 'дня'], [5, 'дней'], [11, 'дней'],
  [21, 'день'], [-21, 'день'], [1.5, 'дня'], [null, 'дней']]) {
  assert.equal(plural(n, 'день', 'дня', 'дней'), expected);
}
assert.equal(duration(3600), '1 ч 00 мин');
assert.equal(duration(3900), '1 ч 05 мин');
assert.equal(duration(0), '0 мин');
assert.equal(duration(null), 'Недоступно');
assert.equal(duration(0.01), '<1 мин');
assert.equal(context.window.healthcheckOwnerShortDate('2026-11-06'), '6 ноя');
assert.equal(context.window.healthcheckOwnerShortDate('2026-11-06', true), '6 ноя 2026');
assert.equal(context.window.healthcheckOwnerDate('2026-11-06T07:25:55.123400+03:00'), '6 ноября 2026, 07:25');
assert.equal(context.window.healthcheckOwnerDate('2026-11-06T07:25:55.123400+03:00', true), '6 ноября 2026, 07:25:55.123400 UTC+03:00');
console.log('Owner formatting checks passed');
