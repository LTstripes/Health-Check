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
    return window.healthcheckOwnerFormat.duration(seconds);
  }
  function zoneLabel(zone, showMoscow = false) {
    if (!zone) return "часовой пояс неизвестен";
    if (zone.kind === "iana_zone") return zone.zone === "Europe/Moscow" && !showMoscow ? "" : zone.zone;
    if (zone.kind !== "explicit_fixed_offset" || typeof zone.minutes !== "number") {
      return "часовой пояс неизвестен";
    }
    if (zone.minutes === 180 && !showMoscow) return "";
    const n = Math.abs(zone.minutes);
    return "UTC" + (zone.minutes < 0 ? "−" : "+") +
      String(Math.floor(n / 60)).padStart(2, "0") + ":" + String(n % 60).padStart(2, "0");
  }
  function dateLabel(day) {
    const date = new Date(calendar(day) * 86400000);
    return ["вс", "пн", "вт", "ср", "чт", "пт", "сб"][date.getUTCDay()] +
      " " + window.healthcheckOwnerShortDate(day);
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
        const analysis = ((data.regularity || {}).sources || []).find(function (s) {
          return s.provider === source.provider && s.source_id === source.source.source_id;
        });
        const classified = analysis && analysis.jetlag && (analysis.jetlag.night_types || {})[day];
        let note = "нет данных";
        if (point && point.state === "value") note = "границы не сохранены";
        else if (point && point.state !== "no_records") note = point.note || "нет пригодных границ";
        return { source: source, point: point, bound: valid ? bound : null,
          start: start, end: end, note: note,
          day_type: classified ? classified.day_type : (data.day_types || {})[day] };
      }) };
    });
  }
  function axis(nights) {
    let min = 21 * 60, max = (24 + 11) * 60;
    nights.forEach(function (row) { row.cells.forEach(function (cell) {
      if (cell.bound) { min = Math.min(min, cell.start); max = Math.max(max, cell.end); }
    }); });
    if (min < 1260) min = Math.floor(min / 120) * 120;
    if (max > 2100) max = Math.ceil(max / 120) * 120;
    const ticks = [];
    for (let minute = min; minute <= max; minute += 120) ticks.push(minute);
    if (ticks[ticks.length - 1] !== max) ticks.push(max);
    return { min: min, max: max, ticks: ticks };
  }
  function summaries(data, visible, threshold) {
    if (!(data.display_series || []).length) {
      return '<p class="muted">' + esc((data.regularity || {}).empty_text ||
        'Недостаточно ночей для сравнения') + '</p>';
    }
    const body = ((data.regularity || {}).sources || []).filter(function (source) {
      return visible.some(function (s) {
        return s.provider === source.provider && s.source.source_id === source.source_id;
      });
    }).map(function (source) {
      const groups = (source.groups || []).slice();
      const jetlag = (source.jetlag || {}).groups || [];
      jetlag.forEach(function (group) {
        if (!groups.some(g => JSON.stringify(g.partition) === JSON.stringify(group.partition))) {
          groups.push({partition: group.partition});
        }
      });
      return (groups.length ? groups : [{}]).map(function (group, index) {
        const jet = jetlag.find(g => JSON.stringify(g.partition) === JSON.stringify(group.partition));
        const zone = groups.length > 1 && group.partition ? " · " + zoneLabel(group.partition.local_clock_regime, true) : "";
        const low = threshold && group.nights != null && group.nights * threshold.denominator < data.days * threshold.numerator;
        const provider = source.provider === "garmin" ? "garmin" : source.provider === "google" ? "google" : "other";
        const coverage = group.nights != null ? '<span class="owner-meta-coverage" data-coverage-qualifier="' +
          esc(group.nights) + '/' + esc(data.days) + '">' + esc(group.nights) + ' из ' +
          esc(data.days) + ' ' + esc(window.healthcheckOwnerFormat.plural(data.days, 'ночь', 'ночи', 'ночей')) + '</span>' : 'Неизвестно';
        function spread(value) {
          return esc(value ? (value.state === 'sufficient' ? '± ' : '') + value.text :
            (source.state === 'unavailable' ? 'Не удалось оценить этот период.' : 'Недостаточно ночей'));
        }
        let middle = jet ? jet.text : 'Сравнение недоступно';
        if (jet && jet.state === 'sufficient' && Number.isFinite(jet.signed_minutes)) {
          const time = function (minutes) {
            const value = Math.round(minutes) % 1440;
            return String(Math.floor(value / 60)).padStart(2, '0') + ':' + String(value % 60).padStart(2, '0');
          };
          middle = time(jet.groups.work.mean_clock_minutes) + ' → ' + time(jet.groups.free.mean_clock_minutes) +
            ' · сдвиг ' + window.healthcheckOwnerFormat.number(jet.signed_minutes, 0, true) + ' мин';
        }
        return '<tr data-regularity-source="' + esc(source.provider) + '" data-regularity-group' +
          (low ? ' class="owner-value-low"' : '') + '><th scope="row"><span class="owner-meta-source"><i class="owner-meta-dot owner-meta-dot--' + provider +
          '" aria-hidden="true"></i>' + esc(source.label + zone) + (groups.length > 1 ? ' · группа ' + (index + 1) : '') +
          '</span></th><td>' + spread(group.start) + '</td><td>' + spread(group.end) + '</td><td data-sleep-jetlag="' +
          esc(source.provider + ':' + source.source_id) + '">' + esc(middle) + '</td><td>' + coverage + '</td></tr>';
      }).join('');
    }).join('');
    return '<div class="table-scroll" role="region" tabindex="0" aria-label="Регулярность сна по источникам"><table class="sleep-schedule-summary"><thead><tr>' +
      '<th scope="col">Источник</th><th scope="col">Разброс начала</th><th scope="col">Разброс окончания</th>' +
      '<th scope="col">Середина сна: рабочие → свободные · сдвиг</th><th scope="col">Ночей</th></tr></thead><tbody>' + body + '</tbody></table></div>';
  }
  function jetlagSummary(source) {
    const result = source.jetlag;
    if (!result) return '<p class="muted">' + esc(source.label) + ' · Сравнение недоступно.</p>';
    return '<details class="owner-details sleep-jetlag-method"><summary>Как считается разброс и сдвиг · ' + esc(source.label) + '</summary>' +
      '<p>Разброс — стандартное отклонение местного времени начала и окончания подходящей основной сессии. ' +
      'Пригодная длительность сама по себе не подтверждает границы; полнота сбора неизвестна.</p>' +
      (source.groups || []).map(function (group, index) {
        return '<p>Группа ' + (index + 1) + ': ' + esc(group.nights) + ' ночей; часовой пояс ' +
          esc(zoneLabel(group.partition.local_clock_regime, true)) + '.</p>';
      }).join('') +
      (result.groups || []).map(group => '<p>' + esc(group.text) + '</p>').join('') +
      '<p>Середина ночи = начало UTC + (окончание UTC − начало UTC) / 2, затем местное время источника. ' +
      'Круговое среднее: θ = 2πt/1440, μ = (atan2(среднее sin θ, среднее cos θ) × 1440/(2π)) mod 1440 минут. ' +
      'Некорректированный сдвиг = (μ свободных − μ рабочих + 720) mod 1440 − 720 минут; знак: свободные минус рабочие. ' +
      'Ночь относится к дате пробуждения. Минимум 2 подходящие ночи в каждой группе; ' +
      'при неопределённом круговом среднем результат недоступен. Источники и несовместимые методы считаются отдельно.</p>' +
      '<p>Исключены: поездки / смена часового пояса — ' + esc(result.travel_nights) +
      ' (ночь смены и следующая ночь); неизвестный тип дня — ' + esc(result.unknown_nights) +
      '; дневной сон, неоднозначные ночи и другие непригодные границы — ' + esc(result.other_excluded_nights) + '.</p>' +
      '<p>Смена зоны определяется по сохранённым ночам источника. ' +
      (result.travel_history === 'bounded_30_days' ?
        'Для начала периода проверены предшествующие 30 дней; более ранняя история неизвестна. ' :
        'История до выбранного периода недоступна; поездки на его границе могут быть неизвестны. ') +
      'Смена смещения при DST в одном IANA-поясе не считается поездкой. Поправки на недосып и сменный график нет; ' +
      'не диагноз и не объяснение самочувствия.</p>' +
      (result.exclusions || []).map(function (item) {
        return '<p class="muted">' + esc(item.reason) + ': ' + esc(item.count) + '</p>';
      }).join('') + '</details>';
  }
  function table(nights) {
    return '<details class="owner-details"><summary>Таблица</summary>' +
      '<div class="table-scroll" role="region" tabindex="0" aria-label="Расписание сна по источникам">' +
      '<table><thead><tr><th scope="col">Дата</th><th scope="col">Источник</th>' +
      '<th scope="col">Начало</th><th scope="col">Окончание</th>' +
      '<th scope="col">Длительность сна</th><th scope="col">Часовой пояс</th></tr></thead><tbody>' +
      nights.map(function (row) {
        if (!row.cells.length) return '<tr><th scope="row">' + esc(dateLabel(row.date)) +
          '</th><td colspan="5">нет данных</td></tr>';
        return row.cells.map(function (cell) {
          const b = cell.bound;
          return '<tr><th scope="row">' + esc(dateLabel(row.date)) + '</th><td>' + esc(cell.source.label) +
            '</td><td>' + esc(b ? window.healthcheckOwnerShortDate(b.start_local.slice(0, 10)) + ' ' + clock(b.start_local) : cell.note) +
            '</td><td>' + esc(b ? window.healthcheckOwnerShortDate(b.end_local.slice(0, 10)) + ' ' + clock(b.end_local) : "—") +
            '</td><td>' + esc(duration(cell.point && cell.point.value_seconds)) +
            '</td><td>' + esc(b ? zoneLabel(b.zone, true) : "часовой пояс неизвестен") + '</td></tr>';
        }).join("");
      }).join("") + '</tbody></table></div></details>';
  }
  function render(data, hidden, threshold, expanded = false) {
    if (!data || data.read_limit_exceeded || !Array.isArray(data.dates)) return '<p class="muted">Расписание недоступно для этого периода.</p>';
    const all = (data.display_series || []).slice().sort(function (a, b) {
      return (a.provider === "garmin" ? 0 : 1) - (b.provider === "garmin" ? 0 : 1);
    });
    const visible = all.filter(s => !(hidden || {})[s.series_id]);
    const nights = rows(data, visible), shown = expanded ? nights : nights.slice(0, 14), scale = axis(nights);
    const percent = n => 100 * (n - scale.min) / (scale.max - scale.min);
    const grid = scale.ticks.map(n => '<span class="sleep-schedule-grid" style="left:' + percent(n) + '%"></span>').join('');
    let html = summaries(data, visible, threshold) + '<div class="sleep-schedule-rows owner-chart-frame">' +
      '<div class="sleep-schedule-axis"><span></span><div class="sleep-schedule-clock">' +
      scale.ticks.map(function (n) {
        const hour = ((n / 60) % 24 + 24) % 24;
        return '<span class="sleep-schedule-tick" style="left:' + percent(n) + '%">' + String(hour).padStart(2, '0') + ':00</span>';
      }).join('') + '</div></div>';
    const previousZone = {};
    shown.forEach(function (row) {
      row.cells.forEach(function (cell) {
        if (!cell.bound) return;
        const id = cell.source.series_id, zone = zoneLabel(cell.bound.zone, true);
        if (previousZone[id] && previousZone[id] !== zone) {
          html += '<div class="sleep-schedule-divider">' + esc(cell.source.label) + ' · Часовой пояс: ' + esc(previousZone[id]) + ' → ' + esc(zone) + '</div>';
        }
        previousZone[id] = zone;
      });
      const free = row.cells.some(c => c.day_type === 'free');
      html += '<div class="sleep-schedule-row' + (free ? ' sleep-schedule-row-free' : '') + '" data-schedule-date="' + esc(row.date) + '">' +
        '<button type="button" class="sleep-schedule-date" data-schedule-select aria-label="Выбрать ночь на ' + esc(window.healthcheckOwnerShortDate(row.date)) +
        '">' + esc(dateLabel(row.date)) + (free ? '<span class="sleep-schedule-free" title="Свободный день">св</span>' : '') +
        '</button><div class="sleep-schedule-track" style="min-height:' + Math.max(20, row.cells.length * 9 + 2) + 'px">' + grid;
      if (!row.cells.length || row.cells.every(c => !c.point || c.point.state === 'no_records')) {
        html += '<span class="sleep-schedule-empty">' + (all.length && !visible.length ? 'Источники скрыты' : 'нет данных') + '</span>';
      } else row.cells.forEach(function (cell, lane) {
        const top = lane * 9 + 2;
        const label = cell.source.label + ' · ' + (cell.bound ? clock(cell.bound.start_local) + ' → ' + clock(cell.bound.end_local) +
          ' · ' + duration(cell.point.value_seconds) : cell.note);
        // The hatch means a saved value without confirmed bounds, never zero or an inferred interval.
        if (cell.bound || (cell.point && cell.point.state === 'value')) {
          html += '<span class="sleep-schedule-bar' + (!cell.bound ? ' sleep-schedule-unbounded owner-chart-hatch' : '') +
            '" data-schedule-bar="' + esc(cell.source.series_id) + '" style="top:' + top + 'px;left:' +
            (cell.bound ? percent(cell.start) : 0) + '%;width:' + (cell.bound ? percent(cell.end) - percent(cell.start) : 100) + '%;' +
            (cell.bound ? 'background:var(--series-' + (cell.source.provider === 'garmin' ? '1' : '4') + ')' : '') +
            '" role="img" title="' + esc(label) + '" aria-label="' + esc(window.healthcheckOwnerShortDate(row.date) + ' · ' + label +
            (cell.bound && zoneLabel(cell.bound.zone) ? ' · ' + zoneLabel(cell.bound.zone) : '')) + '"></span>';
        } else if (cell.point && cell.point.state !== 'no_records') {
          html += '<span class="sleep-schedule-unavailable" style="top:' + top + 'px" title="' + esc(label) + '">?</span>';
        }
        const marker = ((((data.context_events || {}).markers || {})[cell.source.series_id]) || [])
          .find(item => item.wake_date === row.date && cell.point && item.record_id === cell.point.record_id);
        if (marker) html += '<span class="sleep-context-marker sleep-schedule-event" data-schedule-bar="' +
          esc(cell.source.series_id) + '" style="top:' + top + 'px;left:' +
          (cell.bound ? Math.min(97, percent(cell.end)) : 97) + '%" title="' + esc(marker.text) + '" aria-label="' + esc(marker.text) + '">●</span>';
      });
      html += '</div></div>';
    });
    html += '</div><div class="owner-chart-legend sleep-schedule-legend">' +
      '<span><i class="swatch sleep-series-garmin"></i>Garmin</span><span><i class="swatch sleep-series-google"></i>Google</span>' +
      '<span><i class="owner-chart-hatch"></i>длительность есть, границы не сохранены</span>' +
      '<span><i class="sleep-schedule-free-key"></i>св — свободный день</span><span>● комментарий накануне</span>' +
      '<span>? нет пригодных границ</span></div>';
    if (nights.length > 14) html += '<div class="sleep-schedule-expand">Показаны ' + shown.length + ' из ' + nights.length +
      ' ночей · <button type="button" data-schedule-expand aria-expanded="' + expanded + '">' +
      (expanded ? '14 последних' : 'все ' + nights.length) + '</button></div>';
    return html + '<p class="muted sleep-schedule-detail owner-chart-selection" data-schedule-detail role="status" aria-live="polite">' +
      'Выбери строку, чтобы открыть ночь; стрелки ↑ ↓ — соседние строки.</p>' +
      '<details class="owner-details"><summary>ⓘ Как читать расписание</summary><p>Garmin — верхняя полоса, Google — нижняя. ' +
      'Источники переключаются над графиком длительности. Штриховка не задаёт начало или конец сна; ' +
      'нет данных — это не ноль.</p>' + visible.map(function (source) {
        return jetlagSummary(((data.regularity || {}).sources || []).find(s => s.provider === source.provider && s.source_id === source.source.source_id) || source);
      }).join('') + '</details>' + table(rows(data, all));
  }
  window.healthcheckSleepSchedule = { render: render, rows: rows, axis: axis, position: position };
  if (typeof document === "undefined") return;
  const host = document.getElementById("sleep-schedule");
  const node = document.getElementById("sleep-timeline-data");
  if (!host || !node) return;
  function failed() {
    host.innerHTML = '<p class="muted">Не удалось показать расписание. <a href="#sleep-duration-table">Таблица длительности →</a></p>';
  }
  let data;
  try {
    data = JSON.parse(node.textContent);
    if (!data || !Array.isArray(data.dates) || !Array.isArray(data.display_series)) throw new Error('schedule_packet');
  } catch (_error) { failed(); return; }
  let expanded = false;
  const selection = window.healthcheckSleepSelection;
  function markSelection() {
    const current = selection && selection.current;
    host.querySelectorAll('[data-schedule-date]').forEach(function (row) {
      const selected = Boolean(current && row.getAttribute('data-schedule-date') === current.date);
      row.classList.toggle('is-selected', selected);
      row.querySelector('[data-schedule-select]').setAttribute('aria-pressed', String(selected));
    });
  }
  function draw() {
    const hidden = {};
    document.querySelectorAll('[data-sleep-series-toggle]').forEach(function (toggle) {
      hidden[toggle.getAttribute('data-sleep-series-toggle')] = !toggle.checked;
    });
    const policy = document.getElementById('sleep-coverage-threshold');
    const threshold = policy ? { numerator: Number(policy.dataset.numerator), denominator: Number(policy.dataset.denominator) } : null;
    try { host.innerHTML = render(data, hidden, threshold, expanded); markSelection(); }
    catch (_error) { failed(); }
  }
  document.querySelectorAll('[data-sleep-series-toggle]').forEach(toggle => toggle.addEventListener('change', draw));
  function describe(event) {
    const row = event.target.closest('[data-schedule-date]');
    const bar = event.target.closest('[data-schedule-bar]');
    const detail = host.querySelector('[data-schedule-detail]');
    if (detail && row) detail.textContent = bar ? bar.getAttribute('title') :
      Array.from(row.querySelectorAll('[data-schedule-bar], .sleep-schedule-unavailable')).map(item => item.getAttribute('title')).join(' · ') || 'нет данных';
  }
  host.addEventListener('focusin', describe);
  host.addEventListener('pointerover', describe);
  host.addEventListener('click', function (event) {
    if (event.target.closest('[data-schedule-expand]')) {
      expanded = !expanded;
      draw();
      host.querySelector('[data-schedule-expand]').focus({preventScroll: true});
      return;
    }
    const row = event.target.closest('[data-schedule-date]');
    if (!row || !selection) return;
    const bar = event.target.closest('[data-schedule-bar]');
    selection.select(row.getAttribute('data-schedule-date'), bar && bar.getAttribute('data-schedule-bar'));
  });
  host.addEventListener('keydown', function (event) {
    const button = event.target.closest('[data-schedule-select]');
    if (!button || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const buttons = Array.from(host.querySelectorAll('[data-schedule-select]'));
    const index = buttons.indexOf(button) + (event.key === 'ArrowDown' ? 1 : -1);
    if (buttons[index]) { buttons[index].focus({preventScroll: true}); buttons[index].click(); }
  });
  if (selection) selection.onChange = markSelection;
  draw();
})();
