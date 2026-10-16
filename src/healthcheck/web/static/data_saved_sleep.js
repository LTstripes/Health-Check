/* Data default sleep card: eligibility and age belong to the source reader. */
(function () {
  "use strict";
  const host = document.getElementById("saved-sleep-results");
  if (!host) return;
  const feedback = document.getElementById("saved-sleep-feedback");
  const button = document.getElementById("saved-sleep-refresh");
  const selected = {garmin: "", google: ""};
  const inventory = {garmin: new Map(), google: new Map()};
  const labels = {exact: "Сон за день оценки", last_eligible: "Последний пригодный сохранённый сон",
    ambiguous: "Нужен выбор источника", unavailable: "Источник сна не найден",
    no_eligible_in_search: "Пригодный сон в проверенной истории не найден",
    search_incomplete: "Поиск ограничен: последний пригодный сон не определён"};
  let generation = 0, controller;
  function node(tag, text) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    return el;
  }
  const civil = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
  const date = value => window.healthcheckOwnerDate(value);
  function validate(body, params) {
    if (!body || body.mode !== "default_latest" || !Array.isArray(body.items) || body.items.length !== 2 ||
        body.evaluation_local_date !== params.get("evaluation_local_date") ||
        Date.parse(body.evaluated_at_utc) !== Date.parse(params.get("evaluated_at_utc"))) throw Error();
    const found = new Set();
    for (const item of body.items) {
      const p = item.provider, value = item.observation;
      if (!Object.hasOwn(selected, p) || found.has(p) || item.contract_version !== "data-saved-sleep-v1" ||
          item.evaluation_local_date !== body.evaluation_local_date ||
          (item.requested_source_id || "") !== selected[p] || !Object.hasOwn(labels, item.state) ||
          !Array.isArray(item.available_sources) || item.available_sources.length > 32 ||
          !Array.isArray(item.newer_exclusions) || typeof item.search_complete !== "boolean") throw Error();
      const ids = new Set();
      for (const source of item.available_sources) {
        if (!source || typeof source.source_id !== "string" || !source.source_id || ids.has(source.source_id)) throw Error();
        ids.add(source.source_id);
      }
      if (item.source && (!ids.has(item.source.source_id) ||
          (selected[p] && item.source.source_id !== selected[p]))) throw Error();
      if (["exact", "last_eligible"].includes(item.state) !== Boolean(value) || (value && (
          !item.source || !item.search_complete || value.state !== "value" || value.unit !== "seconds" ||
          !Number.isFinite(value.value) || !civil(value.wake_date) ||
          typeof value.partial !== "boolean" || typeof value.role_uncertain !== "boolean" ||
          value.is_zero !== (value.value === 0) ||
          !Number.isInteger(value.observation_age_days) || value.observation_age_days < 0 ||
          (Date.parse(body.evaluation_local_date) - Date.parse(value.wake_date)) / 86400000 !== value.observation_age_days ||
          (item.state === "exact") !== (value.wake_date === body.evaluation_local_date)))) throw Error();
      found.add(p);
    }
    return body;
  }
  function render(body, focus) {
    const grid = node("div"); grid.className = "grid data-source-grid";
    for (const item of body.items) {
      const p = item.provider, name = p === "garmin" ? "Garmin" : "Google";
      for (const source of item.available_sources) inventory[p].set(source.source_id, source);
      const card = node("section"); card.className = "card data-source-card";
      card.style.minWidth = "0"; card.style.overflowWrap = "anywhere";
      card.dataset.sleepProvider = p;
      card.append(node("h3", name), node("p", labels[item.state]));
      if (inventory[p].size > 1 || selected[p]) {
        const label = node("label", "Источник " + name + ": "), select = node("select");
        select.id = "sleep-source-" + p; label.htmlFor = select.id;
        select.style.width = "100%";
        const empty = node("option", "Выбрать источник"); empty.value = ""; select.append(empty);
        for (const source of inventory[p].values()) {
          const option = node("option", (source.device_model || "Источник без модели") + " · " + source.source_instance_id);
          option.value = source.source_id; select.append(option);
        }
        select.value = selected[p];
        select.addEventListener("change", () => { selected[p] = select.value; refresh(select.id); });
        card.append(label, select);
      }
      if (item.observation) {
        const value = item.observation, minutes = Math.round(Math.abs(value.value) / 60 * 100) / 100;
        // Keep sub-minute values and zero; formatting does not change eligibility.
        const duration = (value.value < 0 ? "−" : "") + Math.floor(minutes / 60) + " ч " +
          (minutes % 60).toLocaleString("ru-RU", {maximumFractionDigits: 2}) + " мин";
        const strong = node("strong", duration); strong.className = "saved-sleep-duration";
        card.append(strong,
          node("p", "Пробуждение: " + date(value.wake_date) + ". Возраст: " + value.observation_age_days +
            " дн. на " + date(body.evaluation_local_date) + "."),
          node("p", "Источник: " + (item.source.device_model || name + " (модель не указана)")));
        if (value.observation_age_days > 0) card.append(node("p", "За сегодня пригодный сон не найден. Показана сохранённая ночь."));
        if (value.partial) card.append(node("p", "Запись частичная; длительность пригодна для показа."));
        if (value.role_uncertain) card.append(node("p", "Основная роль этой сессии не подтверждена."));
      }
      if (item.newer_exclusions.length) {
        const dated = item.newer_exclusions.filter(exclusion => exclusion.wake_date);
        const conflicts = dated.filter(exclusion => exclusion.state === "ambiguous");
        if (conflicts.length) card.append(node("p", "Более новые ночи с конфликтом: " + conflicts.length + " (последняя — " + date(conflicts[0].wake_date) + ")."));
        const missing = dated.filter(exclusion => exclusion.state !== "ambiguous");
        if (missing.length) card.append(node("p", "Более новые записи без пригодной длительности: " + missing.length + " (последняя — " + date(missing[0].wake_date) + ")."));
        if (dated.length < item.newer_exclusions.length) card.append(node("p", "Есть записи без даты пробуждения; их возраст неизвестен."));
      }
      grid.append(card);
    }
    host.replaceChildren(grid);
    if (focus) document.getElementById(focus)?.focus();
  }
  async function refresh(focus) {
    const mine = ++generation;
    controller?.abort(); controller = new AbortController();
    const active = controller, timeout = setTimeout(() => active.abort(), 15000);
    host.setAttribute("aria-busy", "true"); host.replaceChildren();
    feedback.setAttribute("role", "status"); feedback.textContent = "Читаем сохранённый сон…";
    try {
      const now = new Date();
      const local = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
      const params = new URLSearchParams({evaluated_at_utc: now.toISOString(), evaluation_local_date: local});
      for (const [p, id] of Object.entries(selected)) if (id) params.set(p + "_source_id", id);
      const response = await fetch("/api/imports/saved-sleep?" + params, {signal: active.signal, cache: "no-store", headers: {Accept: "application/json"}});
      if (!response.ok) throw Error();
      const body = await response.json();
      if (mine !== generation) return;
      if (active.signal.aborted) throw Error();
      render(validate(body, params), focus);
      feedback.textContent = "";
    } catch (_) {
      if (mine !== generation) return;
      host.replaceChildren(); feedback.setAttribute("role", "alert");
      feedback.textContent = "Не удалось прочитать сохранённый сон. Это не подтверждает отсутствие сна. Можно повторить чтение.";
    } finally {
      clearTimeout(timeout);
      if (mine === generation) host.setAttribute("aria-busy", "false");
    }
  }
  button.hidden = false; button.addEventListener("click", () => refresh()); refresh();
})();
