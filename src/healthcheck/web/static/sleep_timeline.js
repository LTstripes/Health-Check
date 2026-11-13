/* Owner Sleep B2 timeline. Presentation only: no pairing, averaging, gap fill
 * or score invention. Each exact source keeps its own labelled series; legend
 * toggles hide a chart series only and never edit the table or the packet. */
(function () {
  const dataNode = document.getElementById("sleep-timeline-data");
  const host = document.getElementById("sleep-timeline-chart");
  if (!dataNode || !host) return;
  let data = null;
  try {
    data = JSON.parse(dataNode.textContent);
  } catch (_error) {
    return;
  }
  if (!data || !Array.isArray(data.display_series) || !data.display_series.length) return;
  const detail = document.getElementById("sleep-timeline-detail");
  const nightCard = window.healthcheckSleepNightCard;
  if (!nightCard) return;
  const seriesColors = { garmin: "var(--series-1)", google: "var(--series-4)" };
  const unresolvedColor = "var(--series-3)";
  const lineColor = "var(--line-strong)";
  let svg = null;
  const hidden = {};
  let focusables = [];
  let current = null;

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

  function fmtNumber(value) {
    if (!isNumber(value)) return "недоступно";
    return window.healthcheckOwnerFormat.number(value);
  }

  const durationText = window.healthcheckOwnerFormat.duration;

  function readableDate(iso) {
    return window.healthcheckOwnerShortDate(iso);
  }

  function plotted(point) {
    return point.state === "value" && isNumber(point.value_hours);
  }

  function contextMarker(series, point) {
    return ((((data.context_events || {}).markers || {})[series.series_id]) || []).find(function (m) {
      return m.wake_date === point.wake_date && m.record_id === point.record_id;
    });
  }

  function markerPoints(series) {
    return series.points.filter(function (point) {
      return plotted(point) || point.state === "ambiguous";
    });
  }

  function niceStep(high) {
    const raw = high / 3;
    const power = Math.pow(10, Math.floor(Math.log10(raw)));
    return [1, 2, 2.5, 5, 10].map(n => n * power).find(n => n >= raw);
  }

  function seriesFor(element) {
    const id = element.getAttribute("data-sleep-series-id");
    return data.display_series.find(function (item) { return item.series_id === id; }) || null;
  }

  // Per-night session packets are not embedded in the page: fetch one exact
  // night (narrowed to the series source) on demand and keep it for the visit.
  const nightCache = new Map();

  function nightKey(series, point) {
    return series.provider + "|" + series.source.source_id + "|" + point.wake_date;
  }

  function loadNight(series, point) {
    const key = nightKey(series, point);
    const cached = nightCache.get(key);
    if (cached) return cached.promise;
    const params = new URLSearchParams({
      provider: series.provider,
      wake_date: point.wake_date,
      source_id: series.source.source_id
    });
    const entry = { value: undefined };
    entry.promise = fetch((data.night_endpoint || "/api/sleep/night") + "?" + params.toString(), {
      headers: { Accept: "application/json" },
      credentials: "same-origin"
    }).then(function (response) {
      if (!response.ok) throw new Error("night_" + response.status);
      return response.json();
    }).then(function (night) {
      entry.value = night;
      return night;
    }, function (error) {
      // A failed read is not cached: the next selection retries it.
      nightCache.delete(key);
      throw error;
    });
    nightCache.set(key, entry);
    return entry.promise;
  }

  function cachedNight(series, point) {
    const cached = nightCache.get(nightKey(series, point));
    return cached ? cached.value : undefined;
  }

  function sessionFor(series, point, day) {
    if (!day || !Array.isArray(day.sources)) return null;
    let sessions = [];
    const source = day.sources.find(function (item) {
      return item.source && item.source.source_id === series.source.source_id;
    });
    if (source) {
      sessions = source.sessions || [];
    } else {
      day.sources.forEach(function (item) { sessions = sessions.concat(item.sessions || []); });
    }
    return sessions.find(function (item) { return item.record_id === point.record_id; }) || null;
  }

  function pointEvidence(point) {
    const rows = [];
    const add = function (label, value) {
      if (value === null || value === undefined || value === "") return;
      rows.push("<div><dt>" + esc(label) + "</dt><dd>" + esc(String(value)) + "</dd></div>");
    };
    if (point.state !== "value") add("Состояние точки", point.state);
    add("Причина", point.reason);
    if (point.state === "ambiguous") add("Кандидатов", point.candidate_count);
    if (Array.isArray(point.candidate_record_ids) && point.candidate_record_ids.length) {
      add("Кандидаты", point.candidate_record_ids.join(", "));
    }
    if (Array.isArray(point.exclusions) && point.exclusions.length) {
      add("Исключённые записи", point.exclusions.map(function (item) {
        return (item.record_id || "без ID") + ": " + item.reason;
      }).join("; "));
    }
    if (!rows.length) return "";
    return '<h4>Основание точки</h4><dl class="sleep-timeline-session">' + rows.join("") + "</dl>";
  }

  function visibleSeries() {
    return data.display_series.filter(item => !hidden[item.series_id]);
  }

  function pointAt(series, date) {
    return series.points.find(item => item.wake_date === date);
  }

  function navigation(series) {
    let html = '<nav class="night-card-navigation" aria-label="Выбор ночи">' +
      '<button type="button" data-night-step="-1"' + (markerPoints(series).length ? "" : " disabled") + '>← предыдущая</button>' +
      '<button type="button" data-night-step="1"' + (markerPoints(series).length ? "" : " disabled") + '>следующая →</button>' +
      '<span class="night-card-sources" role="group" aria-label="Источник ночи">';
    visibleSeries().forEach(item => {
      html += '<button type="button" data-night-source="' + esc(item.series_id) +
        '" aria-pressed="' + (item === series) + '">' + esc(item.label) + '</button>';
    });
    return html + '</span></nav>';
  }

  function moveNight(step, focusGraph) {
    if (!current) return;
    const series = current.series;
    const points = markerPoints(series);
    if (!points.length) return;
    const dateNow = current.point.wake_date;
    const next = step > 0 ? points.find(item => item.wake_date > dateNow) || points[0] :
      points.slice().reverse().find(item => item.wake_date < dateNow) || points[points.length - 1];
    const date = next.wake_date;
    showPoint(series, pointAt(series, date));
    if (focusGraph) {
      const node = focusables.find(item => item.getAttribute("data-sleep-series-id") === series.series_id &&
        item.getAttribute("data-wake-date") === date);
      if (node) node.focus({preventScroll: true});
    }
  }

  function syncSelection() {
    focusables.forEach(node => node.setAttribute("aria-pressed", String(Boolean(current &&
      node.getAttribute("data-sleep-series-id") === current.series.series_id &&
      node.getAttribute("data-wake-date") === current.point.wake_date))));
  }

  function selectedEvidence(point) {
    return pointEvidence(point) + '<pre class="provenance">' + esc(JSON.stringify(point, null, 2)) + '</pre>';
  }

  function showPoint(series, point) {
    if (!detail) return;
    current = { series: series, point: point };
    const pending = point.state === "value" && cachedNight(series, point) === undefined
      ? loadNight(series, point) : null;
    let html = '<article class="night-card" data-night-card="' + esc(point.state) + '">' +
      navigation(series) + nightCard.head(series, point);
    const eventMarker = contextMarker(series, point);
    if (eventMarker) html += '<p class="sleep-context-note">' + esc(eventMarker.text) + '</p>';
    if (point.state === "value") {
      if (point.note) html += '<p class="uncertainty-note">' + esc(point.note) + "</p>";
      if (point.role_uncertain) {
        html += '<p class="uncertainty-note">Роль основного сна не подтверждена; запись показана отдельно.</p>';
      }
      html += '<div class="night-card-body" data-sleep-session-slot>' + sessionSlot(series, point) + "</div>";
    } else if (point.state === "ambiguous") {
      html += '<p class="uncertainty-note">Несколько записей за дату; значение не выбрано. ' +
        'Значения не объединяются и не усредняются.</p>';
    } else {
      const dateText = new Date(point.wake_date + "T00:00:00Z").toLocaleDateString("ru-RU", {
        day: "numeric", month: "long", timeZone: "UTC"
      });
      html += '<p data-night-empty>За ночь на ' + esc(dateText) + ' у ' + esc(series.label) +
        (point.state === "no_records" ? ' нет записи. Это не „0 часов“.' :
          ' нет пригодного значения. Это не „0 часов“. ' + esc(point.note || "")) + '</p>';
      const latest = series.points.filter(item => item.state === "value").slice(-1)[0];
      if (latest) html += '<button type="button" class="button-link" data-night-latest="' + esc(latest.wake_date) +
        '">Показать ' + esc(new Date(latest.wake_date + "T00:00:00Z").toLocaleDateString("ru-RU", {
          day: "numeric", month: "long", timeZone: "UTC"
        })) + '</button>';
      else html += '<p><a href="/imports#data-status">Проверить источники →</a></p>';
    }
    if (point.state !== "value") html += nightCard.disclosures(null, "", selectedEvidence(point));
    detail.innerHTML = html + '</article>';
    syncSelection();
    if (pending) pending.then(fillSlot, fillSlot);

    function fillSlot() {
      // The Owner may have moved on: only the still-selected point is updated.
      if (!current || current.series !== series || current.point !== point) return;
      const slot = detail.querySelector("[data-sleep-session-slot]");
      if (slot) slot.innerHTML = sessionSlot(series, point);
    }
  }

  function sessionSlot(series, point) {
    const evidence = selectedEvidence(point);
    const fallback = nightCard.disclosures(null, "", evidence);
    const key = nightKey(series, point);
    const night = cachedNight(series, point);
    if (night === undefined) {
      return (nightCache.has(key)
        ? '<p class="muted" data-sleep-session-state="loading">Загружаю данные сессии…</p>'
        : '<p class="muted" data-sleep-session-state="error">Не удалось загрузить данные сессии. ' +
          "Длительность выше взята из сохранённой точки; выбери точку ещё раз, чтобы повторить.</p>") + fallback;
    }
    if (night.state === "read_limit_exceeded") {
      return '<p class="muted" data-sleep-session-state="limited">За эту дату слишком много ' +
        "сохранённых записей; данные сессии не показаны.</p>" + fallback;
    }
    const session = sessionFor(series, point, night);
    if (!session) {
      return '<p class="muted" data-sleep-session-state="missing">Сессия этой точки не найдена ' +
        "в текущих сохранённых данных: возможно, они обновились. Обнови страницу.</p>" + fallback;
    }
    return nightCard.session(series, session, evidence);
  }

  function buildAxis(svgElement, width, height, pad, dates, xOf, minTickX) {
    function label(x, y, text, anchor, axis) {
      const node = document.createElementNS("http://www.w3.org/2000/svg", "text");
      node.setAttribute("x", x);
      node.setAttribute("y", y);
      node.setAttribute("text-anchor", anchor);
      node.setAttribute("class", "sleep-timeline-axis");
      node.setAttribute("data-axis", axis);
      node.textContent = text;
      svgElement.appendChild(node);
      return node;
    }
    const baseLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    baseLine.setAttribute("x1", pad.l);
    baseLine.setAttribute("y1", height - pad.b);
    baseLine.setAttribute("x2", width - pad.r);
    baseLine.setAttribute("y2", height - pad.b);
    baseLine.style.setProperty("stroke", lineColor);
    svgElement.appendChild(baseLine);
    const leftLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    leftLine.setAttribute("x1", pad.l);
    leftLine.setAttribute("y1", pad.t);
    leftLine.setAttribute("x2", pad.l);
    leftLine.setAttribute("y2", height - pad.b);
    leftLine.style.setProperty("stroke", lineColor);
    svgElement.appendChild(leftLine);
    const spacing = width - pad.l - pad.r;
    let count = Math.min(5, dates.length, Math.max(2, Math.floor(spacing / 90) + 1));
    for (let index = 0; index < count; index += 1) {
      const dateIndex = count === 1 ? 0 : Math.round((dates.length - 1) * index / (count - 1));
      const x = xOf(dateIndex);
      const tick = document.createElementNS("http://www.w3.org/2000/svg", "line");
      tick.setAttribute("x1", x);
      tick.setAttribute("x2", x);
      tick.setAttribute("y1", height - pad.b);
      tick.setAttribute("y2", height - pad.b + 5);
      tick.style.setProperty("stroke", lineColor);
      svgElement.appendChild(tick);
      const anchor = index === 0 ? "start" : index === count - 1 ? "end" : "middle";
      const node = label(x, height - pad.b + 22, "", anchor, "x");
      node.setAttribute("data-date", dates[dateIndex]);
      node.textContent = window.healthcheckOwnerShortDate(dates[dateIndex]);
    }
    return label(minTickX, pad.t - 6, "ч", "start", "unit");
  }

  function draw() {
    const width = Math.max(340, host.clientWidth);
    const height = 320;
    const pad = { l: 56, r: 16, t: 22, b: 64 };
    const dates = data.dates;
    const observedHigh = (function () {
      let top = 0;
      data.display_series.forEach(function (series) {
        series.points.forEach(function (point) {
          if (plotted(point)) top = Math.max(top, point.value_hours);
        });
      });
      return Math.max(1, top * 1.08);
    })();
    const step = niceStep(observedHigh);
    const high = Math.ceil(observedHigh / step) * step;
    const plotHeight = height - pad.t - pad.b;
    const plotWidth = width - pad.l - pad.r;
    const xOf = function (index) {
      return dates.length === 1 ? pad.l + plotWidth / 2 : pad.l + (index / (dates.length - 1)) * plotWidth;
    };
    const yOf = function (hours) {
      return pad.t + (1 - hours / high) * plotHeight;
    };
    host.innerHTML = "";
    host.classList.add("owner-dynamic-chart");
    svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("role", "group");
    svg.setAttribute("aria-label", "Длительность сна, часы по датам пробуждения");
    host.appendChild(svg);
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML = '<pattern id="sleep-gap-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="var(--line-strong)" vector-effect="non-scaling-stroke"/></pattern>';
    svg.appendChild(defs);
    buildAxis(svg, width, height, pad, dates, xOf, pad.l);
    for (let value = 0; value <= high + step / 2; value += step) {
      const y = yOf(value);
      const node = document.createElementNS("http://www.w3.org/2000/svg", "text");
      node.setAttribute("x", pad.l - 8);
      node.setAttribute("y", y + 4);
      node.setAttribute("text-anchor", "end");
      node.setAttribute("class", "sleep-timeline-axis");
      node.setAttribute("data-axis", "y");
      node.textContent = fmtNumber(Math.round(value * 100) / 100) + " ч";
      svg.appendChild(node);
    }
    focusables = [];
    data.display_series.forEach(function (series) {
      const color = seriesColors[series.provider] || seriesColors.garmin;
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      group.setAttribute("data-sleep-series-group", series.series_id);
      group.setAttribute("class", "sleep-timeline-series");
      // One path per contiguous run of adjacent dated values: never a bridge.
      let run = [];
      const flush = function () {
        if (run.length > 1) {
          const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
          path.setAttribute("d", run.map(function (entry, index) {
            return (index ? "L" : "M") + entry.x + " " + entry.y;
          }).join(" "));
          path.setAttribute("fill", "none");
          path.style.setProperty("stroke", color);
          path.setAttribute("stroke-width", "2.5");
          path.setAttribute("data-sleep-line", series.series_id);
          group.appendChild(path);
        }
        run = [];
      };
      series.points.forEach(function (point, index) {
        const x = xOf(index);
        if (plotted(point)) {
          const y = yOf(point.value_hours);
          run.push({ x: x, y: y });
          const wrap = document.createElementNS("http://www.w3.org/2000/svg", "g");
          wrap.setAttribute("class", "sleep-timeline-point");
          wrap.setAttribute("data-sleep-series-id", series.series_id);
          wrap.setAttribute("data-sleep-point-state", "value");
          wrap.setAttribute("data-wake-date", point.wake_date);
          wrap.setAttribute("tabindex", "0");
          wrap.setAttribute("role", "button");
          wrap.setAttribute("aria-label", readableDate(point.wake_date) + " · " + series.label +
            " · " + durationText(point.value_seconds) + " · показать подробности");
          wrap.setAttribute("aria-controls", "sleep-timeline-detail");
          const eventMarker = contextMarker(series, point);
          if (eventMarker) wrap.setAttribute("aria-label", wrap.getAttribute("aria-label") +
            " · " + eventMarker.text);
          const hit = document.createElementNS("http://www.w3.org/2000/svg", "circle");
          hit.setAttribute("cx", x);
          hit.setAttribute("cy", y);
          hit.setAttribute("r", 27);
          hit.setAttribute("fill", "transparent");
          const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
          dot.setAttribute("cx", x);
          dot.setAttribute("cy", y);
          dot.setAttribute("r", 4.5);
          dot.style.setProperty("fill", color);
          dot.setAttribute("class", "sleep-timeline-dot");
          wrap.appendChild(hit);
          wrap.appendChild(dot);
          const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
          title.textContent = readableDate(point.wake_date) + " · " + durationText(point.value_seconds);
          if (eventMarker) {
            title.textContent += " · " + eventMarker.text;
            const eventDot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            eventDot.setAttribute("cx", x);
            eventDot.setAttribute("cy", y - 10);
            eventDot.setAttribute("r", 2.5);
            eventDot.style.setProperty("fill", "var(--muted)");
            eventDot.setAttribute("data-sleep-context-marker", "");
            wrap.appendChild(eventDot);
          }
          wrap.appendChild(title);
          group.appendChild(wrap);
          focusables.push(wrap);
        } else if (point.state === "ambiguous") {
          flush();
          const wrap = document.createElementNS("http://www.w3.org/2000/svg", "g");
          wrap.setAttribute("class", "sleep-timeline-point");
          wrap.setAttribute("data-sleep-series-id", series.series_id);
          wrap.setAttribute("data-sleep-point-state", "ambiguous");
          wrap.setAttribute("data-wake-date", point.wake_date);
          wrap.setAttribute("tabindex", "0");
          wrap.setAttribute("role", "button");
          wrap.setAttribute("aria-label", readableDate(point.wake_date) + " · " + series.label +
            " · несколько записей, значение не выбрано · показать подробности");
          wrap.setAttribute("aria-controls", "sleep-timeline-detail");
          const hit = document.createElementNS("http://www.w3.org/2000/svg", "circle");
          hit.setAttribute("cx", x);
          hit.setAttribute("cy", height - pad.b - 10);
          hit.setAttribute("r", 22);
          hit.setAttribute("fill", "transparent");
          const diamond = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
          const cy = height - pad.b - 10;
          diamond.setAttribute("points", x + "," + (cy - 6) + " " + (x + 6) + "," + cy + " " +
            x + "," + (cy + 6) + " " + (x - 6) + "," + cy);
          diamond.setAttribute("fill", "none");
          diamond.style.setProperty("stroke", unresolvedColor);
          diamond.setAttribute("stroke-width", "2");
          diamond.setAttribute("class", "sleep-timeline-diamond");
          wrap.appendChild(hit);
          wrap.appendChild(diamond);
          const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
          title.textContent = readableDate(point.wake_date) + " · несколько записей; значение не выбрано";
          wrap.appendChild(title);
          group.appendChild(wrap);
          focusables.push(wrap);
        } else {
          flush();
          const tick = document.createElementNS("http://www.w3.org/2000/svg", "rect");
          const gapWidth = Math.max(2, plotWidth / Math.max(1, dates.length));
          tick.setAttribute("x", Math.max(pad.l, x - gapWidth / 2));
          tick.setAttribute("y", pad.t);
          tick.setAttribute("width", Math.min(gapWidth, width - pad.r - Math.max(pad.l, x - gapWidth / 2)));
          tick.setAttribute("height", plotHeight);
          tick.setAttribute("fill", "url(#sleep-gap-hatch)");
          tick.setAttribute("class", "sleep-timeline-gap-tick");
          const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
          title.textContent = readableDate(point.wake_date) + " · " + (point.note || "Нет пригодного значения");
          tick.appendChild(title);
          group.appendChild(tick);
        }
      });
      flush();
      if (hidden[series.series_id]) group.classList.add("is-hidden");
      svg.appendChild(group);
    });
    syncSelection();
    bindPoints();
    window.healthcheckChartLabels(host, svg);
  }

  function nearestFrom(event) {
    if (!svg || !svg.getScreenCTM) return null;
    const cursor = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    let nearest = null;
    let distance = Infinity;
    focusables.forEach(function (node) {
      // A toggled-off series must never win hit-testing or navigation.
      if (hidden[node.getAttribute("data-sleep-series-id")]) return;
      const shape = node.querySelector("circle");
      if (!shape) return;
      const dx = Number(shape.getAttribute("cx")) - cursor.x;
      const dy = Number(shape.getAttribute("cy")) - cursor.y;
      const next = Math.hypot(dx, dy);
      if (next < distance) {
        distance = next;
        nearest = node;
      }
    });
    return nearest && distance <= 27 ? nearest : null;
  }

  function bindPoints() {
    svg.addEventListener("pointermove", function (event) {
      const node = nearestFrom(event);
      if (!node) return;
      const series = seriesFor(node);
      const point = pointFor(node);
      // Moving within one point's hit area keeps its rendered detail as is.
      if (current && current.series === series && current.point === point) return;
      showPoint(series, point);
    });
    focusables.forEach(function (node) {
      const point = pointFor(node);
      const series = seriesFor(node);
      node.addEventListener("focus", function () { showPoint(series, point); });
      node.addEventListener("click", function () { showPoint(series, point); });
      node.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          showPoint(series, point);
        }
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
          event.preventDefault();
          moveNight(event.key === "ArrowRight" ? 1 : -1, true);
        }
      });
    });
  }

  function pointFor(node) {
    const series = seriesFor(node);
    if (!series) return null;
    return series.points.find(function (item) {
      return item.wake_date === node.getAttribute("data-wake-date");
    }) || null;
  }

  function bindLegend() {
    const toggles = document.querySelectorAll("[data-sleep-series-toggle]");
    Array.prototype.forEach.call(toggles, function (toggle) {
      toggle.addEventListener("change", function () {
        const id = toggle.getAttribute("data-sleep-series-toggle");
        hidden[id] = !toggle.checked;
        const label = toggle.closest("label");
        if (label) label.classList.toggle("is-hidden-series", !toggle.checked);
        if (!toggle.checked && current && current.series.series_id === id) {
          const date = current.point.wake_date;
          const next = visibleSeries()[0];
          current = null;
          if (next) showPoint(next, pointAt(next, date));
          else if (detail) detail.textContent = "Выбери источник, чтобы увидеть ночь.";
        } else if (current) {
          showPoint(current.series, current.point);
        } else if (visibleSeries().length) {
          const next = visibleSeries()[0];
          showPoint(next, pointAt(next, data.end_date || data.dates[data.dates.length - 1]));
        }
        syncSelection();
        if (!svg) return;
        const groups = svg.querySelectorAll("[data-sleep-series-group]");
        Array.prototype.forEach.call(groups, function (group) {
          if (group.getAttribute("data-sleep-series-group") === id) {
            group.classList.toggle("is-hidden", !toggle.checked);
          }
        });
      });
    });
  }

  detail.addEventListener("click", function (event) {
    const button = event.target.closest("button");
    if (!button || !current) return;
    const step = button.getAttribute("data-night-step");
    const source = button.getAttribute("data-night-source");
    const latest = button.getAttribute("data-night-latest");
    if (step) moveNight(Number(step), false);
    if (source) {
      const series = visibleSeries().find(item => item.series_id === source);
      if (series) showPoint(series, pointAt(series, current.point.wake_date));
    }
    if (latest) showPoint(current.series, pointAt(current.series, latest));
    // Replacing the card must not drop keyboard focus to the document body.
    const selector = step ? '[data-night-step="' + step + '"]' : source ?
      '[data-night-source="' + source + '"]' : '[data-night-step="-1"]';
    const replacement = detail.querySelector(selector);
    if (replacement) replacement.focus({preventScroll: true});
  });
  // Night selection and source controls also apply when the chart has no markers.
  bindLegend();
  const initial = visibleSeries().find(item => item.provider === "garmin") || visibleSeries()[0];
  showPoint(initial, pointAt(initial, data.end_date || data.dates[data.dates.length - 1]));
  const markerCount = data.display_series.reduce(function (total, series) {
    return total + markerPoints(series).length;
  }, 0);
  if (!markerCount) {
    host.innerHTML = '<p class="muted">За выбранное окно нет сохранённых значений и спорных дат. ' +
      "Пропуски показаны в таблице ниже и не означают ноль.</p>";
    return;
  }
  const legend = document.createElement("p");
  legend.className = "owner-chart-legend";
  legend.innerHTML = '<span class="owner-chart-hatch" aria-hidden="true"></span> \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445';
  host.insertAdjacentElement("afterend", legend);
  const table = document.querySelector("[data-sleep-table]");
  if (table) table.removeAttribute("open");
  draw();
  if (host.sleepResizeObserver) host.sleepResizeObserver.disconnect();
  host.sleepResizeObserver = new ResizeObserver(function () {
    draw();
  });
  host.sleepResizeObserver.observe(host);
})();
