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

  const LEVELS = [["AWAKE", "awake", "Бодрствование"], ["REM", "rem", "REM"],
    ["LIGHT", "light", "Лёгкий"], ["DEEP", "deep", "Глубокий"]];
  const instant = value => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    ? Date.parse(value) : NaN;
  const offsetValue = value => Number.isInteger(value) && Math.abs(value) <= 1439 ? value : null;
  const pad = value => String(value).padStart(2, "0");

  function intervalTable(rows, clock) {
    let html = '<details class="owner-details night-hypno-intervals"><summary>Интервалы стадий</summary>' +
      '<div class="night-hypno-table"><table><caption>Сохранённые интервалы этой ночи</caption><thead><tr>' +
      '<th scope="col">Начало</th><th scope="col">Окончание</th><th scope="col">Стадия</th>' +
      '<th scope="col">Минуты</th></tr></thead><tbody>';
    rows.forEach(row => {
      const timed = Number.isFinite(row.a) && Number.isFinite(row.b) && row.b > row.a;
      const minutes = timed ? (row.b - row.a) / 60000 : null;
      const duration = minutes === null ? "нет данных" : minutes < 1 ? "<1" :
        Number(minutes.toFixed(2)).toLocaleString("ru-RU");
      html += '<tr><td>' + esc(Number.isFinite(row.a) ? clock(row.a, true) : "нет данных") +
        '</td><td>' + esc(Number.isFinite(row.b) ? clock(row.b, true) : "нет данных") +
        '</td><td>' + esc(row.level < 0 ? "Неизвестная стадия" : LEVELS[row.level][2]) +
        (row.draw ? "" : " (не показан на графике)") + '</td><td>' + esc(duration) + '</td></tr>';
    });
    return html + '</tbody></table></div></details>';
  }

  function hypnogram(session) {
    const metrics = session.metrics || {};
    // Each stage metric freezes the same collection. Take it once, never concatenate
    // metrics, sources or sessions. A withheld total can still disclose saved rows.
    const evidence = STAGES.map(item => (metrics[item[0]] || {}).evidence || {});
    const snapshots = evidence.map(item => item.interval_snapshots || []).find(rows =>
      rows.some(row => row.interval_kind === "sleep_stage")) || [];
    const stages = snapshots.filter(row => row.interval_kind === "sleep_stage");
    if (!stages.length) return '<p class="night-card-note" data-hypnogram="totals-only">' +
      'Последовательность стадий не сохранена — показаны только итоги</p>';

    const allEvidence = Object.values(metrics).map(cell => cell.evidence || {});
    const temporals = [];
    allEvidence.forEach(item => {
      const boundary = (item.quality_inputs || {}).summary_boundary || {};
      [boundary.start, boundary.end].forEach(value => { if (value) temporals.push(value); });
      (item.interval_snapshots || []).forEach(row => {
        [row.start_temporal, row.end_temporal].forEach(value => { if (value) temporals.push(value); });
      });
    });
    const record = session.temporal_evidence || {};
    temporals.push({precision: record.precision, measured_at_utc: record.source_timestamp_utc,
      source_utc_offset_minutes: record.source_utc_offset_minutes});
    const pairedOffset = stamp => {
      const offsets = new Set(temporals.filter(value => value.precision === "instant" &&
        instant(value.measured_at_utc) === stamp).map(value => offsetValue(value.source_utc_offset_minutes))
        .filter(value => value !== null));
      return offsets.size === 1 ? [...offsets][0] : null;
    };
    const boundary = (code, side) => {
      const cell = metrics[code] || {};
      if (cell.eligible && Number.isFinite(instant(cell.value))) return instant(cell.value);
      // Garmin's summary bounds remain independently confirmed when phases have gaps.
      const values = new Set(allEvidence.map(item =>
        ((item.quality_inputs || {}).summary_boundary || {})[side])
        .filter(value => value && value.precision === "instant")
        .map(value => instant(value.measured_at_utc)).filter(Number.isFinite));
      return values.size === 1 ? [...values][0] : NaN;
    };
    const start = boundary("sleep_start_at", "start"), end = boundary("sleep_end_at", "end");
    const hasBounds = Number.isFinite(start) && Number.isFinite(end) && end > start;
    const offsets = new Set(temporals.filter(value => value.precision === "instant" &&
      instant(value.measured_at_utc) >= start && instant(value.measured_at_utc) <= end)
      .map(value => offsetValue(value.source_utc_offset_minutes)).filter(value => value !== null));
    // A fixed night offset is usable only when both bounds confirm it and no saved
    // endpoint contradicts it. Never guess the instant of a DST/travel transition.
    const fixedOffset = offsets.size === 1 && pairedOffset(start) !== null &&
      pairedOffset(start) === pairedOffset(end) ? pairedOffset(start) : null;
    const clock = (stamp, full = false) => {
      const offset = pairedOffset(stamp) ?? fixedOffset;
      const local = new Date(stamp + (offset ?? 0) * 60000);
      const time = pad(local.getUTCHours()) + ":" + pad(local.getUTCMinutes());
      const zone = offset === null || offset === 0 ? " UTC" : " UTC" + (offset < 0 ? "−" : "+") +
        pad(Math.floor(Math.abs(offset) / 60)) + ":" + pad(Math.abs(offset) % 60);
      return (full ? local.toISOString().slice(0, 10) + " " : "") + time +
        (full || fixedOffset === null ? zone : "");
    };
    const x = stamp => Number(((stamp - start) / (end - start) * 100).toFixed(6)) + "%";
    const y = level => 10 + level * 20;
    const rows = stages.map(row => {
      const a = instant(row.start_at_utc), b = instant(row.end_at_utc);
      const level = LEVELS.findIndex(item => item[0] === (row.activity_level || row.stage_type));
      const valid = row.interval_state === "value" && row.start_state === "value" &&
        row.end_state === "value" && row.start_precision === "instant" && row.end_precision === "instant" &&
        Number.isFinite(a) && Number.isFinite(b) && a >= start && b <= end && b > a;
      return {a, b, level, valid};
    });
    // Conflicting intervals are never drawn on top of one another as if confirmed.
    rows.forEach(row => {
      row.draw = row.valid && row.level >= 0 && !rows.some(other => other !== row &&
        Number.isFinite(other.a) && Number.isFinite(other.b) && other.a < row.b && other.b > row.a);
    });
    if (!hasBounds) return '<p class="night-card-note" data-hypnogram="unavailable">' +
      'Гипнограмма недоступна: границы ночи не подтверждены.</p>' + intervalTable(rows, clock);
    const drawn = rows.filter(row => row.draw).sort((a, b) => a.a - b.a);
    let svg = '<svg class="night-hypno-plot" width="100%" height="128" ' +
      'aria-label="Гипнограмма: сохранённые интервалы стадий" role="group">' +
      '<defs><pattern id="night-hypno-hatch" width="6" height="6" patternUnits="userSpaceOnUse">' +
      '<path class="night-hypno-hatch" d="M-1 1L1-1M0 6L6 0M5 7L7 5"/></pattern></defs>';
    LEVELS.forEach((item, i) => {
      svg += '<line class="night-hypno-grid" x1="0" x2="100%" y1="' + y(i) + '" y2="' + y(i) + '"/>';
    });
    // Hatch only the complement of known intervals, including unrecognized stages.
    let cursor = start;
    const gap = (a, b) => '<svg class="night-hypno-gap" data-start="' + a + '" data-end="' + b +
      '" x="' + x(a) + '" y="80" width="' + x(start + b - a) + '" height="8" aria-hidden="true">' +
      '<rect width="100%" height="8" fill="url(#night-hypno-hatch)"/></svg>';
    drawn.forEach(row => { if (row.a > cursor) svg += gap(cursor, row.a); cursor = row.b; });
    if (cursor < end) svg += gap(cursor, end);
    drawn.forEach((row, index) => {
      const stage = LEVELS[row.level], previous = drawn[index - 1];
      const minutes = (row.b - row.a) / 60000;
      const duration = minutes < 1 ? "<1" : Number(minutes.toFixed(2)).toLocaleString("ru-RU");
      const label = stage[2] + " · " + clock(row.a) + "–" + clock(row.b) + " · " + duration + " мин";
      svg += '<g class="night-hypno-segment night-hypno-' + stage[1] + '" tabindex="0" role="img" ' +
        'aria-label="' + esc(label) + '" data-start="' + row.a + '" data-end="' + row.b + '">' +
        '<title>' + esc(label) + '</title>';
      if (previous && previous.b === row.a) svg += '<line class="night-hypno-step" x1="' + x(row.a) +
        '" x2="' + x(row.a) + '" y1="' + y(previous.level) + '" y2="' + y(row.level) + '"/>';
      svg += '<line class="night-hypno-line" x1="' + x(row.a) + '" x2="' + x(row.b) +
        '" y1="' + y(row.level) + '" y2="' + y(row.level) + '"/>' +
        '<line class="night-hypno-hit" x1="' + x(row.a) + '" x2="' + x(row.b) +
        '" y1="' + y(row.level) + '" y2="' + y(row.level) + '"/>' +
        '<foreignObject class="night-hypno-tooltip" x="0" y="0" width="100%" height="78" aria-hidden="true">' +
        '<div xmlns="http://www.w3.org/1999/xhtml">' + esc(label) + '</div></foreignObject></g>';
    });
    const tick = (stamp, anchor) => '<text class="night-hypno-tick" x="' + x(stamp) +
      '" y="119" text-anchor="' + anchor + '">' + esc(clock(stamp)) + '</text>';
    svg += tick(start, "start");
    const hour = 3600000, step = end - start > 6 * hour ? 2 * hour : hour;
    const shift = (fixedOffset ?? 0) * 60000;
    for (let stamp = Math.ceil((start + shift) / step) * step - shift; stamp < end; stamp += step) {
      if (stamp - start >= step * 0.6 && end - stamp >= step * 0.6) svg += tick(stamp, "middle");
    }
    svg += tick(end, "end") + '</svg>';
    let html = '<figure class="night-hypno" data-hypnogram="intervals"><figcaption class="night-card-label">' +
      'Гипнограмма</figcaption><div class="night-hypno-chart"><div class="night-hypno-levels" aria-hidden="true">';
    LEVELS.forEach(item => { html += '<span>' + item[2] + '</span>'; });
    html += '</div>' + svg + '</div>';
    if (fixedOffset === null) html += '<p class="night-card-note">Местное время — по сохранённым смещениям; ' +
      'где смещение неизвестно, показано UTC.</p>';
    return html + '</figure>' + intervalTable(rows, clock);
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
    return windowLine(session) + stagesBlock(session) + hypnogram(session) + tiles(series, session) + notes(session) +
      technical(session);
  }

  window.healthcheckSleepNightCard = Object.freeze({ head: head, session: sessionBody });
})();
