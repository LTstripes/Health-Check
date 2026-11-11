/* Filter only the event table; the saved snapshot and source identities stay intact. */
(function () {
  "use strict";
  function apply(hidden) {
    document.querySelectorAll("[data-sleep-context-source]").forEach(function (cell) {
      cell.hidden = !!hidden[cell.getAttribute("data-sleep-context-source")];
    });
    document.querySelectorAll("[data-sleep-context-hidden]").forEach(function (note) {
      note.hidden = Array.from(note.parentElement.querySelectorAll("[data-sleep-context-source]"))
        .some(function (cell) { return !cell.hidden; });
    });
  }
  function draw() {
    const hidden = {};
    document.querySelectorAll("[data-sleep-series-toggle]").forEach(function (toggle) {
      hidden[toggle.getAttribute("data-sleep-series-toggle")] = !toggle.checked;
    });
    apply(hidden);
  }
  document.querySelectorAll("[data-sleep-series-toggle]").forEach(function (toggle) {
    toggle.addEventListener("change", draw);
  });
  draw();
})();
