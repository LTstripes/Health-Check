"use strict";
(() => {
  const form = document.getElementById("analysis-export-form");
  if (!form) return;
  const status = document.getElementById("analysis-export-status");
  const result = document.getElementById("analysis-export-result");
  const reload = document.getElementById("analysis-export-reload");
  const submit = form.querySelector('[type="submit"]');
  const garmin = form.elements.garmin_source_id;
  const google = form.elements.google_hrv_source_id;
  const options = document.getElementById("analysis-export-options");
  let generation = 0;
  let controller = null;
  let urls = [];
  let sourcesReady = false;

  function updateRange() {
    const days = Number(form.elements.days.value);
    const value = form.elements.end_date.value;
    const end = new Date(`${value}T00:00:00Z`);
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - days + 1);
    const valid = [7, 30].includes(days) && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
      Number.isFinite(end.getTime()) && end.toISOString().slice(0, 10) === value &&
      start.getUTCFullYear() >= 1 && value < "9999-12-31";
    form.elements.end_date.setCustomValidity(valid ? "" : "Укажите корректную дату для выбранного периода.");
    document.getElementById("analysis-export-preview").textContent = valid
      ? `Период: ${start.toISOString().slice(0, 10)} — ${value} (включительно).`
      : "Укажите корректную дату и период 7 или 30 дней для скачивания.";
    return valid;
  }

  function clear() {
    generation += 1;
    if (controller) controller.abort();
    controller = null;
    urls.forEach((url) => URL.revokeObjectURL(url));
    urls = [];
    result.hidden = true;
    for (const kind of ["text", "json"]) {
      document.getElementById(`analysis-export-${kind}`).removeAttribute("href");
    }
    document.getElementById("analysis-export-disclosures").textContent = "";
    document.getElementById("analysis-export-summary").replaceChildren();
    const validRange = updateRange();
    submit.disabled = !sourcesReady || !garmin.value || !validRange;
  }

  form.addEventListener("input", () => {
    clear();
    status.textContent = "Параметры изменены. Нажмите «Скачать».";
  });

  function showSummary(details) {
    const labels = {state: "состояние", window_state: "состояние",
      observed_dates_count: "сохранённых дат", missing_dates_count: "дат без подходящих значений",
      eligible_day_count: "подходящих сохранённых дней", missing_day_count: "дней без подходящих значений",
      eligible_snapshot_date_count: "дат подходящих недельных снимков",
      requested_day_count: "Запрошено дней", completed_day_count: "Завершённых дней, МСК",
      excluded_uncompleted_day_count: "Незавершённых дней исключено",
      returned_count: "записей в файле", observed_count: "подходящих записей", has_more: "есть ещё записи"};
    const states = {no_records: "нет записей", no_eligible_in_period: "нет подходящих значений",
      records: "есть сохранённые записи", projection_unavailable: "сохранённая проекция недоступна",
      no_eligible_values: "нет подходящих значений", no_current_record_in_window: "нет текущих записей",
      unknown: "неизвестно", unavailable: "недоступно", ambiguous: "неоднозначно",
      conflict: "конфликт источников", partial: "частичные данные", value: "есть значение"};
    Object.assign(states, {null: "Нет значения", missing: "Поле отсутствует",
      invalid: "Некорректно", search_incomplete: "Поиск не завершён"});
    const rows = [];
    const add = (name, item) => {
      if (!item) return;
      const facts = Object.entries(item).filter(([key]) => key in labels &&
        !(key === "missing_dates_count" && "missing_day_count" in item)).map(([key, value]) =>
        `${labels[key]}: ${value === null ? "неизвестно" : states[value] || (typeof value === "boolean" ? (value ? "да" : "нет") : value)}`);
      if (item.cell_state_counts) facts.push(Object.entries(item.cell_state_counts)
        .map(([state, count]) => `${states[state] || state}: ${count} дней`).join("; "));
      if (facts.length) rows.push(`${name} — ${facts.join("; ")}.`);
    };
    for (const [provider, section] of Object.entries(details.sleep.providers)) {
      add(`Сон · ${provider === "garmin" ? "Garmin" : "Google"}`, section.source_range || section.source_selection);
    }
    add("Активности · Garmin", details.activity.providers.garmin.metrics.activity_session_count);
    add("Комментарии", details.context);
    add("Stress · Garmin", details.stress);
    add("Body Battery · Garmin", details.body_battery);
    for (const domain of ["hrv", "rhr"]) {
      for (const [provider, section] of Object.entries(details[domain].providers)) {
        add(`${domain === "hrv" ? "HRV" : "Пульс в покое"} · ${provider === "garmin" ? "Garmin" : "Google"}`, section);
      }
    }
    add(details.steps.display_zone === "Europe/Moscow"
      ? "Шаги за завершённые дни — Garmin (МСК)"
      : "Наблюдаемые шаги — Garmin (не финальные итоги)", details.steps);
    if (details.steps.effective_completed_range) {
      const range = details.steps.effective_completed_range;
      rows.push(range.start_date
        ? `Завершённые даты шагов: ${range.start_date} — ${range.end_date} (МСК).`
        : "В запрошенном периоде ещё нет завершённых дней по МСК.");
    }
    add("Вес · измерения", details.weight.measured_facts);
    const list = document.getElementById("analysis-export-summary");
    list.replaceChildren(...rows.map((text) => {
      const item = document.createElement("li");
      item.textContent = text;
      return item;
    }));
  }

  async function loadSources() {
    clear();
    sourcesReady = false;
    submit.disabled = true;
    garmin.disabled = true;
    google.disabled = true;
    reload.hidden = true;
    status.textContent = "Загрузка источников…";
    try {
      const response = await fetch("/api/analysis-export/sources", {cache: "no-store"});
      if (!response.ok) throw new Error();
      const data = await response.json();
      const garminRows = data.sources.filter((row) => row.provider === "garmin_connect");
      const googleRows = data.sources.filter((row) => row.provider === "google_health");
      garmin.replaceChildren(new Option("Выберите источник", ""));
      google.replaceChildren(new Option("Не включать", ""));
      garminRows.forEach((row) => garmin.add(new Option(row.label, row.id)));
      googleRows.forEach((row) => google.add(new Option(row.label, row.id)));
      if (garminRows.length === 1) garmin.value = garminRows[0].id;
      if (googleRows.length === 1) google.value = googleRows[0].id;
      // A sole saved identity is only a selector default. The existing reader,
      // not inventory size, determines metric eligibility and missing states.
      options.hidden = garminRows.length <= 1 && googleRows.length <= 1;
      options.open = !options.hidden;
      form.querySelector('[data-export-garmin-choice]').hidden = garminRows.length <= 1;
      form.querySelector('[data-export-google-choice]').hidden = googleRows.length <= 1;
      sourcesReady = true;
      garmin.disabled = false;
      google.disabled = false;
      submit.disabled = !garmin.value || !updateRange();
      status.textContent = !garminRows.length
        ? "Сохранённых источников Garmin нет. Проверьте источники в разделе «Данные»."
        : garmin.value ? (googleRows.length > 1 ? "Google HRV: выберите источник, чтобы включить его в файл." : "") : "Выберите источник Garmin.";
    } catch (_) {
      options.hidden = true;
      status.textContent = "Источники недоступны. Проверьте локальные данные и повторите загрузку.";
      reload.hidden = false;
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity() || submit.disabled) return;
    clear();
    const current = generation;
    controller = new AbortController();
    submit.disabled = true;
    status.textContent = "Готовим локальный файл…";
    const values = new FormData(form);
    try {
      const response = await fetch("/api/analysis-export", {
        method: "POST", cache: "no-store", signal: controller.signal,
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({days: Number(values.get("days")), end_date: values.get("end_date"),
          garmin_source_id: values.get("garmin_source_id"),
          steps_view: values.get("steps_view") || "completed",
          google_hrv_source_id: values.get("google_hrv_source_id") || null}),
      });
      const data = await response.json();
      if (current !== generation) return;
      if (!response.ok) {
        status.textContent = data.code === "output_exceeds_byte_limit"
          ? "Превышен лимит 2 MiB. Выберите 7 дней. Частичная выгрузка не создана."
          : "Не удалось сформировать файлы: проверьте дату и источники. Возможен предел поиска или объёма; попробуйте 7 дней. Частичная выгрузка не создана.";
        return;
      }
      const sizes = [];
      for (const kind of ["text", "json"]) {
        const blob = new Blob([data[kind]], {type: kind === "json" ? "application/json;charset=utf-8" : "text/plain;charset=utf-8"});
        const url = URL.createObjectURL(blob);
        urls.push(url);
        const link = document.getElementById(`analysis-export-${kind}`);
        link.href = url;
        link.download = `${data.filename}.${kind === "text" ? "txt" : "json"}`;
        sizes.push(`${kind === "text" ? "Текст" : "JSON"}: ${(blob.size / 1024).toFixed(1)} KiB`);
      }
      document.getElementById("analysis-export-range").textContent = `Период: ${data.range.start_date} — ${data.range.end_date} (включительно).`;
      document.getElementById("analysis-export-sizes").textContent = sizes.join(" · ");
      document.getElementById("analysis-export-disclosures").textContent = JSON.stringify(data.disclosures, null, 2);
      showSummary(data.disclosures);
      result.hidden = false;
      document.getElementById("analysis-export-text").click();
      status.textContent = "Файл готов. Скачивание текста началось.";
    } catch (error) {
      if (current !== generation || error.name === "AbortError") return;
      clear();
      status.textContent = "Не удалось скачать файл. Проверьте локальный интерфейс и повторите скачивание.";
    } finally {
      if (current === generation) {
        controller = null;
        submit.disabled = !sourcesReady || !garmin.value || !updateRange();
      }
    }
  });
  reload.addEventListener("click", loadSources);
  window.addEventListener("pagehide", () => {
    clear();
    status.textContent = "Скачайте файл заново.";
  });
  loadSources();
})();
