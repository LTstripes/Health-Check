"use strict";

// Synthetic DOM: exercise the production checkbox -> A/B -> existing GET path.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
class Element {
  constructor(value = "") {
    this.value = value; this.dataset = {}; this.listeners = {};
    this.checked = false; this.disabled = false; this.hidden = true;
    this.textContent = ""; this.innerHTML = ""; this.options = [{}, {}, {}, {}];
    this.classList = { toggle() {} };
  }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  dispatchEvent(event) { this.listeners[event.type]?.(event); }
  setAttribute() {}
  removeAttribute() {}
  scrollIntoView() {}
  requestSubmit() { this.dispatchEvent({type: "submit", preventDefault() {}}); }
}
const elements = new Map();
const el = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const activities = ["one", "two", "three"].map(record_id => ({record_id, activity_type: "cycling", source_local_date: "2099-01-02"}));
const series = {
  metric_definition: {metric_code: "heart_rate_bpm", unit: "bpm"},
  query: {start_date: "2099-01-02", end_date: "2099-01-03"},
  points: [{status: "zero", value: 0, analytic_date: "2099-01-02"}, {status: "missing", value: null, analytic_date: "2099-01-03"}],
  availability: {usable_count: 1, zero_count: 1, excluded_count: 0, missing_count: 1},
  baseline: {available: true, mean: 0, median: 0},
};
el("garmin-dashboard-data").textContent = JSON.stringify({source_selection: {selected_source_id: "synthetic-source"}, activities, series});
el("activity-metric-names").textContent = "{}";
el("activity-type-names").textContent = JSON.stringify({cycling: "Велосипед"});
// The same record appears in recent and full journals.
const boxes = ["one", "two", "three", "one", "two", "three"].map(id => {
  const input = new Element(); input.dataset.activityCompare = id; return input;
});
const buttons = [new Element(), new Element()];
const panels = ["activity-journal", "activity-comparison", "training-recovery"].map(id => el(id));
panels.forEach((panel, i) => { panel.id = ["activity-journal", "activity-comparison", "training-recovery"][i]; });
const requests = [];
let hash = "";
const location = {
  get hash() { return hash; },
  set hash(value) { hash = value ? "#" + value.replace(/^#/, "") : ""; },
};
const context = {
  document: {
    getElementById: id => id === "garmin-source-id" || id === "source-form" ? null : el(id),
    querySelector: selector => { assert.equal(selector, "#activity-form button"); return el("submit"); },
    querySelectorAll: selector => ({
      "[data-activity-panel]": panels, "[data-activity-mode]": [],
      "[data-activity-compare]": boxes, "[data-compare-selected]": buttons,
      "[data-activity-checkbox-ui], [data-compare-selected]": [...boxes, ...buttons],
    })[selector] || [],
  },
  window: {
    healthcheckOwnerDate: value => value || "Дата не указана",
    healthcheckOwnerFormat: {duration: String, number: value => value == null ? "—" : String(value)},
    addEventListener() {},
  },
  Event: class { constructor(type) { this.type = type; } },
  location, URLSearchParams,
  fetch: url => { requests.push(url); return new Promise(() => {}); },
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../src/healthcheck/web/static/garmin_dashboard.js"), "utf8"), context);
assert.ok(el("series-summary").innerHTML.includes("0 уд/мин"));
assert.ok(el("series-summary").innerHTML.includes("Ряд не описывает весь период"));
assert.ok(!el("series-summary").innerHTML.includes("Пригодных значений"));
assert.ok(el("series-counts").innerHTML.includes("Пригодных значений: 1"));
assert.deepEqual(JSON.parse(el("series-evidence").textContent), series);
function choose(index, checked) { boxes[index].checked = checked; boxes[index].dispatchEvent({type: "change"}); }
assert.equal(buttons[0].disabled, true);
choose(0, true);
assert.equal(el("activity-a").value, "one");
assert.equal(el("activity-b").value, "");
assert.equal(boxes[3].checked, true);
choose(4, true);
assert.equal(el("activity-b").value, "two");
assert.equal(boxes[1].checked, true);
assert.equal(boxes[2].disabled, true);
assert.equal(buttons[0].disabled, false);
assert.equal(buttons[0].textContent, "Сравнить выбранные (2)");
buttons[0].dispatchEvent({type: "click"});
assert.equal(requests.length, 1);
const url = new URL(requests[0], "http://localhost");
assert.equal(url.pathname, "/api/garmin/activity-comparison");
assert.deepEqual(Object.fromEntries(url.searchParams), {
  garmin_source_id: "synthetic-source", activity_record_ids: "one,two", reference_activity_id: "one",
});
assert.equal(panels[0].hidden, true);
assert.equal(panels[1].hidden, false);
choose(3, false);
assert.equal(el("activity-a").value, "two");
assert.equal(el("activity-b").value, "");
assert.equal(boxes[0].checked, false);
assert.equal(boxes[2].disabled, false);
assert.equal(buttons[1].disabled, true);
// Manual dropdowns synchronize the journal and still reject identical A/B.
el("activity-a").value = "three";
el("activity-b").value = "three";
el("activity-b").dispatchEvent({type: "change"});
assert.equal(el("submit").disabled, true);
assert.equal(buttons[0].disabled, true);
assert.equal(el("activity-result").innerHTML, "");
el("activity-b").value = "one";
el("activity-b").dispatchEvent({type: "change"});
assert.equal(el("submit").disabled, false);
assert.equal(boxes[2].checked, true);
assert.equal(boxes[0].checked, true);
assert.equal(boxes[1].disabled, true);
console.log("Activity journal selection/source/order/duplicate rows/fallback/reset/API PASS");
