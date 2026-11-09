/* Render the production selected-night card helpers for synthetic cases.
 * Usage: node scripts/render_sleep_night_card.cjs <cases.json>
 * Input: [{series, point, session|null}]; output: [{head, session}] HTML strings. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..', 'src', 'healthcheck', 'web', 'static');
const context = vm.createContext({ window: {} });
for (const name of ['owner_formatting.js', 'sleep_night_card.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), context, { filename: name });
}
const card = context.window.healthcheckSleepNightCard;
const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const output = cases.map(item => ({
  head: card.head(item.series, item.point),
  session: item.session ? card.session(item.series, item.session) : null,
}));
process.stdout.write(JSON.stringify(output));
