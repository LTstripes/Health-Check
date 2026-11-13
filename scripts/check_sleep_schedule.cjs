// Synthetic DOM contract checks for schedule loading, controls and selection.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function setup(packet, invalid = false) {
  const status = {}, expand = {focus() { this.focused = true; }};
  let buttons = [], rows = [];
  const selection = {current: {date: packet.dates.at(-1), seriesId: 'garmin'}, calls: [],
    select(date, seriesId) {
      this.calls.push({date, seriesId});
      this.current = {date, seriesId: seriesId || this.current.seriesId};
      this.onChange();
    }};
  const host = {events: {}, html: '',
    set innerHTML(value) {
      this.html = value;
      rows = [...value.matchAll(/data-schedule-date="([^"]+)"/g)].map(match => {
        const row = {date: match[1], selected: false, getAttribute() {return this.date;},
          classList: {toggle(name, value) {row.selected = value;}},
          querySelector() {return row.button;}, querySelectorAll() {return [];} };
        row.button = {pressed: null, row,
          setAttribute(key, value) {this.pressed = value;}, focus() {this.focused = true;},
          click() {host.events.click({target: this});},
          closest(selector) {return selector === '[data-schedule-select]' ? this : selector === '[data-schedule-date]' ? row : null;} };
        return row;
      });
      buttons = rows.map(row => row.button);
    },
    get innerHTML() {return this.html;},
    querySelector(selector) {return selector === '[data-schedule-expand]' ? expand : status;},
    querySelectorAll(selector) {return selector === '[data-schedule-select]' ? buttons : rows;},
    addEventListener(name, handler) {this.events[name] = handler;}
  };
  const dataNode = {textContent: invalid ? '{broken' : JSON.stringify(packet)};
  const document = {getElementById(id) {return {'sleep-schedule': host, 'sleep-timeline-data': dataNode}[id];}, querySelectorAll() {return [];} };
  const context = vm.createContext({window: {healthcheckSleepSelection: selection}, document});
  for (const file of ['owner_dates.js', 'owner_formatting.js', 'sleep_schedule.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/healthcheck/web/static', file), 'utf8'),context);
  }
  return {host, selection, expand, rows: () => rows, buttons: () => buttons};
}
const dates = Array.from({length: 30}, (_, i) => new Date(Date.UTC(2026,9,1+i)).toISOString().slice(0,10));
const packet = {dates, days:30, display_series:[], regularity:{sources:[]}};
const ui = setup(packet);
assert.equal(ui.rows().length,14);
assert.equal(ui.rows()[0].selected,true);
ui.buttons()[3].click();
assert.equal(ui.selection.current.date, dates.at(-4));
assert.equal(ui.rows()[3].selected,true);
assert.equal(ui.rows()[3].button.pressed,'true');
assert.equal(ui.rows()[0].selected,false);
let prevented=false;
ui.host.events.keydown({key:'ArrowDown',target:ui.buttons()[3],preventDefault(){prevented=true;}});
assert.equal(prevented,true);
assert.equal(ui.selection.current.date,dates.at(-5));
assert.equal(ui.buttons()[4].focused,true);
ui.selection.current={date:dates.at(-2),seriesId:'google'};
ui.selection.onChange();
assert.equal(ui.rows()[1].selected,true);
ui.host.events.click({target:{closest(selector){return selector==='[data-schedule-expand]' ? ui.expand : null;}}});
assert.equal(ui.rows().length,30);
assert.equal(ui.expand.focused,true);
ui.host.events.click({target:{closest(selector){return selector==='[data-schedule-expand]' ? ui.expand : null;}}});
assert.equal(ui.rows().length,14);
const broken=setup(packet,true);
assert.match(broken.host.innerHTML,/Не удалось показать расписание/);
assert.match(broken.host.innerHTML,/href="#sleep-duration-table"/);
assert.doesNotMatch(broken.host.innerHTML,/JavaScript/);
assert.deepEqual(packet,{dates,days:30,display_series:[],regularity:{sources:[]}});
console.log('PASS: schedule selection, keyboard, highlight, expand/collapse, JSON failure, packet unchanged');
