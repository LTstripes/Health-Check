"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const handlers = {};
const source = { value: "source-one", defaultValue: "source-one" };
const start = { value: "", defaultValue: "" };
const end = { value: "", defaultValue: "" };
const garmin = { value: "garmin-alpha", resets: 0 };
const form = controls => ({ reset() { controls.forEach(c => { c.value = c.defaultValue; }); } });
const forms = [form([source]), form([start, end])];
let sectionPresent = true;
const context = {
  window: { addEventListener(name, handler) { handlers[name] = handler; } },
  document: { getElementById(id) {
    assert.equal(id, "google-exercise");
    return sectionPresent ? { querySelectorAll(selector) {
      assert.equal(selector, "form");
      return forms;
    } } : null;
  } },
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,
  "../src/healthcheck/web/static/google_exercise.js"), "utf8"), context);
assert.equal(typeof handlers.pageshow, "function");

// A source-two submission leaves a source-two edit in the source-one history
// document. Back must restore source one, matching that document's saved rows.
source.value = "source-two";
start.value = end.value = "2099-01-03";
handlers.pageshow({ persisted: true });
assert.equal(source.value, "source-one");
assert.equal(start.value, "");
assert.equal(end.value, "");

// Forward/reload can use a fresh document, not necessarily a bfcache restore.
// Its server defaults are source two and the submitted civil-day window.
source.defaultValue = "source-two";
start.defaultValue = end.defaultValue = "2099-01-03";
source.value = "source-one";
start.value = "2099-01-04";
end.value = "2099-01-05";
handlers.pageshow({ persisted: false });
assert.equal(source.value, "source-two");
assert.equal(start.value, "2099-01-03");
assert.equal(end.value, "2099-01-03");

// Ordinary edits remain usable until the next navigation; no change/submit
// handler or timer resets them. Repeated pageshow remains idempotent.
source.value = "source-one";
assert.deepEqual(Object.keys(handlers), ["pageshow"]);
assert.equal(source.value, "source-one");
handlers.pageshow({ persisted: true });
handlers.pageshow({ persisted: false });
assert.equal(source.value, "source-two");
assert.equal(garmin.value, "garmin-alpha");
assert.equal(garmin.resets, 0);
sectionPresent = false;
assert.doesNotThrow(() => handlers.pageshow({ persisted: true }));
console.log("Google history controls: Back/Forward/reload/defaults/idempotence PASS");
