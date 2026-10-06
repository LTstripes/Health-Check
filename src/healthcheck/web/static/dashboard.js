/* Owner-first Weight presentation. Analytics/canonical semantics unchanged; UI only translates. */
(function () {
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

  const dataNode = document.getElementById("dashboard-data");
  if (dataNode) {
    const payload = JSON.parse(dataNode.textContent);
    renderDashboard(payload);
  }
  bindReview();

  function renderDashboard(payload) {
    const series = payload.series || {};
    const summary = payload.summary || {};
    drawWeightChart(series);
    renderTrendStatus(series);
    renderRate(summary.rate || {});
    renderCoverage(summary.coverage);
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
    const slope = rate.slope_kg_per_week;
    node.innerHTML =
      '<p>' + (slope > 0 ? 'Вес в среднем увеличивался' : slope < 0 ? 'Вес в среднем снижался' : 'Направленного изменения веса не обнаружено') + '.</p>' +
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
      "% (источник)</p>" +
      "<p class=\"muted\">Один метод расчёта. Не утверждение о реальном росте мышц или потере жира.</p>";
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
    names.forEach(function (group, index) {
      const wrap = document.createElement("div");
      wrap.className = 'weight-composition-group';
      wrap.innerHTML = '<h3>Ряд состава ' + (index + 1) + ' · отдельная группа метода</h3>';
      const dates = groups[group].map(function (item) { return item.observed_date; }).sort();
      const span = document.createElement('p');
      span.className = 'muted';
      span.textContent = dates.length ? 'Измерения этой группы: ' + readableDate(dates[0]) +
        (dates[0] === dates[dates.length - 1] ? '' : ' — ' + readableDate(dates[dates.length - 1])) +
        '. Показаны только значения выбранного показателя; точные даты — в таблице.' : 'В этой группе нет измерений.';
      wrap.appendChild(span);
      const label = document.createElement('label');
      label.textContent = 'Показатель ';
      const select = document.createElement('select');
      const metrics = [
        ['body_fat_pct', 'Жир % (источник)', '%'],
        ['estimated_fat_mass_kg', 'Оценка жира кг (Health-Check)', ' кг'],
        ['estimated_lean_mass_kg', 'Оценка сухой массы кг (Health-Check)', ' кг'],
        ['source_muscle_mass_kg', 'Мышцы кг (источник, отдельная оценка)', ' кг']
      ];
      metrics.forEach(function (metric) {
        const option = document.createElement('option');
        option.value = metric[0];
        option.textContent = metric[1];
        select.appendChild(option);
      });
      label.appendChild(select);
      wrap.appendChild(label);
      const chart = document.createElement("div");
      chart.className = "chart";
      wrap.appendChild(chart);
      const detail = document.createElement('div');
      detail.id = 'composition-detail-' + index;
      detail.setAttribute('role', 'status');
      detail.setAttribute('aria-live', 'polite');
      detail.setAttribute('aria-atomic', 'true');
      wrap.appendChild(detail);
      node.appendChild(wrap);
      function redraw() {
        const metric = metrics[select.selectedIndex];
        drawCompositionChart(chart, groups[group], metric, detail);
      }
      select.addEventListener('change', redraw);
      redraw();
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
    const composition = Object.values(series.composition_by_group || {}).flat();
    const points = raw.map(function (item) {
      // Exact evidence identity only: a date or equal weight cannot prove a session.
      const matches = composition.filter(function (entry) { return item.evidence_id && entry.weight_measurement_id === item.evidence_id; });
      return { date: item.observed_date, value: item.value_kg, id: item.evidence_id, kind: "raw", provenance: item.provenance, composition: matches };
    });
    const trendPoints = trend.map(function (item) {
      return { date: item.observed_date, value: item.trend_kg, kind: "trend" };
    });
    const allValues = points.concat(trendPoints).map(function (item) { return item.value; });
    if (series.goal_kg !== null && series.goal_kg !== undefined) allValues.push(series.goal_kg);
    host.innerHTML = "";
    host.appendChild(
      svgSeries(points, trendPoints, series.goal_kg, allValues, function (point) {
        showObservation(point);
      }, null, null, host)
    );
    if (points.length) showObservation(points[points.length - 1]);
  }

  function drawCompositionChart(host, points, metric, detailNode) {
    host.innerHTML = '';
    detailNode.innerHTML = '';
    const fat = (points || [])
      .filter(function (item) { return item[metric[0]] !== null && item[metric[0]] !== undefined; })
      .map(function (item) {
        return { date: item.observed_date, value: item[metric[0]], id: item.weight_measurement_id, kind: "raw", composition: [item], weight: item.weight_kg };
      });
    if (!fat.length) {
      host.innerHTML = '<p class="muted">Нет подтверждённых значений этого показателя. Это не означает ноль.</p>';
    } else {
      host.appendChild(svgSeries(fat, [], null, fat.map(function (item) { return item.value; }), function (point) {
        showObservation({ date: point.date, value: point.weight, id: point.id, composition: point.composition }, detailNode);
      }, metric[2], detailNode.id, host));
    }
    const detail = document.createElement('details');
    detail.innerHTML = '<summary>Все значения ряда</summary>';
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
    detail.appendChild(scroller);
    host.appendChild(detail);
  }

  function showObservation(point, detailNode) {
    const node = detailNode || document.getElementById('observation-detail');
    if (!node) return;
    let html = '<h3>Наблюдение · ' + escapeHtml(point.date) + '</h3><p>Вес ' + fmt(point.value, 1) + ' кг (источник)</p>';
    const items = point.composition || [];
    if (!items.length) html += '<p class="muted">Состав тела для этого наблюдения недоступен. Это не означает ноль.</p>';
    items.forEach(function (item, index) {
      if (items.length > 1) html += '<h4>Ряд состава ' + (index + 1) + '</h4>';
      html += '<dl class="weight-composition-values">';
      [
        ['Жир (источник)', item.body_fat_pct, '%'],
        ['Оценка жировой массы (Health-Check)', item.estimated_fat_mass_kg, ' кг'],
        ['Оценка сухой массы (Health-Check)', item.estimated_lean_mass_kg, ' кг'],
        ['Мышцы (источник, отдельная оценка)', item.source_muscle_mass_kg, ' кг']
      ].forEach(function (metric) {
        html += '<div><dt>' + metric[0] + '</dt><dd>' + (metric[1] === null || metric[1] === undefined ? 'недоступно' : fmt(metric[1], 1) + metric[2]) + '</dd></div>';
      });
      html += '</dl>';
    });
    node.innerHTML = html;
    node.classList.add('weight-observation');
    showProvenance(Object.assign({}, point.provenance || { evidence_id: point.id }, { composition: items }));
  }

  function readableDate(date) {
    return new Date(date).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }

  function svgSeries(rawPoints, trendPoints, goal, values, onClick, unit, detailId, host) {
    let width = Math.max(260, host.clientWidth);
    const height = 280;
    const pad = { l: 48, r: 16, t: 16, b: 52 };
    const dates = rawPoints.concat(trendPoints).map(function (item) { return Date.parse(item.date); });
    const minX = Math.min.apply(null, dates);
    const maxX = Math.max.apply(null, dates);
    const low = Math.min.apply(null, values);
    const high = Math.max.apply(null, values);
    const margin = Math.max((high - low) * 0.1, 0.5);
    const minY = low - margin;
    const maxY = high + margin;
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
    svg.setAttribute("role", "group");
    svg.setAttribute('aria-label', unit ? 'Состав тела, ' + unit.trim() : 'Вес, кг');
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
    function textLabel(x, y, text, anchor, axis) {
      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', x);
      label.setAttribute('y', y);
      label.setAttribute('text-anchor', anchor);
      label.setAttribute('class', 'weight-axis');
      label.setAttribute('data-axis', axis);
      label.textContent = text;
      svg.appendChild(label);
    }
    for (let index = 0; index <= 4; index++) {
      const value = minY + spanY * index / 4;
      textLabel(pad.l - 8, yOf(value) + 4, fmt(value, 1), 'end', 'y');
    }
    textLabel(pad.l, 12, unit ? unit.trim() : 'кг', 'start', 'unit');
    const dayMs = 86400000;
    function drawTimeAxis() {
      svg.querySelectorAll('[data-axis="x"], .weight-time-tick').forEach(function (node) { node.remove(); });
      const days = Math.round((maxX - minX) / dayMs);
      // Date-only points: never invent times or duplicate a day to fill the axis.
      let count = days ? Math.min(7, days + 1, Math.max(2, Math.floor((width - pad.l - pad.r) / 80) + 1)) : 1;
      while (count >= 1) {
        const labels = [];
        for (let index = 0; index < count; index++) {
          const timestamp = count === 1 ? minX : minX + Math.round(days * index / (count - 1)) * dayMs;
          const x = pad.l + ((timestamp - minX) / spanX) * (width - pad.l - pad.r);
          textLabel(x, height - pad.b + 22, '', index === 0 ? 'start' : index === count - 1 ? 'end' : 'middle', 'x');
          const label = svg.lastChild;
          label.setAttribute('data-date', new Date(timestamp).toISOString().slice(0, 10));
          const date = new Date(timestamp);
          [date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', timeZone: 'UTC' }), String(date.getUTCFullYear())].forEach(function (part, row) {
            const line = document.createElementNS('http://www.w3.org/2000/svg', 'tspan');
            line.setAttribute('x', x);
            line.setAttribute('dy', row ? '16' : '0');
            line.textContent = part;
            label.appendChild(line);
          });
          labels.push(label);
          const tick = document.createElementNS('http://www.w3.org/2000/svg', 'line');
          tick.setAttribute('class', 'weight-time-tick');
          tick.setAttribute('x1', x);
          tick.setAttribute('x2', x);
          tick.setAttribute('y1', height - pad.b);
          tick.setAttribute('y2', height - pad.b + 5);
          tick.setAttribute('stroke', '#d9d0c3');
          svg.appendChild(tick);
        }
        // Measure the actual font, including endpoint anchors and year labels.
        const overlaps = labels.some(function (label, index) {
          if (!index) return false;
          const previous = labels[index - 1].getBBox();
          return previous.x + previous.width + 12 > label.getBBox().x;
        });
        if (!overlaps || count <= 2) break;
        svg.querySelectorAll('[data-axis="x"], .weight-time-tick').forEach(function (node) { node.remove(); });
        count--;
      }
    }
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
    const circles = [];
    function nearestPointer(event) {
      const cursor = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
      let nearest = null;
      let distance = Infinity;
      rawPoints.forEach(function (point) {
        const next = Math.hypot(xOf(point.date) - cursor.x, yOf(point.value) - cursor.y);
        if (next < distance) { distance = next; nearest = point; }
      });
      if (nearest && distance <= 27) onClick(nearest);
    }
    if (onClick) svg.addEventListener('pointermove', nearestPointer);
    rawPoints.forEach(function (item, index) {
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "g");
      circle.setAttribute('class', 'weight-point');
      const hit = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      hit.setAttribute('cx', xOf(item.date));
      hit.setAttribute('cy', yOf(item.value));
      hit.setAttribute('r', 27);
      hit.setAttribute('fill', 'transparent');
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('cx', xOf(item.date));
      dot.setAttribute('cy', yOf(item.value));
      dot.setAttribute('r', 4.5);
      dot.setAttribute('fill', '#1d4e89');
      dot.setAttribute('class', 'weight-dot');
      circle.appendChild(hit);
      circle.appendChild(dot);
      circle.setAttribute("data-series", "raw");
      circle.setAttribute("data-evidence-id", item.id || "");
      circle.setAttribute("tabindex", "0");
      circle.setAttribute('role', 'button');
      circle.setAttribute('aria-label', item.date + ' · ' + fmt(item.value, 1) + (unit || ' кг') + ' · показать наблюдение');
      circle.setAttribute('aria-controls', detailId || 'observation-detail');
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = item.date + " · " + fmt(item.value, 1) + (unit || " кг");
      circle.appendChild(title);
      if (onClick) {
        circle.addEventListener('focus', function () { onClick(item); });
        circle.addEventListener("click", nearestPointer);
        circle.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onClick(item); }
          if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
            event.preventDefault();
            const next = (index + (event.key === 'ArrowRight' ? 1 : -1) + circles.length) % circles.length;
            circles[next].focus();
          }
        });
      }
      svg.appendChild(circle);
      circles.push(circle);
    });
    function resizeChart() {
      width = Math.max(260, host.clientWidth);
      svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
      svg.firstChild.setAttribute('x2', width - pad.r);
      const goalLine = svg.querySelector('[data-series="goal"]');
      if (goalLine) goalLine.setAttribute('x2', width - pad.r);
      const trendPath = svg.querySelector('[data-series="trend"]');
      if (trendPath) trendPath.setAttribute('d', trendPoints.map(function (point, index) {
        return (index ? 'L' : 'M') + xOf(point.date) + ' ' + yOf(point.value);
      }).join(' '));
      circles.forEach(function (circle, index) {
        circle.querySelectorAll('circle').forEach(function (dot) { dot.setAttribute('cx', xOf(rawPoints[index].date)); });
      });
      drawTimeAxis();
    }
    if (host.weightResizeObserver) host.weightResizeObserver.disconnect();
    host.weightResizeObserver = new ResizeObserver(resizeChart);
    host.weightResizeObserver.observe(host);
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
    (info.composition || []).forEach(function (item, index) {
      lines.push('composition ' + (index + 1) + ': ' + (item.algorithm_code || missing) + ' @ ' + (item.algorithm_version || missing) + ' · ' + (item.compatibility_group || missing));
    });
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
