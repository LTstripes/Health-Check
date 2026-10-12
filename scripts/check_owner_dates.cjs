/* Pure regressions against the production helper; Date normalization is forbidden. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const missing = 'Дата не указана';
const invalidLabel = 'Некорректная дата/время';
const valid = [
  ['2026-01-02', '2 января 2026'],
  ['2024-02-29', '29 февраля 2024'],
  ['2000-02-29', '29 февраля 2000'],
  ['2400-02-29', '29 февраля 2400'],
  ['0001-01-01', '1 января 0001'],
  ['0004-02-29', '29 февраля 0004'],
  ['9999-12-31', '31 декабря 9999'],
  ['9999-12-31T23:59:59-23:59', '31 декабря 9999, 23:59:59 UTC-23:59', true],
  ['0001-01-01T00:00:00+23:59', '1 января 0001, 00:00:00 UTC+23:59', true],
  ['2026-04-30', '30 апреля 2026'],
  ['2026-12-31T23:59:59.123400Z', '31 декабря 2026, 23:59:59.123400 UTC', true],
  ['2026-01-02T00:00', '2 января 2026, 00:00'],
  ['2026-01-02T00:00:00.000000+00:00', '2 января 2026, 00:00:00.000000 UTC', true],
  ['2026-01-02T00:15+14:00', '2 января 2026, 00:15 UTC+14:00'],
  ['2026-01-02T23:15-11:00', '2 января 2026, 23:15 UTC-11:00'],
  ['2026-01-02T00:15:00+05:45', '2 января 2026, 00:15:00 UTC+05:45', true],
  ['2026-01-02T19:30:10.123400+03:00', '2 января 2026, 19:30 UTC+03:00'],
  ['2026-01-02T19:30:10.123400+03:00', '2 января 2026, 19:30:10.123400 UTC+03:00', true],
  ['2026-03-08T01:30-05:00', '8 марта 2026, 01:30 UTC-05:00'],
  ['2026-03-08T03:30-04:00', '8 марта 2026, 03:30 UTC-04:00'],
  ['2026-01-02T23:59:59+23:59', '2 января 2026, 23:59:59 UTC+23:59', true],
  ['2026-01-02T00:00:00-23:59', '2 января 2026, 00:00:00 UTC-23:59', true],
  ['2026-01-02 19:30:10.120Z', '2 января 2026, 19:30:10.120 UTC', true],
];
const invalid = [
  '2026-02-30', '2026-01-00', '2026-01-02T25:61:70+99:99',
  '2026-02-29', '1900-02-29', '2100-02-29', '0001-02-29',
  '2026-04-31', '2026-06-31', '2026-09-31', '2026-11-31',
  '2026-01-32', '2026-00-01', '2026-13-01', '0000-01-01',
  '2026-01-02T24:00', '2026-01-02T99:00', '2026-01-02T00:60',
  '2026-01-02T00:99', '2026-01-02T00:00:60', '2026-01-02T00:00:99',
  '2026-01-02T00:00:60.123Z', '2026-01-02T00:00:00+24:00',
  '2026-01-02T00:00:00-24:00', '2026-01-02T00:00:00+99:59',
  '2026-01-02T00:00:00+00:60', '2026-01-02T00:00:00-00:99',
  '2026-01-02T00:00:00+23:60', '2026-01-02T00:00:00+03:0',
  '2026-01-02T00:00:00.Z', '2026-01-02Z', '20260102',
  '2026-1-02', '2026-01-2', ' 2026-01-02', '2026-01-02 ',
  '2026-01-02T00:00Z\n', '', null, false, 20260102, {date: '2026-01-02'},
];
const cases = valid.map(([value, expected, sourcePrecision = false]) =>
  ({ value, expected, sourcePrecision, pythonParity: true })).concat(invalid.flatMap(value => [false, true].map(sourcePrecision => ({
    value, expected: value === null || value === '' ? missing : invalidLabel, sourcePrecision,
    // Python fromisoformat accepts compact dates/offset overflow; 3.12 also accepts a dangling dot.
    // this presentation contract requires literal YYYY-MM-DD and strict civil fields.
    pythonParity: typeof value !== 'number' && !['20260102', '2026-01-02T00:00:00+00:60', '2026-01-02T00:00:00-00:99',
      '2026-01-02T00:00:00+23:60', '2026-01-02T00:00:00.Z'].includes(value),
  }))));
function loadHelper() {
  class ForbiddenDate {
    constructor() { throw new Error('Date conversion/normalization forbidden'); }
    static parse() { throw new Error('Date.parse forbidden'); }
    static UTC() { throw new Error('Date.UTC forbidden'); }
  }
  const window = {Date: ForbiddenDate};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/healthcheck/web/static/owner_dates.js'), 'utf8'),
    {window, Date: ForbiddenDate});
  return window.healthcheckOwnerDate;
}
function run() {
  const helper = loadHelper();
  const results = cases.map(test => {
    const before = JSON.stringify(test.value);
    const actual = helper(test.value, test.sourcePrecision);
    assert.equal(actual, test.expected, JSON.stringify(test.value));
    assert.equal(JSON.stringify(test.value), before);
    return {...test, actual};
  });
  assert.equal(helper(undefined), missing);
  assert.equal(helper({toString: () => '2026-01-02'}), invalidLabel);
  return {cases: results, extraInvalidInputs: 2, dateConversion: false};
}
module.exports = {cases, run};
if (require.main === module) console.log(JSON.stringify(run()));
