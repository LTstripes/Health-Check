/* Owner-first Weight presentation. Analytics/canonical semantics unchanged; UI only translates. */
(function () {
  const dataNode = document.getElementById("dashboard-data");
  if (dataNode) {
    const payload = JSON.parse(dataNode.textContent);
    renderDashboard(payload);
  }
  bindReview();

  const STATE_LABELS = {
    present: "Данные доступны",
    partial: "Данные доступны частично",
    confirmed_empty: "За период записей нет",
    unknown: "Состояние данных не определено",
    unavailable: "Источник данных недоступен",
    insufficient: "Недостаточно данных",
    not_requested: "Не запрашивалось",
    loading: "Загрузка данных",
    error: "Не удалось выполнить запрос",
    no_change: "Изменений не обнаружено"
  };

  const REASON_TEXT = {
    no_data: "Нет подтверждённых измерений.",
    no_data_in_window: "В выбранном окне нет подтверждённых измерений.",
    insufficient_observations: "Недостаточно измерений для надёжного показателя.",
    insufficient_span: "Недостаточно охвата по времени для надёжного показателя.",
    insufficient_evidence: "Принятых данных недостаточно для этого показателя.",
    not_enough_points: "Недостаточно измерений для надёжного показателя.",
    no_canonical_run: "Нет принятого расчёта.",
    database_unavailable: "Локальное хранилище не готово.",
    missing_session: "Нет подходящей сессии измерений.",
    missing_weight: "Нет веса для сравнения.",
    missing_composition_evidence: "Нет подходящих данных состава тела.",
    cross_session: "Измерения из разных сессий нельзя объединять.",
    conflicting_observed_date: "Даты измерений не совпадают.",
    incompatible_algorithm_group: "Другой алгоритм; сравнение через границу недоступно.",
    insufficient_gap: "Интервал между измерениями меньше 28 дней.",
    weight_diff_exceeds_threshold: "Вес отличается более чем на 1%.",
    source_muscle_not_lean: "Мышцы источника — не сухая масса."
  };

  function renderDashboard(payload) {
    const series = payload.series || {};
    const summary = payload.summary || {};
    drawWeightChart(series);
    renderTrendStatus(series);
    renderRate(summary.rate || {});
    renderCoverage(summary.coverage);
    renderLatestComposition(summary.latest_composition || {});
    renderSimilar(summary.similar_weight || {});
    renderCompositionGroups(series.composition_by_group || {});
  }

  function fmt(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "недоступно";
    }
    return Number(value).toFixed(digits);
  }

  function ownerState(available, reason) {
    if (available === true) return "present";
    const token = String(reason || "unknown");
    if (["insufficient_observations", "insufficient_span", "insufficient_evidence", "not_enough_points", "insufficient_gap"].includes(token)) {
      return "insufficient";
    }
    if (["unknown", "", "none", "None"].includes(token)) return "unknown";
    return "unavailable";
  }

  function reasonText(reason) {
    const token = String(reason || "");
    if (REASON_TEXT[token]) return REASON_TEXT[token];
    if (token.startsWith("missing_")) return "Нет подходящих данных.";
    if (token.startsWith("invalid_")) return "Данные непригодны для этого показателя.";
    return "Подробности доступны в технических данных.";
  }

  function chip(state) {
    const key = STATE_LABELS[state] ? state : "unknown";
    return '<span class="status-chip owner-state ' + key + '" data-owner-state="' + key + '">' + STATE_LABELS[key] + "</span>";
  }

  function renderTrendStatus(series) {
    const node = document.getElementById("trend-status");
    if (!node) return;
    if (series.trend_available) {
      node.textContent =
        "Тренд доступен · " +
        (series.input_count || 0) +
        " подтверждённых наблюдений";
    } else {
      const state = ownerState(false, series.trend_reason);
      node.innerHTML =
        chip(state) +
        " <span>" + reasonText(series.trend_reason) + " Это не означает ноль.</span>";
    }
  }

  function renderRate(rate) {
    const node = document.getElementById("rate-panel");
    if (!node) return;
    if (!rate.available) {
      node.innerHTML =
        "<p>" + chip(ownerState(false, rate.reason)) + "</p><p class=\"muted\">" +
        reasonText(rate.reason) +
        " Отсутствующий темп не показан как 0.</p>";
      return;
    }
    node.innerHTML =
      "<p><strong>" +
      fmt(rate.slope_kg_per_week, 3) +
      " кг/нед.</strong></p>" +
      "<p class=\"muted\">" +
      rate.observation_count +
      " точек за " +
      rate.covered_span_days +
      " дней (" +
      (rate.window_start_date || "") +
      " — " +
      (rate.window_end_date || "") +
      ").</p>";
  }

  function renderCoverage(coverage) {
    const node = document.getElementById("coverage-panel");
    if (!node) return;
    if (!coverage) {
      node.innerHTML =
        "<p>" + chip("unavailable") + "</p><p class=\"muted\">" +
        reasonText("no_data") +
        " Это не означает ноль.</p>";
      return;
    }
    const counts = coverage.status_counts || {};
    const missing = function (value) {
      return value === null || value === undefined ? "недоступно" : value;
    };
    node.innerHTML =
      "<ul>" +
      "<li>Даты наблюдений: " +
      (coverage.observed_dates ? coverage.observed_dates.length : 0) +
      "</li>" +
      "<li>Закрытые интервалы: " +
      missing(coverage.covered_bin_count) +
      " / " +
      missing(coverage.expected_bin_count) +
      "</li>" +
      "<li>Свежесть (дней): " +
      missing(coverage.freshness_days) +
      "</li>" +
      "<li>Самый длинный пропуск (дней): " +
      missing(coverage.longest_gap_days) +
      "</li>" +
      "<li>Состояния — доступно " +
      (counts.present || 0) +
      ", неизвестно " +
      (counts.unknown || 0) +
      ", недоступно " +
      (counts.unavailable || 0) +
      ", сбой " +
      (counts.failed || 0) +
      ", пусто " +
      (counts.confirmed_empty || 0) +
      "</li>" +
      "</ul>";
  }

  function renderLatestComposition(item) {
    const node = document.getElementById("composition-latest");
    if (!node) return;
    if (!item.available) {
      node.innerHTML =
        "<p>" + chip(ownerState(false, item.reason)) + "</p><p class=\"muted\">" +
        reasonText(item.reason) +
        "</p>";
      return;
    }
    node.innerHTML =
      "<p>Жир " +
      fmt(item.body_fat_pct, 1) +
      "% (источник)</p>" +
      "<p>Оценка жировой массы " +
      fmt(item.estimated_fat_mass_kg, 1) +
      " кг (расчёт Health-Check)</p>" +
      "<p>Оценка сухой массы " +
      fmt(item.estimated_lean_mass_kg, 1) +
      " кг (расчёт Health-Check)</p>" +
      "<p class=\"muted\">Группа " +
      escapeHtml(item.compatibility_group || "неизвестна") +
      ".</p>";
  }

  function renderSimilar(item) {
    const node = document.getElementById("similar-panel");
    if (!node) return;
    if (!item.available) {
      node.innerHTML =
        "<p>" + chip(ownerState(false, item.reason)) + "</p><p class=\"muted\">" +
        reasonText(item.reason) +
        "</p>";
      return;
    }
    node.innerHTML =
      "<p>" +
      escapeHtml(item.earlier_date) +
      " → " +
      escapeHtml(item.later_date) +
      " (" +
      item.days_apart +
      " дней)</p>" +
      "<p>Вес " +
      fmt(item.earlier_weight_kg, 1) +
      " → " +
      fmt(item.later_weight_kg, 1) +
      " кг</p>" +
      "<p>Жир " +
      fmt(item.earlier_body_fat_pct, 1) +
      " → " +
      fmt(item.later_body_fat_pct, 1) +
      " п.п. (источник)</p>" +
      "<p class=\"muted\">Та же группа " +
      escapeHtml(item.compatibility_group || "") +
      ". Не утверждение о реальном росте мышц или потере жира.</p>";
  }

  function renderCompositionGroups(groups) {
    const node = document.getElementById("composition-groups");
    if (!node) return;
    const names = Object.keys(groups);
    if (!names.length) {
      node.innerHTML = "<p>" + chip("unavailable") + '</p><p class="muted">Нет подтверждённого ряда состава тела. Это не означает ноль.</p>';
      return;
    }
    node.innerHTML = "";
    names.forEach(function (group) {
      const wrap = document.createElement("div");
      wrap.innerHTML = "<h3>Группа алгоритма <code>" + escapeHtml(group) + "</code></h3>";
      const chart = document.createElement("div");
      chart.className = "chart";
      wrap.appendChild(chart);
      node.appendChild(wrap);
      drawCompositionChart(chart, groups[group], group);
    });
  }

  function drawWeightChart(series) {
    const host = document.getElementById("weight-chart");
    if (!host) return;
    const raw = series.raw_points || [];
    const trend = series.trend_points || [];
    if (!raw.length && !trend.length) {
      host.innerHTML = "<p>" + chip("unavailable") + '</p><p class="muted">Нет подтверждённых измерений веса. Это не означает ноль.</p>';
      return;
    }
    const points = raw.map(function (item) {
      return { date: item.observed_date, value: item.value_kg, id: item.evidence_id, kind: "raw", provenance: item.provenance };
    });
    const trendPoints = trend.map(function (item) {
      return { date: item.observed_date, value: item.trend_kg, kind: "trend" };
    });
    const allValues = points.concat(trendPoints).map(function (item) { return item.value; });
    if (series.goal_kg !== null && series.goal_kg !== undefined) allValues.push(series.goal_kg);
    host.innerHTML = "";
    host.appendChild(
      svgSeries(points, trendPoints, series.goal_kg, allValues, function (point) {
        showProvenance(point.provenance || { evidence_id: point.id });
      })
    );
  }

  function drawCompositionChart(host, points, group) {
    const fat = (points || [])
      .filter(function (item) { return item.body_fat_pct !== null && item.body_fat_pct !== undefined; })
      .map(function (item) {
        return { date: item.observed_date, value: item.body_fat_pct, kind: "raw" };
      });
    if (!fat.length) {
      host.innerHTML = '<p class="muted">Нет точек жира в ' + escapeHtml(group) + ".</p>";
      return;
    }
    host.appendChild(svgSeries(fat, [], null, fat.map(function (item) { return item.value; }), null, "%"));
    const scroller = document.createElement("div");
    scroller.className = "table-scroll";
    scroller.setAttribute("tabindex", "0");
    scroller.setAttribute("role", "region");
    scroller.setAttribute("aria-label", "Состав тела, прокрутка таблицы");
    const table = document.createElement("table");
    table.innerHTML =
      "<thead><tr><th>Дата</th><th>Жир % (источник)</th><th>Оценка жира кг (расчёт)</th><th>Оценка сухой массы кг (расчёт)</th><th>Мышцы источника кг</th></tr></thead>";
    const body = document.createElement("tbody");
    points.forEach(function (item) {
      const row = document.createElement("tr");
      row.innerHTML =
        "<td>" +
        escapeHtml(item.observed_date) +
        "</td><td>" +
        fmt(item.body_fat_pct, 1) +
        "</td><td>" +
        fmt(item.estimated_fat_mass_kg, 1) +
        "</td><td>" +
        fmt(item.estimated_lean_mass_kg, 1) +
        "</td><td>" +
        (item.source_muscle_mass_kg === null || item.source_muscle_mass_kg === undefined
          ? "недоступно"
          : fmt(item.source_muscle_mass_kg, 1)) +
        "</td>";
      body.appendChild(row);
    });
    table.appendChild(body);
    scroller.appendChild(table);
    host.appendChild(scroller);
  }

  function svgSeries(rawPoints, trendPoints, goal, values, onClick, unit) {
    const width = 1000;
    const height = 280;
    const pad = { l: 48, r: 16, t: 16, b: 36 };
    const dates = rawPoints.concat(trendPoints).map(function (item) { return Date.parse(item.date); });
    const minX = Math.min.apply(null, dates);
    const maxX = Math.max.apply(null, dates);
    const minY = Math.min.apply(null, values);
    const maxY = Math.max.apply(null, values);
    const spanY = maxY === minY ? 1 : maxY - minY;
    const spanX = maxX === minX ? 1 : maxX - minX;
    const xOf = function (date) {
      return pad.l + ((Date.parse(date) - minX) / spanX) * (width - pad.l - pad.r);
    };
    const yOf = function (value) {
      return pad.t + (1 - (value - minY) / spanY) * (height - pad.t - pad.b);
    };
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("role", "img");
    svg.innerHTML =
      '<line x1="' +
      pad.l +
      '" y1="' +
      (height - pad.b) +
      '" x2="' +
      (width - pad.r) +
      '" y2="' +
      (height - pad.b) +
      '" stroke="#d9d0c3"/>' +
      '<line x1="' +
      pad.l +
      '" y1="' +
      pad.t +
      '" x2="' +
      pad.l +
      '" y2="' +
      (height - pad.b) +
      '" stroke="#d9d0c3"/>';
    if (goal !== null && goal !== undefined) {
      const gy = yOf(goal);
      const goalLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
      goalLine.setAttribute("x1", pad.l);
      goalLine.setAttribute("x2", width - pad.r);
      goalLine.setAttribute("y1", gy);
      goalLine.setAttribute("y2", gy);
      goalLine.setAttribute("stroke", "#5c4d86");
      goalLine.setAttribute("stroke-dasharray", "6 4");
      goalLine.setAttribute("data-series", "goal");
      svg.appendChild(goalLine);
    }
    if (trendPoints.length > 1) {
      const d = trendPoints
        .map(function (item, index) {
          return (index ? "L" : "M") + xOf(item.date) + " " + yOf(item.value);
        })
        .join(" ");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", d);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "#9a4f1a");
      path.setAttribute("stroke-width", "2.5");
      path.setAttribute("data-series", "trend");
      svg.appendChild(path);
    }
    rawPoints.forEach(function (item) {
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", xOf(item.date));
      circle.setAttribute("cy", yOf(item.value));
      circle.setAttribute("r", 4.5);
      circle.setAttribute("fill", "#1d4e89");
      circle.setAttribute("data-series", "raw");
      circle.setAttribute("data-evidence-id", item.id || "");
      circle.setAttribute("tabindex", "0");
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = item.date + " · " + fmt(item.value, 1) + (unit || " кг");
      circle.appendChild(title);
      if (onClick) {
        circle.addEventListener("click", function () { onClick(item); });
        circle.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") onClick(item);
        });
      }
      svg.appendChild(circle);
    });
    return svg;
  }

  function showProvenance(info) {
    const node = document.getElementById("provenance-panel");
    if (!node) return;
    const missing = "недоступно";
    const lines = [
      "evidence_id: " + (info.evidence_id || ""),
      "provider: " + (info.provider_code || missing) + " (" + (info.provider_display_name || "") + ")",
      "device: " + (info.device_code || missing) + " (" + (info.device_display_name || "") + ")",
      "input_method: " + (info.input_method || missing),
      "source_application: " + (info.source_application || missing),
      "algorithm: " + (info.algorithm_code || missing) + " @ " + (info.algorithm_version || missing),
      "compatibility_group: " + (info.compatibility_group || missing),
      "temporal_precision: " + (info.temporal_precision || missing),
      "source_local_date: " + (info.source_local_date || missing),
      "source_timestamp_utc: " + (info.source_timestamp_utc || "null (date-only, no invented midnight)"),
      "artifact_content_hash: " + (info.artifact_content_hash || missing)
    ];
    node.classList.remove("empty");
    node.textContent = lines.join("\n");
  }

  function bindReview() {
    const boxes = Array.prototype.slice.call(document.querySelectorAll(".candidate-select"));
    if (!boxes.length) return;
    const preview = document.getElementById("commit-preview");
    const confirmIds = document.getElementById("confirm-ids");
    const rejectIds = document.getElementById("reject-ids");
    const confirmButton = document.getElementById("confirm-button");
    const rejectButton = document.getElementById("reject-button");
    function refresh() {
      const selected = boxes.filter(function (box) { return box.checked; });
      if (confirmIds) confirmIds.innerHTML = "";
      if (rejectIds) rejectIds.innerHTML = "";
      selected.forEach(function (box) {
        ["confirm-ids", "reject-ids"].forEach(function (id) {
          const host = document.getElementById(id);
          if (!host) return;
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = "candidate_ids";
          input.value = box.value;
          host.appendChild(input);
        });
      });
      if (confirmButton) confirmButton.disabled = selected.length === 0;
      if (rejectButton) rejectButton.disabled = selected.length === 0;
      if (!preview) return;
      if (!selected.length) {
        preview.classList.add("empty");
        preview.textContent = "Выбери кандидатов, чтобы увидеть итоговые значения.";
        return;
      }
      const items = selected.map(function (box) {
        const row = box.closest(".candidate-row");
        return (
          row.getAttribute("data-metric") +
          ": " +
          row.getAttribute("data-value") +
          " " +
          (row.getAttribute("data-unit") || "") +
          " на " +
          (row.getAttribute("data-date") || "неизвестная дата") +
          (row.getAttribute("data-committed") === "true" ? " (уже подтверждено, повтор)" : " (будет подтверждено)")
        );
      });
      preview.classList.remove("empty");
      preview.innerHTML = "<ul>" + items.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("") + "</ul>";
    }
    boxes.forEach(function (box) { box.addEventListener("change", refresh); });
    refresh();
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();
