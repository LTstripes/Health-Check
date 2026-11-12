/* Counts are server decimal strings. JS selects days; it never aggregates counts. */
(() => {
  "use strict";
  for (const panel of document.querySelectorAll("[data-steps-chart]")) {
    const data = panel.querySelector("[data-steps-chart-data]");
    if (!data) continue;
    const rows = JSON.parse(data.textContent);
    const select = panel.querySelector("[data-steps-day]");
    const svg = panel.querySelector("svg");
    const previous = panel.querySelector("[data-steps-previous]");
    const next = panel.querySelector("[data-steps-next]");
    const show = (index) => {
      index = Math.max(0, Math.min(rows.length - 1, index));
      const row = rows[index];
      select.value = String(index);
      const date = panel.querySelector("[data-steps-selected-date]");
      date.hidden = false;
      panel.querySelector("[data-steps-selected-separator]").hidden = false;
      date.dateTime = row.date;
      date.textContent = window.healthcheckOwnerShortDate(row.date);
      panel.querySelector("[data-steps-selected-value]").textContent = row.value === null ? "Нет допустимого значения" : row.display;
      panel.querySelector("[data-steps-selected-unit]").textContent = row.value === null ? "" : "шагов";
      const cursor = panel.querySelector("[data-steps-cursor]");
      cursor.hidden = false;
      cursor.removeAttribute("hidden");
      cursor.setAttribute("x1", row.x);
      cursor.setAttribute("x2", row.x);
      previous.disabled = index === 0;
      next.disabled = index === rows.length - 1;
    };
    const selected = () => select.value === "" ? -1 : rows.findIndex(row => String(row.index) === select.value);
    select.addEventListener("change", () => show(selected()));
    previous.addEventListener("click", () => show(selected() - 1));
    next.addEventListener("click", () => show(selected() + 1));
    svg.tabIndex = 0;
    svg.setAttribute("role", "group");
    svg.setAttribute("aria-label", `${panel.dataset.stepsChart}: график по дням. Стрелки выбирают день, Home и End — края периода.`);
    svg.addEventListener("keydown", (event) => {
      const target = {ArrowLeft: selected() - 1, ArrowRight: selected() + 1,
        Home: 0, End: rows.length - 1}[event.key];
      if (target === undefined) return;
      event.preventDefault();
      show(target);
    });
    const choosePointer = (event) => {
      const rect = svg.getBoundingClientRect();
      const box = svg.viewBox.baseVal;
      const x = box.x + (event.clientX - rect.left) * box.width / rect.width;
      let nearest = 0;
      for (let index = 1; index < rows.length; index++) {
        if (Math.abs(rows[index].x - x) < Math.abs(rows[nearest].x - x)) nearest = index;
      }
      show(nearest);
    };
    svg.addEventListener("click", choosePointer);
    svg.addEventListener("pointermove", choosePointer);
    panel.querySelector("[data-steps-day-controls]").hidden = false;

  }
})();
