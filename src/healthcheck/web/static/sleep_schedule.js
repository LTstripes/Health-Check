/* Source-local schedule from the existing accepted regularity inputs. No
 * timezone inference, session fetching, duration-derived bounds or source merge. */
(function () {
  "use strict";
  function esc(value) {
    return String(value == null ? "" : value).replace(/&/g, "&amp;")
      .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function calendar(value) {
    // Calendar arithmetic only. Never parse a local timestamp in the host zone.
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
    return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / 86400000 : NaN;
  }
  function position(local, wakeDate) {
    const m = /T(\d{2}):(\d{2}):(\d{2})/.exec(local || "");
    return m ? (calendar(local) - calendar(wakeDate) + 1) * 1440 +
      Number(m[1]) * 60 + Number(m[2]) + Number(m[3]) / 60 : NaN;
  }
  function clock(local) { return (local || "").slice(11, 16); }
  function duration(seconds) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds)) return "нет данных";
    const minutes = Math.round(seconds / 60);
    return Math.floor(minutes / 60) + " ч " + minutes % 60 + " мин";
  }
  function zoneLabel(zone) {
    if (!zone) return "часовой пояс неизвестен";
    if (zone.kind === "iana_zone") return zone.zone;
    if (zone.kind !== "explicit_fixed_offset" || typeof zone.minutes !== "number") {
      return "часовой пояс неизвестен";
    }
    const n = Math.abs(zone.minutes);
    return "UTC" + (zone.minutes < 0 ? "−" : "+") +
      String(Math.floor(n / 60)).padStart(2, "0") + ":" + String(n % 60).padStart(2, "0");
  }
  function dateLabel(day) {
    const date = new Date(calendar(day) * 86400000);
    return ["вс", "пн", "вт", "ср", "чт", "пт", "сб"][date.getUTCDay()] +
      " " + day.slice(8, 10) + "." + day.slice(5, 7);
  }
  function rows(data, series) {
    return (data.dates || []).slice().reverse().map(function (day) {
      return { date: day, cells: series.map(function (source) {
        const point = (source.points || []).find(function (p) { return p.wake_date === day; });
        const bound = ((data.schedule_bounds || {})[source.series_id] || []).find(function (b) {
          return b.wake_date === day && point && b.record_id === point.record_id;
        });
        const start = bound ? position(bound.start_local, day) : NaN;
        const end = bound ? position(bound.end_local, day) : NaN;
        const valid = point && point.state === "value" &&
          Number.isFinite(start) && Number.isFinite(end) && end > start;
        let note = "нет данных";
        if (point && point.state === "value") note = "границы не сохранены";
        else if (point && point.state !== "no_records") note = point.note || "нет пригодных границ";
        return { source: source, point: point, bound: valid ? bound : null,
          start: start, end: end, note: note };
      }) };
    });
  }
  function axis(nights) {
    let min = 18 * 60, max = (24 + 14) * 60;
    nights.forEach(function (row) { row.cells.forEach(function (cell) {
      if (cell.bound) { min = Math.min(min, cell.start); max = Math.max(max, cell.end); }
    }); });
    min = Math.floor(min / 120) * 120;
    max = Math.ceil(max / 120) * 120;
    const ticks = [];
    for (let minute = min; minute <= max; minute += 120) ticks.push(minute);
    return { min: min, max: max, ticks: ticks };
  }
  function summaries(data, visible) {
    return ((data.regularity || {}).sources || []).filter(function (source) {
      return visible.some(function (s) {
        return s.provider === source.provider && s.source.source_id === source.source_id;
      });
    }).map(function (source) {
      return (source.groups || []).filter(function (group) {
        return group.start.state === "sufficient" && group.end.state === "sufficient" &&
          group.start.minutes != null && group.end.minutes != null;
      }).map(function (group) {
        const zone = source.groups.length > 1 ? " · " + zoneLabel(group.partition.local_clock_regime) : "";
        return '<p class="sleep-schedule-summary">' + esc(source.label + zone) +
          " · Начало сна: разброс ±" + esc(group.start.text) + " · Окончание: ±" +
          esc(group.end.text) + " · " + esc(group.nights) + " из " + esc(data.days) + " ночей</p>";
      }).join("");
    }).join("");
  }
  function table(nights) {
    return '<details class="owner-details"><summary>Таблица</summary>' +
      '<div class="table-scroll" role="region" tabindex="0" aria-label="Расписание сна по источникам">' +
      '<table><thead><tr><th scope="col">Дата</th><th scope="col">Источник</th>' +
      '<th scope="col">Начало</th><th scope="col">Окончание</th>' +
      '<th scope="col">Длительность сна</th><th scope="col">Часовой пояс</th></tr></thead><tbody>' +
      nights.map(function (row) {
        if (!row.cells.length) return '<tr><th scope="row">' + esc(row.date) +
          '</th><td colspan="5">нет данных</td></tr>';
        return row.cells.map(function (cell) {
          const b = cell.bound;
          return '<tr><th scope="row">' + esc(row.date) + '</th><td>' + esc(cell.source.label) +
            '</td><td>' + esc(b ? b.start_local.slice(0, 16).replace("T", " ") : cell.note) +
            '</td><td>' + esc(b ? b.end_local.slice(0, 16).replace("T", " ") : "—") +
            '</td><td>' + esc(duration(cell.point && cell.point.value_seconds)) +
            '</td><td>' + esc(b ? zoneLabel(b.zone) : "часовой пояс неизвестен") + '</td></tr>';
        }).join("");
      }).join("") + '</tbody></table></div></details>';
  }
  function render(data, hidden) {
    if (data.read_limit_exceeded || !data.dates) return '<p class="muted">Расписание недоступно для этого периода.</p>';
    const all = (data.display_series || []).slice().sort(function (a, b) {
      return (a.provider === "garmin" ? 0 : 1) - (b.provider === "garmin" ? 0 : 1);
    });
    const visible = all.filter(function (s) { return !(hidden || {})[s.series_id]; });
    const nights = rows(data, visible), scale = axis(nights);
    const percent = function (n) { return 100 * (n - scale.min) / (scale.max - scale.min); };
    const grid = scale.ticks.map(function (n) {
      return '<span class="sleep-schedule-grid" style="left:' + percent(n) + '%"></span>';
    }).join("");
    let html = summaries(data, visible) + '<div class="' +
      (data.days === 30 ? "sleep-schedule-compact" : "sleep-schedule-rows") + '">' +
      '<div class="sleep-schedule-axis"><span></span><div class="sleep-schedule-clock">' +
      scale.ticks.map(function (n) {
        const hour = ((n / 60) % 24 + 24) % 24;
        return '<span class="sleep-schedule-tick" style="left:' + percent(n) + '%">' +
          String(hour).padStart(2, "0") + ':00</span>';
      }).join("") + '</div></div>';
    const previousZone = {};
    nights.forEach(function (row) {
      row.cells.forEach(function (cell) {
        if (!cell.bound) return;
        const id = cell.source.series_id, zone = zoneLabel(cell.bound.zone);
        if (previousZone[id] && previousZone[id] !== zone) {
          html += '<div class="sleep-schedule-divider">' + esc(cell.source.label) +
            ' · Часовой пояс: ' + esc(previousZone[id]) + ' → ' + esc(zone) + '</div>';
        }
        previousZone[id] = zone;
      });
      html += '<div class="sleep-schedule-row" data-schedule-date="' + esc(row.date) + '">' +
        '<span class="sleep-schedule-date">' + esc(dateLabel(row.date)) +
        '</span><div class="sleep-schedule-track" style="min-height:' +
        Math.max(14, row.cells.length * 7) + 'px">' + grid;
      const any = row.cells.some(function (c) { return c.bound; });
      if (!row.cells.length || (!any && row.cells.every(function (c) { return c.note === "нет данных"; }))) {
        html += '<span class="sleep-schedule-empty">' +
          (all.length && !visible.length ? 'Источники скрыты' : 'нет данных') + '</span>';
      } else row.cells.forEach(function (cell, lane) {
        const top = lane * 7;
        if (!cell.bound) {
          html += '<span class="sleep-schedule-note" style="top:' + top + 'px" title="' +
            esc(cell.source.label + ' · ' + cell.note) + '">' +
            esc(cell.source.label + ' · ' + cell.note) + '</span>';
          return;
        }
        const label = cell.source.label + ' · ' + clock(cell.bound.start_local) + ' → ' +
          clock(cell.bound.end_local) + ' · ' + duration(cell.point.value_seconds);
        html += '<button type="button" class="sleep-schedule-bar" data-schedule-bar="' +
          esc(cell.source.series_id) + '" style="top:' + top + 'px;left:' + percent(cell.start) +
          '%;width:' + (percent(cell.end) - percent(cell.start)) + '%;background:var(--series-' +
          (cell.source.provider === 'garmin' ? '1' : '4') + ')" title="' + esc(label) +
          '" aria-label="' + esc(row.date + ' · ' + label + ' · ' + zoneLabel(cell.bound.zone)) + '"></button>';
      });
      html += '</div></div>';
    });
    return html + '</div><p class="muted sleep-schedule-detail" data-schedule-detail role="status" aria-live="polite">' +
      'Наведи на полосу или выбери её клавишей Tab.</p>' + table(rows(data, all));
  }
  window.healthcheckSleepSchedule = { render: render, rows: rows, axis: axis, position: position };
  if (typeof document === "undefined") return;
  const host = document.getElementById("sleep-schedule");
  const node = document.getElementById("sleep-timeline-data");
  if (!host || !node) return;
  let data;
  try { data = JSON.parse(node.textContent); } catch (_error) { return; }
  function draw() {
    const hidden = {};
    document.querySelectorAll("[data-sleep-series-toggle]").forEach(function (toggle) {
      hidden[toggle.getAttribute("data-sleep-series-toggle")] = !toggle.checked;
    });
    host.innerHTML = render(data, hidden);
  }
  document.querySelectorAll("[data-sleep-series-toggle]").forEach(function (toggle) {
    toggle.addEventListener("change", draw);
  });
  function describe(event) {
    const bar = event.target.closest("[data-schedule-bar]");
    const detail = host.querySelector("[data-schedule-detail]");
    if (bar && detail) detail.textContent = bar.getAttribute("title");
  }
  host.addEventListener("focusin", describe);
  host.addEventListener("pointerover", describe);
  draw();
})();
