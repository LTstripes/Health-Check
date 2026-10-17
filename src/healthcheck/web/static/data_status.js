/* Independent #376 Data consumer. No eligibility or age policy in the UI. */
(function () {
  "use strict";
  const host = document.getElementById("saved-rhr-results");
  if (!host) return;
  const button = document.getElementById("saved-rhr-refresh");
  const feedback = document.getElementById("saved-rhr-feedback");
  const clock = document.getElementById("saved-rhr-clock");
  const selected = {garmin_connect: "", google_health: ""};
  const inventory = {garmin_connect: new Map(), google_health: new Map()};
  const metrics = {garmin_connect: "resting_heart_rate_bpm", google_health: "daily_resting_heart_rate_bpm"};
  const labels = {exact: "Измерение за дату оценки", last_eligible: "Последнее пригодное измерение",
    no_eligible_in_search: "Пригодное измерение в проверенной истории не найдено",
    search_incomplete: "Поиск не завершён: достигнут предел чтения",
    never_collected: "Сбор не выполнялся (подтверждено)", ambiguous: "Неоднозначные данные",
    unavailable: "Сохранённое значение не определено"};
  let generation = 0, controller, focusAfter;
  function node(tag, text) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function displayDate(value) {
    return window.healthcheckOwnerDate(value);
  }
  function disclosure(title, value) {
    const item = node("details");
    item.className = "owner-details";
    item.append(node("summary", title));
    const pre = node("pre", JSON.stringify(value, null, 2));
    pre.className = "provenance";
    item.append(pre);
    return item;
  }
  function validate(payload, params) {
    const civil = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
    if (!payload || payload.mode !== "default_latest" || !civil(payload.evaluation_local_date) ||
        payload.evaluation_local_date !== params.get("evaluation_local_date") ||
        Date.parse(payload.evaluated_at_utc) !== Date.parse(params.get("evaluated_at_utc")) ||
        !Array.isArray(payload.items) || payload.items.length !== 2 || !payload.collection_policy) throw Error("invalid_response");
    const found = new Set();
    for (const dto of payload.items) {
      const q = dto.query, p = q && q.provider_code;
      if (!Object.hasOwn(metrics, p) || found.has(p) || dto.contract_version !== "r376-saved-rhr-read-v1" ||
          q.metric_code !== metrics[p] || q.mode !== "default_latest" ||
          q.requested_start_date !== payload.evaluation_local_date || q.requested_end_date !== payload.evaluation_local_date ||
          q.evaluation_local_date !== payload.evaluation_local_date ||
          Date.parse(q.evaluated_at_utc) !== Date.parse(payload.evaluated_at_utc) ||
          (q.source_id || "") !== selected[p] || !Object.hasOwn(labels, dto.state) ||
          !Array.isArray(dto.available_sources) || !Array.isArray(dto.newer_exclusions) ||
          dto.available_sources.length > 32 || !dto.search || !dto.refresh ||
          dto.search.date_group_cap !== 32 || dto.search.candidate_record_cap !== 256 ||
          !dto.metric_identity || dto.metric_identity.metric_code !== metrics[p] || dto.metric_identity.unit !== "bpm") throw Error("invalid_response");
      const ids = new Set();
      for (const identity of dto.available_sources) {
        if (!identity || identity.provider_code !== p || typeof identity.source_id !== "string" ||
            !identity.source_id || ids.has(identity.source_id)) throw Error("invalid_response");
        ids.add(identity.source_id);
      }
      if (dto.source_identity && (dto.source_identity.provider_code !== p || !ids.has(dto.source_identity.source_id) ||
          (selected[p] && dto.source_identity.source_id !== selected[p]))) throw Error("invalid_response");
      const observation = dto.observation;
      if (["exact", "last_eligible"].includes(dto.state) !== Boolean(observation) ||
          (observation && (!dto.source_identity || !Number.isFinite(observation.value) || observation.unit !== "bpm" ||
          !civil(observation.source_local_date) || !Number.isInteger(observation.observation_age_days) || observation.observation_age_days < 0 ||
          (Date.parse(payload.evaluation_local_date) - Date.parse(observation.source_local_date)) / 86400000 !== observation.observation_age_days))) throw Error("invalid_response");
      found.add(p);
    }
    return payload;
  }
  function render(payload) {
    const grid = node("div");
    grid.className = "grid data-source-grid";
    for (const dto of payload.items) {
      const p = dto.query.provider_code, name = p === "garmin_connect" ? "Garmin" : "Google";
      for (const identity of dto.available_sources) inventory[p].set(identity.source_id, identity);
      const card = node("section");
      card.className = "card data-source-card";
      card.setAttribute("style", "min-width:0;overflow-wrap:anywhere");
      card.dataset.savedProvider = p;
      card.append(node("h3", name + " · пульс в покое"));
      const label = node("label", "Источник " + name + ": ");
      const select = node("select");
      select.id = "saved-source-" + p;
      select.setAttribute("style", "width:100%;max-width:100%");
      label.htmlFor = select.id;
      const empty = node("option", "Автоматический выбор пригодного источника");
      empty.value = "";
      select.append(empty);
      for (const identity of inventory[p].values()) {
        const device = identity.device_attributed && identity.device_model ? identity.device_model : "Устройство не подтверждено";
        const option = node("option", [device, identity.source_kind, identity.source_instance_id, identity.source_id].filter(Boolean).join(" · "));
        option.value = identity.source_id;
        select.append(option);
      }
      select.value = selected[p];
      select.addEventListener("change", () => { selected[p] = select.value; refresh(); });
      const controls = node("div");
      controls.append(label, select);
      if (selected[p]) {
        const clear = node("button", "Сбросить выбор источника");
        clear.type = "button";
        clear.addEventListener("click", () => { selected[p] = ""; refresh(); });
        controls.append(clear);
      }
      if (dto.reason === "source_inventory_cap" || (selected[p] && !inventory[p].has(selected[p]))) {
        const form = node("form"), input = node("input"), apply = node("button", "Выбрать ID");
        input.type = "text"; input.value = selected[p]; input.required = true;
        input.setAttribute("aria-label", "Явный ID источника " + name);
        apply.type = "submit";
        form.append(input, apply);
        form.addEventListener("submit", event => { event.preventDefault(); selected[p] = input.value.trim(); refresh(); });
        card.append(node("p", "Список источников ограничен. Можно указать точный ID без автоматического выбора."), form);
      }
      if (dto.source_selection?.state === "unique_eligible_source" && !selected[p] && dto.observation) {
        const override = node("details");
        override.className = "owner-details";
        override.append(node("summary", "Выбрать другой источник (необязательно)"), controls);
        card.append(override);
      } else card.append(controls);
      card.append(node("p", labels[dto.state]));
      if (dto.reason === "source_selection_required") card.append(node("p", "Выберите источник явно. Значения разных identities не объединяются."));
      if (dto.reason === "saved_value_read_failed") card.append(node("p", "Ошибка чтения; это не отсутствие измерений."));
      if (dto.reason === "source_not_found") card.append(node("p", "Источник не найден; наличие других измерений не определено."));
      if (dto.observation) {
        const value = dto.observation;
        card.append(node("p", value.value + " " + value.unit),
          node("p", "Исходная дата: " + displayDate(value.source_local_date) + ". Возраст: " + value.observation_age_days + " дн. относительно " + displayDate(payload.evaluation_local_date) + "."),
          node("p", "Источник: " + dto.source_identity.source_instance_id + " · " + dto.source_identity.source_id));
        if (value.record_status === "partial") card.append(node("p", "Запись частичная; пригодность этого RHR подтверждена reader. Полнота остальных данных неизвестна."));
      }
      if (dto.newer_exclusions.length) {
        const extra = node("details"); extra.className = "owner-details";
        extra.append(node("summary", "Исключённые записи: " + dto.newer_exclusions.length));
        for (const exclusion of dto.newer_exclusions) extra.append(node("p", displayDate(exclusion.source_local_date) + " · " + exclusion.reason));
        card.append(extra);
      }
      if (!dto.search.complete) card.append(node("p", "Полная группа/история не подтверждена: " + (dto.search.reason || "unknown") + (dto.search.incomplete_group_date ? " · " + displayDate(dto.search.incomplete_group_date) : "")));
      const scope = p === "garmin_connect" ? "garmin:resting_heart_rate" : "google:daily_resting_hr";
      const disabled = payload.collection_policy.status === "valid" && payload.collection_policy.disabled_streams.includes(scope);
      if (p === "google_health" && payload.collection_policy.status === "valid" && payload.collection_policy.disabled_streams.includes("google:heart_rate")) {
        card.append(node("p", "Отдельный поток «Пульс» отключён. Это не статус сбора пульса в покое (RHR)."));
      }
      card.append(node("p", "Обновление потока: " + (disabled ? "Сбор отключён" : ({reauth_required: "Нужен повторный вход", disabled: "Сбор отключён", failed: "Ошибка обновления"}[dto.refresh.terminal_status] || dto.refresh.terminal_status || "Не определено"))),
        node("p", "Последняя попытка: " + displayDate(dto.refresh.last_attempt_utc) + ". Последнее успешное обновление: " + displayDate(dto.refresh.last_successful_refresh_utc) + "."),
        node("p", "Полнота сбора: неизвестна. Происхождение и возраст снимка: неизвестны. Правило возраста: не настроено."),
        disclosure("Точные значения и provenance", dto));
      grid.append(card);
    }
    host.replaceChildren(grid);
    if (focusAfter) document.getElementById(focusAfter)?.focus();
  }
  async function refresh() {
    const mine = ++generation;
    focusAfter = document.activeElement?.id?.startsWith("saved-source-") ? document.activeElement.id : null;
    if (controller) controller.abort();
    controller = new AbortController();
    const active = controller;
    const timeout = setTimeout(() => active.abort(), 15000);
    host.setAttribute("aria-busy", "true");
    host.replaceChildren(); clock.textContent = "";
    feedback.textContent = "Читаем сохранённые измерения…";
    delete feedback.dataset.failureCode;
    let failure = "network_error";
    try {
      const now = new Date(), localDate = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
      const params = new URLSearchParams({evaluated_at_utc: now.toISOString(), evaluation_local_date: localDate});
      for (const [provider, id] of Object.entries(selected)) if (id) params.set(provider === "garmin_connect" ? "garmin_source_id" : "google_source_id", id);
      const response = await fetch("/api/imports/saved-rhr?" + params, {signal: active.signal, cache: "no-store", headers: {Accept: "application/json"}});
      if (mine !== generation) return;
      if (!response.ok) { failure = response.status === 422 ? "invalid_request" : response.status === 503 ? "database_unavailable" : "endpoint_error"; throw Error(failure); }
      failure = "invalid_response";
      const body = await response.json();
      if (mine !== generation) return;
      if (active.signal.aborted) throw Error("timeout");
      const payload = validate(body, params);
      failure = "render_failed";
      render(payload);
      clock.textContent = "Дата оценки возраста: " + displayDate(payload.evaluation_local_date) + ". Чтение (UTC): " + displayDate(payload.evaluated_at_utc) + ". Режим: default_latest.";
      feedback.textContent = "Сохранённые значения прочитаны. Состояние обновления показано отдельно.";
    } catch (_) {
      if (mine !== generation) return;
      if (active.signal.aborted) failure = "timeout";
      host.replaceChildren(); clock.textContent = "";
      feedback.dataset.failureCode = failure;
      feedback.textContent = "Не удалось прочитать сохранённые значения (" + failure + "). Это не подтверждает отсутствие измерений. Можно повторить чтение.";
    } finally {
      clearTimeout(timeout);
      if (mine === generation) host.setAttribute("aria-busy", "false");
    }
  }
  button.hidden = false;
  button.addEventListener("click", refresh);
  refresh();
})();
/* Owner presentation of source-freshness-v1. No thresholds or provider calls here. */
(function () {
  "use strict";
  document.querySelectorAll("time.import-started[datetime]").forEach(element => {
    const date = new Date(element.dateTime);
    if (!Number.isNaN(date.getTime())) element.textContent = new Intl.DateTimeFormat("ru-RU", {
      year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short"
    }).format(date);
  });
  const host = document.getElementById("data-results");
  if (!host) return;
  const button = document.getElementById("data-refresh");
  const feedback = document.getElementById("data-feedback");
  const clock = document.getElementById("data-clock");
  const stateLabels = {
    present: "Данные доступны", partial: "Данные доступны частично",
    confirmed_empty: "За период записей нет", unknown: "Состояние данных не определено",
    unavailable: "Источник данных недоступен", insufficient: "Недостаточно данных",
    not_requested: "Не запрашивалось", loading: "Загрузка данных",
    error: "Не удалось выполнить запрос", no_change: "Изменений не обнаружено"
  };
  const scopeLabels = {
    "garmin:daily_summary": "Сводка дня", "garmin:sleep": "Сон",
    "garmin:heart_rate": "Пульс", "garmin:resting_heart_rate": "Пульс в покое",
    "garmin:hrv_status": "Вариабельность пульса", "garmin:stress": "Стресс",
    "garmin:body_battery": "Body Battery", "garmin:spo2": "Кислород в крови",
    "garmin:respiration": "Дыхание", "garmin:training_status": "Статус тренировок",
    "garmin:training_readiness": "Готовность к тренировке", "garmin:activities": "Активности",
    "google:sleep": "Сон", "google:heart_rate": "Пульс", "google:hrv": "Вариабельность пульса",
    "google:daily_hrv": "Вариабельность пульса за день",
    "google:daily_resting_hr": "Пульс в покое за день", "google:spo2": "Кислород в крови",
    "google:daily_spo2": "Кислород в крови за день",
    "google:respiratory_rate_sleep": "Дыхание во сне",
    "google:daily_respiratory_rate": "Дыхание за день",
    "google:wearables_sleep_reconcile": "Сопоставление сна устройств", weight: "Вес"
  };
  const reasons = {
    evidence_current: "Данные актуальны по правилам источника.",
    evidence_within_grace: "Новых данных пока нет; пауза в пределах допустимого интервала.",
    voluntary_sampling: "Есть подтверждённые измерения. Новые измерения добавляются по мере необходимости; ежедневный сбор не ожидается.",
    event_window_confirmed_empty: "За проверенное окно активностей записи отсутствуют. Это подтверждённая пустота, а не пропуск проверки.",
    refresh_overdue: "Сохранённое обновление устарело.",
    expected_evidence_absent: "Ожидаемые новые данные не поступили.",
    reauth_required: "Источнику требуется повторный вход.",
    required_stream_unavailable: "Необходимый поток данных недоступен.",
    refresh_failed: "Последняя попытка обновления завершилась неудачно.",
    disabled: "Сбор отключён в настройках владельца.", not_requested: "Данные не запрашивались.",
    never_observed: "Сохранённых данных для оценки пока нет.",
    coverage_unknown: "Полнота проверенного периода неизвестна.",
    scope_unresolved: "Принадлежность данных этому потоку не установлена.",
    acquisition_incomplete: "Последнее получение данных не завершено полностью.",
    chronology_unresolved: "Недостаточно сведений о времени данных и обновлений.",
    invalid_chronology: "Временные сведения нельзя использовать для оценки свежести.",
    future_chronology: "Есть временные сведения из будущего; свежесть не определена."
  };
  const actions = {
    reauth_required: "Повтори вход в источник через существующий локальный процесс сбора.",
    refresh_overdue: "Проверь выполнение локального сбора и его последний отчёт.",
    expected_evidence_absent: "Проверь поступление данных и последний отчёт локального сбора.",
    refresh_failed: "Проверь ошибку в последнем отчёте локального сбора.",
    required_stream_unavailable: "Проверь доступность потока в последнем отчёте локального сбора."
  };
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function chip(state) {
    const key = Object.hasOwn(stateLabels, state) ? state : "unknown";
    const element = node("span", stateLabels[key], "status-chip owner-state " + key);
    element.dataset.ownerState = key;
    return element;
  }
  function ownerState(item) {
    if (item.state === "quiet" && item.reason_code === "event_window_confirmed_empty") return "confirmed_empty";
    return {fresh: "present", quiet: "present", stale: "partial", unavailable: "unavailable",
      unknown: "unknown", not_requested: "not_requested"}[item.state] || "unknown";
  }
  function details(title) {
    const element = node("details", undefined, "owner-details");
    element.append(node("summary", title));
    return element;
  }
  function chronology(item) {
    const facts = item.facts;
    const list = node("dl", undefined, "data-chronology");
    [
      ["Дата сохранённых данных", facts.latest_evidence_local_date || facts.latest_evidence_utc],
      ["Последняя попытка обновления", facts.last_relevant_attempt_utc],
      ["Последнее успешное обновление", facts.last_successful_refresh_utc]
    ].forEach(([label, value]) => {
      const row = node("div");
      row.append(node("dt", label), node("dd", value ? window.healthcheckOwnerDate(value, true) : "Неизвестно"));
      list.append(row);
    });
    return list;
  }
  function stream(item) {
    const element = node("li", undefined, "data-stream");
    element.dataset.scope = item.scope_key;
    element.append(node("h3", scopeLabels[item.scope_key] || "Другой поток данных"), chip(ownerState(item)));
    element.append(node("p", reasons[item.reason_code] || "Состояние требует проверки технических сведений."));
    element.append(chronology(item));
    return element;
  }
  function providerChronology(items) {
    const list = node("dl", undefined, "data-chronology");
    // This endpoint exposes chronology, not latest eligible metric values or clone age.
    // Do not substitute a refresh timestamp for a saved observation date.
    const dated = items.filter(item => item.facts.latest_evidence_local_date || item.facts.latest_evidence_utc);
    const knownDates = items.map(item => item.facts.latest_evidence_local_date).filter(Boolean).sort();
    const attempts = items.map(item => item.facts.last_relevant_attempt_utc).filter(Boolean)
      .sort((a, b) => Date.parse(a) - Date.parse(b));
    let dateText = "Неизвестны";
    if (knownDates.length) dateText = window.healthcheckOwnerDate(knownDates[0]) +
      (knownDates[0] !== knownDates[knownDates.length - 1] ? " — " + window.healthcheckOwnerDate(knownDates[knownDates.length - 1]) : "");
    else if (dated.length) dateText = "Есть временные отметки; см. потоки";
    if (knownDates.length && dated.length > knownDates.length) dateText += "; другие временные отметки — в потоках";
    [
      ["Даты сохранённых данных по потокам", dateText + (dated.length < items.length ? "; без даты: " + (items.length - dated.length) : "")],
      ["Последняя сохранённая попытка обновления", attempts.length ? window.healthcheckOwnerDate(attempts[attempts.length - 1], true) : "Неизвестна"]
    ].forEach(([label, value]) => {
      const row = node("div");
      row.append(node("dt", label), node("dd", value));
      list.append(row);
    });
    return list;
  }
  function providerAction(items) {
    const actionable = items.filter(item => item.actionable);
    if (!actionable.length) return node("p", "По правилам обязательных потоков действий нет. Подробности и дополнительные потоки — ниже.", "muted");
    const codes = new Set(actionable.map(item => item.reason_code));
    const instructions = [...codes].map(code => actions[code] ||
      "Проверь сведения о данных в последнем отчёте локального сбора.");
    // One provider action, with each distinct instruction retained once.
    return node("p", [...new Set(instructions)].join(" "), "data-actions uncertainty-note");
  }
  function validate(payload) {
    // A missing/partial response must not masquerade as a successful check.
    const states = ["fresh", "quiet", "stale", "unavailable", "unknown", "not_requested"];
    if (!payload || !payload.owner || !payload.providers || !Array.isArray(payload.components) ||
        !payload.collection_policy || typeof payload.evaluated_at_utc !== "string" ||
        typeof payload.evaluation_local_date !== "string" || !states.includes(payload.owner.state) ||
        !["garmin", "google"].every(key => payload.providers[key] && states.includes(payload.providers[key].state))) {
      throw new Error("invalid_response");
    }
    const found = new Set();
    for (const item of payload.components) {
      if (!item || !Object.hasOwn(scopeLabels, item.scope_key) || found.has(item.scope_key) ||
          !states.includes(item.state) || !["required", "optional"].includes(item.role) ||
          typeof item.actionable !== "boolean" || typeof item.reason_code !== "string" ||
          item.provider !== (item.scope_key === "weight" ? "weight" : item.scope_key.split(":")[0]) ||
          !item.facts || typeof item.facts !== "object") throw new Error("invalid_response");
      found.add(item.scope_key);
    }
    if (found.size !== Object.keys(scopeLabels).length) throw new Error("invalid_response");
    return payload;
  }
  const failures = {
    timeout: "Проверка не завершилась за 15 секунд. Повтори её; если это повторяется, передай этот код для диагностики локального чтения.",
    network_error: "Браузер не получил ответ локального приложения. Проверь, что оно запущено, и повтори проверку.",
    database_unavailable: "Не удалось прочитать локальное хранилище. Проверь готовность профиля и базы данных через существующий локальный процесс.",
    invalid_request: "Локальное приложение отклонило параметры проверки. Перезагрузи страницу и проверь дату и время устройства.",
    invalid_response: "Ответ локального приложения не соответствует ожидаемому формату. Перезагрузи страницу; если ошибка повторяется, передай этот код для проверки совместимости UI и API.",
    endpoint_error: "Локальное приложение вернуло ошибку. Повтори проверку; если это повторяется, передай HTTP-статус и код ниже для диагностики.",
    check_failed: "Не удалось показать результат проверки. Перезагрузи страницу и передай этот код, если ошибка повторяется."
  };
  function render(payload) {
    const policy = payload.collection_policy;
    if (!["valid", "absent"].includes(policy.status)) {
      host.append(node("p", "Настройки сбора недоступны или некорректны. Состояния ниже не подтверждают действующие настройки; проверь локальный файл настроек сбора.", "uncertainty-note"));
    }
    const grid = node("div", undefined, "grid data-source-grid");
    [ ["garmin", "Garmin"], ["google", "Google"], ["weight", "Подтверждённые измерения веса"] ].forEach(([provider, label]) => {
      const items = payload.components.filter(item => item.provider === provider);
      const card = node("section", undefined, "card data-source-card");
      card.dataset.provider = provider;
      card.append(node("h3", label));
      const summary = provider === "weight" ? items[0] : payload.providers[provider];
      const status = chip(ownerState(summary));
      if (provider !== "weight" && summary.state === "unavailable") status.textContent = "Обновление или подключение требует внимания";
      card.append(node("p", provider === "weight" ? "Сохранённые измерения" : "Свежесть обязательных потоков"), status);
      if (summary.state === "stale") card.append(node("p", "Данные устарели; актуальное состояние по ним не подтверждено.", "uncertainty-note"));
      if (provider !== "weight") {
        card.append(providerChronology(items), providerAction(items));
        const streamStates = {fresh: "актуальны", quiet: "пауза / пустое окно", stale: "устарели",
          unavailable: "обновление / доступ недоступны", unknown: "не определены", not_requested: "не запрашивались"};
        const counts = Object.keys(streamStates).map(state => {
          const count = items.filter(item => item.state === state).length;
          return count ? streamStates[state] + ": " + count : null;
        }).filter(Boolean);
        card.append(node("p", "Потоки — " + counts.join(" · "), "muted"));
      }
      const list = node("ul", undefined, "data-streams");
      items.forEach(item => list.append(stream(item)));
      if (provider !== "weight") {
        const extra = details("Состояние и даты потоков: " + items.length);
        extra.append(node("p", "Дополнительные потоки не меняют общий вывод обязательных потоков. Ошибки обновления не означают, что сохранённая история отсутствует.", "muted"));
        extra.append(list);
        card.append(extra);
      } else card.append(list);
      grid.append(card);
    });
    host.append(grid);
    const technical = details("Технические детали");
    technical.append(node("pre", JSON.stringify(payload, null, 2), "provenance"));
    host.append(technical);
  }
  async function refresh() {
    if (button.disabled) return;
    button.disabled = true;
    host.replaceChildren();
    clock.textContent = "";
    host.setAttribute("aria-busy", "true");
    feedback.setAttribute("role", "status");
    delete feedback.dataset.failureCode;
    feedback.replaceChildren(chip("loading"));
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    let failure = "network_error";
    let httpStatus;
    try {
      const now = new Date();
      const localDate = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
      const params = new URLSearchParams({evaluated_at_utc: now.toISOString(), evaluation_local_date: localDate});
      const response = await fetch("/api/source-freshness?" + params, {
        signal: controller.signal, cache: "no-store", headers: {Accept: "application/json"}
      });
      httpStatus = response.status;
      if (!response.ok) {
        failure = response.status === 422 ? "invalid_request" : "endpoint_error";
        // Only a documented, fixed code is accepted. Never display server text.
        try {
          const error = await response.json();
          if (response.status === 503 && error.code === "database_unavailable") failure = error.code;
        } catch (_) { /* Non-JSON HTTP failures still retain their HTTP status. */ }
        throw new Error("endpoint_error");
      }
      failure = "invalid_response";
      const payload = validate(await response.json());
      failure = "check_failed";
      render(payload);
      clock.textContent = "Проверено (UTC): " + window.healthcheckOwnerDate(payload.evaluated_at_utc, true) + ". Локальная дата оценки: " + window.healthcheckOwnerDate(payload.evaluation_local_date) + ".";
      feedback.replaceChildren(node("p", "Проверка сохранённых состояний завершена. Даты данных и обновления показаны отдельно."));
    } catch (_) {
      if (controller.signal.aborted) failure = "timeout";
      host.replaceChildren();
      clock.textContent = "";
      feedback.setAttribute("role", "alert");
      feedback.dataset.failureCode = failure;
      feedback.replaceChildren(chip("error"), node("p", failures[failure]),
        node("p", "Состояние источников неизвестно. Очередь импорта показана отдельно."),
        node("p", "Код: " + failure + (httpStatus ? " · HTTP " + httpStatus : ""), "muted"));
    } finally {
      clearTimeout(timeout);
      host.setAttribute("aria-busy", "false");
      button.disabled = false;
    }
  }
  button.hidden = false;
  button.addEventListener("click", refresh);
  refresh();
})();
