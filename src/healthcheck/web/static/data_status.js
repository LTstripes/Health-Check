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
      ["Последнее успешное обновление (UTC)", facts.last_successful_refresh_utc],
      ["Последние данные", facts.latest_evidence_local_date || facts.latest_evidence_utc]
    ].forEach(([label, value]) => {
      const row = node("div");
      row.append(node("dt", label), node("dd", value || "Неизвестно"));
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
    const actionable = payload.components.filter(item => item.actionable);
    const actionSection = node("section");
    actionSection.append(node("h3", "Что требует внимания"));
    if (actionable.length) {
      const list = node("ul", undefined, "data-actions uncertainty-note");
      actionable.forEach(item => {
        const provider = item.scope_key.startsWith("garmin:") ? "Garmin" : "Google";
        list.append(node("li", provider + " · " + scopeLabels[item.scope_key] + ": " +
          (actions[item.reason_code] || "Проверь сведения о данных в последнем отчёте локального сбора.")));
      });
      actionSection.append(list);
    } else {
      actionSection.append(node("p", "По правилам свежести обязательных потоков действий нет. Это не подтверждает полноту всей истории или наличие всех дополнительных данных."));
    }
    host.append(actionSection);
    const grid = node("div", undefined, "grid data-source-grid");
    [ ["garmin", "Garmin"], ["google", "Google"], ["weight", "Подтверждённые измерения веса"] ].forEach(([provider, label]) => {
      const items = payload.components.filter(item => item.provider === provider);
      const card = node("section", undefined, "card data-source-card");
      card.dataset.provider = provider;
      card.append(node("h3", label));
      const summary = provider === "weight" ? items[0] : payload.providers[provider];
      card.append(chip(ownerState(summary)));
      if (summary.state === "stale") card.append(node("p", "Данные устарели; актуальное состояние по ним не подтверждено.", "uncertainty-note"));
      if (provider !== "weight") card.append(node("p", "Общее состояние относится к обязательным потокам.", "muted"));
      const list = node("ul", undefined, "data-streams");
      items.filter(item => item.role === "required" || provider === "weight").forEach(item => list.append(stream(item)));
      card.append(list);
      const optional = items.filter(item => item.role === "optional" && provider !== "weight");
      if (optional.length) {
        const extra = details("Дополнительные потоки: " + optional.length);
        extra.append(node("p", "Их состояние не меняет общий статус обязательных потоков.", "muted"));
        const extraList = node("ul", undefined, "data-streams");
        optional.forEach(item => extraList.append(stream(item)));
        extra.append(extraList);
        card.append(extra);
      }
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
      clock.textContent = "Проверено (UTC): " + payload.evaluated_at_utc + ". Локальная дата оценки: " + payload.evaluation_local_date + ".";
      feedback.replaceChildren(chip(ownerState(payload.owner)));
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
