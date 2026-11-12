// Execute the production renderer on synthetic packets, without a browser or network.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = vm.createContext({ window: {} });
for (const file of ['owner_dates.js', 'owner_formatting.js', 'sleep_schedule.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'src', 'healthcheck',
    'web', 'static', file), 'utf8'), context);
}
const schedule = context.window.healthcheckSleepSchedule;
const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(JSON.stringify(cases.map(item => {
  const rows = schedule.rows(item.data, item.data.display_series || []);
  return { html: schedule.render(item.data, item.hidden || {}), axis: schedule.axis(rows), rows };
})));
