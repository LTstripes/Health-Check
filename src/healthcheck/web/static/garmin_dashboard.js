(function () {
  const dataNode = document.getElementById("garmin-dashboard-data");
  if (!dataNode) return;
  const payload = JSON.parse(dataNode.textContent || "{}");
  const names = JSON.parse(document.getElementById("activity-metric-names").textContent);
  const state = { sourceId: (payload.source_selection || {}).selected_source_id || "",
    activities: payload.activities || [], tickets: {} };
  const labels = { present: "Данные доступны", partial: "Данные доступны частично",
    confirmed_empty: "За период записей нет", unknown: "Состояние данных не определено",
    unavailable: "Источник данных недоступен", insufficient: "Недостаточно данных",
    not_requested: "Не запрашивалось", loading: "Загрузка данных",
    error: "Не удалось выполнить запрос", no_change: "Изменений не обнаружено" };
  const activityNames = { cycling: "Велотренировка", running: "Бег", walking: "Ходьба",
    swimming: "Плавание", strength_training: "Силовая тренировка", tennis: "Теннис" };
  const units = { seconds: "с", meters: "м", "m/s": "м/с", bpm: "уд/мин",
    watts: "Вт", rpm: "об/мин", points: "баллы", percent: "%", "%": "%" };

  bindForms();
  populateActivities(state.activities);
  renderMetricWording();
  showMode();
  window.addEventListener("hashchange", showMode);
  if (payload.series) renderSeries(payload.series);
  else renderNoSeries(payload.unavailable_reason || (payload.source_selection || {}).reason || "no_data");

  function showMode() {
    const mode = location.hash === "#training-recovery" ? "training-recovery" : "activity-journal";
    document.querySelectorAll("[data-activity-panel]").forEach(el => { el.hidden = el.id !== mode; });
    document.querySelectorAll("[data-activity-mode]").forEach(el => {
      const selected = el.dataset.activityMode === mode;
      el.classList.toggle("selected", selected);
      if (selected) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
    });
  }
  function bindForms() {
    document.getElementById("garmin-source-id")?.addEventListener("change", () => {
      setText("source-status", value("garmin-source-id") === state.sourceId ?
        "Показаны данные применённого источника Garmin." :
        "Источник ещё не применён. Показанные данные относятся к предыдущему источнику; нажми «Применить источник».");
    });
    document.getElementById("source-form")?.addEventListener("submit", event => {
      event.preventDefault();
      const params = new URLSearchParams();
      const source = value("garmin-source-id"), metric = value("metric-code");
      if (source) params.set("garmin_source_id", source);
      if (metric) params.set("metric_code", metric);
      if (value("series-start")) params.set("start_date", value("series-start"));
      if (value("series-end")) params.set("end_date", value("series-end"));
      window.location = "/garmin?" + params.toString() + location.hash;
    });
    document.getElementById("series-form").addEventListener("submit", event => { event.preventDefault(); loadSeries(); });
    document.getElementById("metric-code").addEventListener("change", renderMetricWording);
    document.getElementById("activity-form").addEventListener("submit", event => { event.preventDefault(); loadActivityComparison(); });
    ["activity-a", "activity-b"].forEach(id => document.getElementById(id).addEventListener("change", () => {
      resetRequest("activity");
      setHtml("activity-result", "");
      setText("result-identity", "Пара сессий изменена; сравнение ещё не выполнено");
      updateActivitySelection();
    }));
    document.getElementById("lag-form").addEventListener("submit", event => { event.preventDefault(); loadLaggedAssociation(); });
  }
  function value(id) { return document.getElementById(id).value; }
  function requireSourceId() {
    const selector = document.getElementById("garmin-source-id");
    if (!state.sourceId || (selector && selector.value !== state.sourceId)) {
      throw new Error("Сначала примени источник Garmin выше. Сессии разных источников не объединяются.");
    }
    return state.sourceId;
  }
  // Each panel owns its applied query. New submissions clear old results and
  // evidence; late completions cannot replace a more recent request.
  function request(panel, url, params, context, render) {
    const ticket = (state.tickets[panel] || 0) + 1;
    state.tickets[panel] = ticket;
    const target = panel === "series" ? "series-chart" : panel + "-result";
    setHtml(target, chip("loading") + "<p>" + escapeHtml(context) + "</p>");
    if (panel === "series") { setHtml("series-summary", ""); setHtml("series-coverage", ""); setText("series-context", context); }
    setText(panel + "-evidence", "");
    setText("result-identity", "Загрузка нового результата");
    const node = document.getElementById(panel + "-result");
    node.setAttribute("aria-busy", "true");
    fetchJson(url + "?" + params.toString()).then(body => {
      if (state.tickets[panel] !== ticket) return;
      render(body);
      if (panel === "series") setText("series-context", context);
      else document.getElementById(target).insertAdjacentHTML("afterbegin", "<p class=\"muted\">" + escapeHtml(context) + "</p>");
    }).catch(err => {
      if (state.tickets[panel] !== ticket) return;
      setHtml(target, '<div role="alert">' + chip("error") + "<p>Попробуй повторить запрос. Предыдущий результат не показан.</p></div>");
      setText(panel + "-evidence", JSON.stringify(err.body || { reason: "request_failed" }, null, 2));
      setText("result-identity", "Запрос не выполнен");
    }).finally(() => { if (state.tickets[panel] === ticket) node.setAttribute("aria-busy", "false"); });
  }
  function loadSeries() {
    resetRequest("series");
    let sourceId;
    try { sourceId = requireSourceId(); } catch (err) { renderNoSeries(err.message); return; }
    const params = new URLSearchParams({ garmin_source_id: sourceId, metric_code: value("metric-code"), start_date: value("series-start"), end_date: value("series-end") });
    const context = metricName(value("metric-code")) + " · " + ownerDate(value("series-start")) + " — " + ownerDate(value("series-end"));
    request("series", "/api/garmin/series", params, context, renderSeries);
  }
  function loadActivityComparison() {
    resetRequest("activity");
    let sourceId;
    try { sourceId = requireSourceId(); } catch (err) { setHtml("activity-result", unavailable(err.message)); return; }
    const a = value("activity-a"), b = value("activity-b");
    if (!a || !b || a === b) { updateActivitySelection(); return; }
    const params = new URLSearchParams({ garmin_source_id: sourceId, activity_record_ids: [a, b].join(","), reference_activity_id: a });
    request("activity", "/api/garmin/activity-comparison", params, "A: " + sessionLabel(a) + " · B: " + sessionLabel(b), renderActivityResult);
  }
  function loadLaggedAssociation() {
    resetRequest("lag");
    let sourceId;
    try { sourceId = requireSourceId(); } catch (err) { setHtml("lag-result", unavailable(err.message)); return; }
    const params = new URLSearchParams({ garmin_source_id: sourceId, x_metric_code: value("x-metric-code"), y_metric_code: value("y-metric-code"), start_date: value("lag-start"), end_date: value("lag-end"), lag_days: value("lag-days") });
    const context = metricName(value("x-metric-code")) + " / " + metricName(value("y-metric-code")) + " · " + ownerDate(value("lag-start")) + " — " + ownerDate(value("lag-end")) + " · сдвиги: " + value("lag-days");
    request("lag", "/api/garmin/lagged-association", params, context, renderLagResult);
  }
  function fetchJson(url) {
    return fetch(url, { method: "GET", headers: { Accept: "application/json" } }).then(response => response.json().then(body => {
      if (!response.ok) { const error = new Error("request_failed"); error.body = body; throw error; }
      return body;
    }));
  }
  function resetRequest(panel) {
    state.tickets[panel] = (state.tickets[panel] || 0) + 1;
    document.getElementById(panel + "-result").setAttribute("aria-busy", "false");
    setText(panel + "-evidence", "");
    if (panel === "series") { setHtml("series-summary", ""); setHtml("series-coverage", ""); }
  }
  function activityLabel(activity, index) {
    return "Сессия " + (index + 1) + " · " + (activityNames[activity.activity_type] || "Другой вид активности") + " · " + ownerDate(activity.source_local_date || activity.local_wall_time || activity.measured_at_utc);
  }
  function sessionLabel(id) {
    const index = state.activities.findIndex(a => a.record_id === id);
    return index < 0 ? "Сессия" : activityLabel(state.activities[index], index);
  }
  function populateActivities(activities) {
    ["activity-a", "activity-b"].forEach(id => {
      const select = document.getElementById(id);
      select.add(new Option("Выбери сессию", ""));
      activities.forEach((activity, index) => select.add(new Option(activityLabel(activity, index), activity.record_id)));
      select.disabled = activities.length < 2;
    });
    updateActivitySelection();
  }
  function updateActivitySelection() {
    const a = value("activity-a"), b = value("activity-b");
    document.querySelector("#activity-form button").disabled = !a || !b || a === b;
    setText("activity-selection-hint", state.activities.length < 2 ?
      "Для сравнения нужны две сохранённые сессии одного источника Garmin. Пока их недостаточно; проверь раздел «Данные»." :
      a && a === b ? "Выбрана одна и та же сессия. Выбери другую сессию B." :
      !a ? "Выбери сессию A — основу сравнения." : !b ? "Теперь выбери другую сессию B." :
      "A: " + sessionLabel(a) + " · B: " + sessionLabel(b) + ". Нажми «Сравнить A и B»; результат покажет B минус A.");
  }
  function renderMetricWording() {
    const code = value("metric-code");
    setText("metric-wording", code === "sleep_score" ? "Оценка сна Garmin не доказывает полноту длительности, стадий или дневного сна и не является оценкой восстановления." :
      ["training_effect", "acute_training_load"].includes(code) ? "Показатель Garmin относится к отдельной сессии, а не к дневной готовности или восстановлению." : "Пропуски не заменяются нулём; отдельные измерения и дневные показатели различаются.");
  }
  function renderNoSeries(reason) {
    setHtml("series-chart", unavailable("Нет пригодного ряда. Пропущенные значения не показаны как 0."));
    setHtml("series-summary", ""); setHtml("series-coverage", ""); setText("series-context", "Результат за период недоступен");
    setText("series-evidence", JSON.stringify({ reason }, null, 2)); setText("result-identity", "Нет результата ряда");
  }
  function renderSeries(series) {
    const points = series.points || [], plottable = points.filter(p => p.status === "usable" || p.status === "zero");
    const chart = document.getElementById("series-chart");
    if (!plottable.length) chart.innerHTML = unavailable("Нет пригодных значений. Это не нулевая нагрузка.");
    else {
      // Coordinate projection only. Missing/excluded calendar days break the
      // line; no interpolation, pooling or analytics are computed here.
      const width = Math.max(640, points.length * 28), height = 260, pad = 28;
      const ys = plottable.map(p => Number(p.value)), minY = Math.min(...ys), maxY = Math.max(...ys), spanY = maxY - minY || 1;
      let path = "", previous = null, circles = "";
      points.forEach((point, index) => {
        if (point.status !== "usable" && point.status !== "zero") { previous = null; return; }
        const x = pad + index / Math.max(points.length - 1, 1) * (width - pad * 2);
        const y = height - pad - (Number(point.value) - minY) / spanY * (height - pad * 2);
        const consecutive = previous && Date.parse(point.analytic_date) - Date.parse(previous.analytic_date) === 86400000;
        path += (consecutive ? " L" : " M") + x.toFixed(1) + "," + y.toFixed(1);
        circles += '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="4" fill="var(--series-1)"><title>' + escapeHtml(ownerDate(point.analytic_date) + " · " + fmt(point.value, 1)) + "</title></circle>";
        previous = point;
      });
      chart.innerHTML = '<svg viewBox="0 0 ' + width + ' ' + height + '" width="' + width + '" height="' + height + '" role="img" aria-label="Значения Garmin; пропуски разрывают линию"><path d="' + path + '" fill="none" stroke="var(--series-1)" stroke-width="2"/>' + circles + '</svg>';
    }
    const code = (series.metric_definition || {}).metric_code;
    setText("series-context", metricName(code) + " · " + ownerDate((series.query || {}).start_date) + " — " + ownerDate((series.query || {}).end_date));
    const a = series.availability || {}, b = series.baseline || {}, t = series.trend || {}, p = series.personal_percentile || {}, d = series.deviation || {};
    const missing = [a.missing_count, a.null_count, a.invalid_count, a.partial_count, a.not_computable_count, a.excluded_count].some(n => n > 0);
    let html = chip(!plottable.length ? "unavailable" : missing ? "partial" : "present");
    html += "<p>" + escapeHtml(metricName(code)) + " · единица: " + escapeHtml(units[(series.metric_definition || {}).unit] || "не предоставлена") + "</p>";
    html += "<p>Пригодных значений: " + fmt(a.usable_count, 0) + "; явных нулей: " + fmt(a.zero_count, 0) + "; исключено: " + fmt(a.excluded_count, 0) + ".</p>";
    if (missing) html += '<p class="uncertainty-note">Есть пропуски, исключения или неполные значения. Ряд не описывает весь период; неоднозначные дневные значения не объединяются.</p>';
    html += "<ul><li>Среднее в личном окне: " + available(b, () => fmt(b.mean)) + "</li><li>Медиана: " + available(b, () => fmt(b.median)) + "</li><li>Изменение в день: " + available(t, () => fmt(t.slope_per_day, 3)) + "</li><li>Процентиль в личном окне: " + available(p, () => fmt(p.value)) + "</li></ul>";
    html += "<p>Отклонение от личного окна: " + available(d, () => d.personal_baseline_deviation === true ? "выделено алгоритмом" : d.personal_baseline_deviation === false ? "не выделено алгоритмом" : "не определено") + ". Это не медицинский порог.</p>";
    setHtml("series-summary", html);
    // Exact availability.exclusions, excluded_count, ambiguous_daily_aggregate,
    // statuses and statistics remain in the untouched response disclosure.
    setText("series-evidence", JSON.stringify(series, null, 2));
    setText("series-coverage", "Подробное покрытие и исключения — в результате ниже.");
    identity(series);
  }
  function renderActivityResult(body) {
    let html = "<h3>Результат: B минус A</h3><p>Эффект и нагрузка Garmin относятся к сессии. «Не предоставлено» означает отсутствие пригодного значения; «Не вычисляется» — разницу или процент получить нельзя.</p>";
    (body.comparisons || []).forEach(block => {
      if (!block.same_activity_type) html += '<p class="uncertainty-note">Разные виды активности: часть показателей может быть несопоставима.</p>';
      html += '<div class="table-scroll"><table class="garmin-table"><thead><tr><th scope="col">Показатель</th><th scope="col">Сессия A</th><th scope="col">Сессия B</th><th scope="col">B − A</th><th scope="col">% к A</th><th scope="col">Сопоставимость / ограничение</th></tr></thead><tbody>';
      (block.metrics || []).forEach(m => {
        const field = id => (body.sessions || []).find(s => s.record_id === id)?.metric_coverage.find(c => c.metric_code === m.metric_code);
        const side = id => {
          const coverage = field(id);
          if (!coverage) return "Не предоставлено";
          if (coverage.reason === "metric_absent_from_projection") return "Не предоставлено";
          return statusValue(coverage.status, coverage.value, 1);
        };
        html += "<tr><th scope=\"row\">" + escapeHtml(metricName(m.metric_code)) + " · " + escapeHtml(units[m.unit] || "единица не предоставлена") + "</th><td>" + side(block.reference_record_id) + "</td><td>" + side(block.compared_record_id) + "</td><td>" + (m.status === "compared" ? fmt(m.absolute_delta, 1) : "Не вычисляется") + "</td><td>" + (m.percent_status === "computed" ? fmt(m.percent_delta, 1) : "Не вычисляется") + "</td><td>" + (m.reason || m.percent_reason ? escapeHtml(reasonText(m.reason || m.percent_reason)) : statusLabel(m.status)) + "</td></tr>";
      });
      html += "</tbody></table></div>";
    });
    setHtml("activity-result", html); setText("activity-evidence", JSON.stringify(body, null, 2)); identity(body);
  }
  function renderLagResult(body) {
    let html = '<div class="table-scroll"><table class="garmin-table"><thead><tr><th>Сдвиг, дней</th><th>Состояние</th><th>Связь (Спирмен)</th><th>Пар значений</th><th>Ограничение</th></tr></thead><tbody>';
    (body.lags || []).forEach(lag => {
      html += "<tr><td>" + fmt(lag.lag_days, 0) + "</td><td>" + statusLabel(lag.status) + "</td><td>" + fmt(lag.rho, 4) + "</td><td>" + fmt(lag.n, 0) + "</td><td>" + (lag.reason ? reasonText(lag.reason) : "—") + "</td></tr>";
    });
    html += "</tbody></table></div><p>Результат зависит от покрытия и исключений. Нет статистической значимости, причинных выводов или выбора лучшего сдвига.</p>";
    setHtml("lag-result", html); setText("lag-evidence", JSON.stringify(body, null, 2)); identity(body);
  }
  function identity(body) { setText("result-identity", [body.algorithm, body.rule_version, body.result_hash].join(" / ")); }
  function metricName(code) { return names[code] || "Другой показатель (определение в технических деталях)"; }
  function reasonText(reason) {
    if (reason === "zero_reference_percent") return "В сессии A указан ноль: процент относительно A не вычисляется";
    if (reason && reason.includes(";")) return reason.split(";").map(reasonText).join("; ");
    if (reason && /^(reference|compared):/.test(reason)) {
      const split = reason.indexOf(":");
      return (reason.slice(0, split) === "reference" ? "Сессия A: " : "Сессия B: ") + reasonText(reason.slice(split + 1));
    }
    const comparisonReasons = { metric_absent_from_projection: "показатель не предоставлен в сохранённой записи", missing: "значение не предоставлено", null: "Garmin не передал значение", invalid_metric: "значение некорректно", partial: "значение неполное", aggregation_mismatch: "разные способы агрегации", window_mismatch: "разные окна измерения", unit_mismatch: "единицы измерения различаются", ambiguous_cadence_source_field: "единица каденса не подтверждена", unsupported_speed_source_field: "нет подтверждённой средней скорости Garmin", unreviewed_source_field: "поле Garmin не подтверждено для сравнения", sides_not_comparable: "значения A и B нельзя сопоставить" };
    if (comparisonReasons[reason]) return comparisonReasons[reason];
    const reasons = { insufficient_paired_n: "Недостаточно пар значений", insufficient_usable_values: "Недостаточно пригодных значений", insufficient_temporal_sample: "Недостаточно дат для тренда", constant_or_degenerate_input: "Ряд постоянный или вырожденный: связь не вычисляется", mad_zero_or_non_finite: "Отклонение не вычисляется: разброс нулевой или некорректный", insufficient_samples: "Недостаточно значений", insufficient_pairs: "Недостаточно пар", constant_series: "Ряд не меняется: связь не вычисляется", different_activity_type: "Разные виды активности", reference_zero: "Опорное значение равно нулю: процент не вычисляется", zero_reference: "Опорное значение равно нулю: процент не вычисляется", ambiguous_daily_aggregate: "Неоднозначное дневное значение исключено", no_data: "Нет пригодных данных" };
    return reasons[reason] || "Есть ограничение сопоставимости или данных; точная причина — в технических деталях";
  }
  function statusLabel(status) {
    const text = { usable: "Данные доступны", zero: "Явный ноль", compared: "Сопоставлено", association_available: "Данные доступны", comparable: "Сопоставимо", not_comparable: "Несопоставимо", available: "Данные доступны", insufficient: "Недостаточно данных", missing: "Не предоставлено", null: "Не предоставлено", invalid: "Некорректное значение", partial: "Данные доступны частично", excluded: "Исключено", not_computable: "Не вычисляется", insufficient_data: "Недостаточно данных" };
    return escapeHtml(text[status] || labels[status] || labels.unknown);
  }
  function available(block, render) { return block.available ? render() : chip(block.reason && block.reason.includes("insufficient") ? "insufficient" : "unavailable") + " " + escapeHtml(reasonText(block.reason)); }
  function statusValue(status, val, digits) {
    if (status === "zero") return "0";
    return status === "usable" ? fmt(val, digits) : statusLabel(status);
  }
  function chip(key) { if (key === "present") return ""; return '<span class="status-chip owner-state ' + key + '" data-owner-state="' + key + '">' + labels[key] + "</span>"; }
  function unavailable(reason) { return chip("unavailable") + "<p>" + escapeHtml(reason) + "</p>"; }
  function ownerDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/.exec(String(value || ""));
    if (!match) return "Дата не указана";
    const months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
    const month = months[Number(match[2]) - 1];
    if (!month) return "Дата не указана";
    let text = Number(match[3]) + " " + month + " " + match[1];
    if (match[4]) text += ", " + match[4] + ":" + match[5];
    if (match[6]) text += ["Z", "+00:00"].includes(match[6]) ? " UTC" : " UTC" + match[6];
    return text;
  }
  function fmt(val, digits = 1) { return val === null || val === undefined || !Number.isFinite(Number(val)) ? "Не предоставлено" : Number(val).toFixed(digits); }
  function setHtml(id, html) { const el = document.getElementById(id); if (el) el.innerHTML = html; }
  function setText(id, text) { const el = document.getElementById(id); if (el) el.textContent = text; }
  function escapeHtml(val) { return String(val).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
})();
