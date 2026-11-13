// Exercise source-card hydration with the production T6 renderer and exact slots.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const hosts = input.hosts.map(host => ({dataset: host, innerHTML: 'server fallback'}));
const packet = {textContent: JSON.stringify(input.packet)};
const context = vm.createContext({window: {}, document: {
  getElementById: () => packet,
  querySelectorAll: () => hosts,
}, fetch: () => { throw new Error('source cards must not fetch'); }});
const root = path.resolve(__dirname, '..', 'src', 'healthcheck', 'web', 'static');
for (const name of ['owner_formatting.js', 'sleep_night_card.js', 'sleep_source_night.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), context, {filename: name});
}
process.stdout.write(JSON.stringify(hosts.map(host => host.innerHTML)));
