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
      select.selectedIndex = index;
      const date = panel.querySelector("[data-steps-selected-date]");
      date.dateTime = row.date;
      const [year, month, day] = row.date.split("-");
      date.textContent = `${day}.${month}.${year}`;
      panel.querySelector("[data-steps-selected-value]").textContent = row.value === null ? "Нет допустимого значения" : row.value;
      panel.querySelector("[data-steps-selected-unit]").textContent = row.value === null ? "" : "шагов";
      const cursor = panel.querySelector("[data-steps-cursor]");
      cursor.setAttribute("x1", row.x);
      cursor.setAttribute("x2", row.x);
      previous.disabled = index === 0;
      next.disabled = index === rows.length - 1;
    };
    select.addEventListener("change", () => show(select.selectedIndex));
    previous.addEventListener("click", () => show(select.selectedIndex - 1));
    next.addEventListener("click", () => show(select.selectedIndex + 1));
    svg.tabIndex = 0;
    svg.setAttribute("role", "group");
    svg.setAttribute("aria-label", `${panel.dataset.stepsChart}: график по дням. Стрелки выбирают день, Home и End — края периода.`);
    svg.addEventListener("keydown", (event) => {
      const target = {ArrowLeft: select.selectedIndex - 1, ArrowRight: select.selectedIndex + 1,
        Home: 0, End: rows.length - 1}[event.key];
      if (target === undefined) return;
      event.preventDefault();
      show(target);
    });
    svg.addEventListener("click", (event) => {
      const rect = svg.getBoundingClientRect();
      const x = (event.clientX - rect.left) * 900 / rect.width;
      let nearest = 0;
      for (let index = 1; index < rows.length; index++) {
        if (Math.abs(rows[index].x - x) < Math.abs(rows[nearest].x - x)) nearest = index;
      }
      show(nearest);
    });
    panel.querySelector("[data-steps-day-controls]").hidden = false;
    show(select.selectedIndex);
  }
})();
