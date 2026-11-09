/* Selected-night card on /sleep. Presentation only: it renders one exact saved
 * session as returned by /api/sleep/night. Missing or unconfirmed values are
 * labelled, never drawn as 0; shares exist only for a complete stage record;
 * colours mark stages, never a health grade. Technical detail stays collapsed. */
(function () {
  const format = window.healthcheckOwnerFormat;
  const STAGES = [
    ["sleep_stage_light_seconds", "light", "Лёгкий"],
    ["sleep_stage_deep_seconds", "deep", "Глубокий"],
    ["sleep_stage_rem_seconds", "rem", "Быстрый (REM)"],
    ["sleep_awake_waso_seconds", "awake", "Бодрствование"]
  ];
  const ENDPOINTS = [["sleep_start_at", "Начало сна"], ["sleep_end_at", "Окончание сна"]];

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function longDate(iso) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("ru-RU", {
      day: "numeric", month: "long", year: "numeric", timeZone: "UTC"
    });
  }

  // "8 ч 35 мин" -> large thin numerals with small units; anything else stays plain.
  function figure(text) {
    const match = /^(?:(\d+) ч )?(\d+) мин$/.exec(text);
    if (!match) return '<span class="night-card-num">' + esc(text) + "</span>";
    let html = "";
    if (match[1] !== undefined) {
      html += '<span class="night-card-num">' + match[1] + '</span><span class="night-card-unit">ч</span> ';
    }
    return html + '<span class="night-card-num">' + match[2] + '</span><span class="night-card-unit">мин</span>';
  }

  // Header: wake-date night, exact source label and, for a value, the duration.
  function head(series, point) {
    let html = '<header class="night-card-head">';
    html += '<h3 class="night-card-title">Ночь на ' + esc(longDate(point.wake_date)) + "</h3>";
    html += '<p class="night-card-source"><span class="swatch sleep-series-' + esc(series.provider) +
      '" aria-hidden="true"></span>' + esc(series.label) + "</p>";
    html += "</header>";
    if (point.state === "value") {
      const text = format.duration(point.value_seconds);
      html += '<div class="night-card-duration"><p class="night-card-label">Длительность сна</p>' +
        '<p class="night-card-figure" aria-label="' + esc(text) + '">' + figure(text) + "</p></div>";
    }
    return html;
  }

  function cellState(cell) {
    if (cell && cell.eligible && isNumber(cell.value) && cell.value >= 0) return "value";
    // The source reported a value the reader withholds as unconfirmed: not "no data".
    if (cell && cell.state === "value") return "unconfirmed";
    return "missing";
  }

  function stateText(state) {
    return state === "unconfirmed" ? "не подтверждено" : "нет данных";
  }

  function stateValue(cell, render) {
    const state = cellState(cell);
    if (state === "value") return render(cell.value);
    return '<span class="night-card-missing" data-night-state="' + state + '">' + stateText(state) + "</span>";
  }

  function windowLine(session) {
    const metrics = session.metrics || {};
    const ends = ENDPOINTS.map(function (item) {
      const cell = metrics[item[0]] || null;
      const clock = format.clock(cell, session, item[0]);
      return { clock: clock, state: clock ? "value" : cell && cell.state === "value" ? "unconfirmed" : "missing" };
    });
    const missing = function (state, plural) {
      const text = state === "unconfirmed" ? (plural ? "не подтверждены" : "не подтверждено") : "нет данных";
      return '<span class="night-card-missing" data-night-state="' + state + '">' + text + "</span>";
    };
    if (!ends[0].clock && !ends[1].clock) {
      const state = ends[0].state === "unconfirmed" || ends[1].state === "unconfirmed" ? "unconfirmed" : "missing";
      return '<p class="night-card-window" data-night-window="missing">' +
        '<span class="night-card-window-label">Начало и окончание сна</span>' + missing(state, true) + "</p>";
    }
    const part = function (end, label) {
      const text = end.clock ? '<time class="night-card-clock">' + esc(end.clock.text) + "</time>"
        : missing(end.state, false);
      return '<span class="visually-hidden">' + label + ": </span>" + text;
    };
    const complete = ends[0].clock && ends[1].clock;
    return '<p class="night-card-window" data-night-window="' + (complete ? "value" : "partial") + '">' +
      part(ends[0], "Начало сна") + '<span class="night-card-arrow" aria-hidden="true">→</span>' +
      '<span class="visually-hidden">, </span>' + part(ends[1], "окончание") + "</p>";
  }

  function shareText(value, total) {
    if (value > 0 && value / total < 0.005) return "<1 %";
    return Math.round(value / total * 100) + " %";
  }

  function stagesBlock(session) {
    const metrics = session.metrics || {};
    const rows = STAGES.map(function (item) {
      const cell = metrics[item[0]] || null;
      return { key: item[1], label: item[2], cell: cell, state: cellState(cell) };
    });
    const known = rows.filter(function (row) { return row.state === "value"; });
    const complete = known.length === rows.length;
    const total = known.reduce(function (sum, row) { return sum + row.cell.value; }, 0);
    let html = '<section class="night-card-stages" aria-labelledby="night-card-stages-title">';
    html += '<h4 id="night-card-stages-title">Стадии сна';
    if (known.length && !complete) html += ' <span class="night-card-flag">неполные</span>';
    html += "</h4>";
    if (!known.length) {
      const anyRetained = rows.some(function (row) { return row.state === "unconfirmed"; });
      return html + '<p class="night-card-stage-empty" data-night-stages="none">' +
        '<span class="night-card-missing">' + (anyRetained ? "не подтверждены" : "нет данных") +
        "</span></p></section>";
    }
    // Proportions only for a complete stage record: a partial one has no honest denominator.
    if (complete && total > 0) {
      html += '<div class="night-stage-bar" data-night-stages="complete" aria-hidden="true">';
      rows.forEach(function (row) {
        if (row.cell.value > 0) {
          html += '<span class="night-stage night-stage-' + row.key + '" style="flex-grow: ' +
            row.cell.value + '"></span>';
        }
      });
      html += "</div>";
    }
    html += '<ul class="night-stage-legend" data-night-stages="' + (complete ? "complete" : "partial") + '">';
    rows.forEach(function (row) {
      html += '<li data-night-stage="' + row.key + '"><span class="night-stage-key night-stage-' + row.key +
        '" aria-hidden="true"></span><span class="night-stage-name">' + row.label + "</span>";
      html += '<span class="night-stage-figures">';
      if (row.state === "value") {
        html += '<span class="night-stage-value">' + esc(format.duration(row.cell.value)) + "</span>";
        if (complete && total > 0) {
          html += '<span class="night-stage-share">' + esc(shareText(row.cell.value, total)) + "</span>";
        }
      } else {
        html += stateValue(row.cell);
      }
      html += "</span></li>";
    });
    return html + "</ul></section>";
  }

  function tiles(series, session) {
    const metrics = session.metrics || {};
    let html = '<dl class="night-card-tiles">';
    html += '<div class="night-card-tile" data-night-tile="time_in_bed"><dt>Время в постели</dt><dd>' +
      stateValue(metrics.sleep_time_in_bed_seconds, function (value) { return esc(format.duration(value)); }) +
      "</dd></div>";
    // Native Garmin score stays a per-session source value; Google has no promised score.
    if (series.provider === "garmin") {
      html += '<div class="night-card-tile" data-night-tile="sleep_score"><dt>Оценка сна Garmin</dt><dd>' +
        stateValue(metrics.sleep_score, function (value) {
          const text = Number.isInteger(value) ? String(value) : value.toFixed(1).replace(".", ",");
          return esc(text) + ' <span class="night-card-scale">из 100</span>';
        }) + '<span class="night-card-tile-note">шкала Garmin, по сессии</span></dd></div>';
    }
    return html + "</dl>";
  }

  function notes(session) {
    const metrics = session.metrics || {};
    const check = ((metrics.sleep_duration_asleep_seconds || {}).evidence || {}).quality_inputs || {};
    if ((check.session_bound_validation || {}).state === "unverified") {
      return '<p class="night-card-note">Границы сессии не проверены; длительность — из сводки источника.</p>';
    }
    return "";
  }

  function technical(session) {
    const metrics = session.metrics || {};
    const rows = [];
    const add = function (label, value) {
      if (value === null || value === undefined || value === "") return;
      rows.push("<div><dt>" + esc(label) + "</dt><dd>" + esc(String(value)) + "</dd></div>");
    };
    ENDPOINTS.forEach(function (item) {
      if (metrics[item[0]] && metrics[item[0]].eligible) {
        add(item[1], format.endpoint(metrics[item[0]], session, item[0]));
      }
    });
    add("Запись", session.record_id);
    add("Статус записи", session.record_status);
    add("Роль", session.role);
    const withheld = Object.entries(metrics).filter(function (entry) {
      return !entry[1].eligible && entry[1].reason;
    }).map(function (entry) { return entry[0] + ": " + entry[1].reason; });
    if (withheld.length) add("Не показаны как значение", withheld.join("; "));
    let html = '<details class="owner-details night-card-tech"><summary>ⓘ Данные сессии</summary>';
    if (rows.length) html += '<dl class="sleep-timeline-session">' + rows.join("") + "</dl>";
    return html + '<pre class="provenance">' + esc(JSON.stringify(session, null, 2)) + "</pre></details>";
  }

  // Session body: clock window, stages, secondary tiles, short qualifiers, collapsed detail.
  function sessionBody(series, session) {
    return windowLine(session) + stagesBlock(session) + tiles(series, session) + notes(session) +
      technical(session);
  }

  window.healthcheckSleepNightCard = Object.freeze({ head: head, session: sessionBody });
})();
