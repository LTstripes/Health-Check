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
  if (!data || !Array.isArray(data.series) || !data.series.length) return;
  const detail = document.getElementById("sleep-timeline-detail");
  const seriesColors = { garmin: "#1d4e89", google: "#3f5f73" };
  const unresolvedColor = "#5c4d86";
  const lineColor = "#d9d0c3";
  let svg = null;
  let hidden = {};
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
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(1).replace(".", ",");
  }

  function durationText(seconds) {
    if (!isNumber(seconds) || seconds < 0) return "недоступно";
    const hours = Math.floor(seconds / 3600);
    const remainder = seconds - hours * 3600;
    const minutes = Math.floor(remainder / 60);
    const rest = remainder - minutes * 60;
    let text = hours + " ч " + minutes + " мин";
    if (rest > 0) text += " " + fmtNumber(Math.round(rest * 100) / 100) + " с";
    return text;
  }

  function readableDate(iso) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("ru-RU", {
      day: "numeric", month: "short", year: "numeric", timeZone: "UTC"
    });
  }

  function plotted(point) {
    return point.state === "value" && isNumber(point.value_hours);
  }

  function markerPoints(series) {
    return series.points.filter(function (point) {
      return plotted(point) || point.state === "ambiguous";
    });
  }

  function niceStep(high) {
    const steps = [0.5, 1, 2, 3, 4, 6, 8, 12, 24];
    for (let index = 0; index < steps.length; index += 1) {
      if (high / steps[index] <= 6) return steps[index];
    }
    return steps[steps.length - 1];
  }

  function seriesFor(element) {
    const id = element.getAttribute("data-sleep-series-id");
    return data.series.find(function (item) { return item.series_id === id; }) || null;
  }

  function sessionFor(series, point) {
    const day = data.nights && data.nights[series.provider]
      ? data.nights[series.provider][point.wake_date] : null;
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

  function sessionDetails(series, session) {
    const metrics = session.metrics || {};
    const cell = function (code) { return metrics[code] || null; };
    const eligible = function (code) {
      const item = cell(code);
      return Boolean(item && item.eligible);
    };
    const rows = [];
    const add = function (label, value) {
      rows.push("<div><dt>" + esc(label) + "</dt><dd>" + value + "</dd></div>");
    };
    if (eligible("sleep_start_at")) {
      add("Начало сессии · UTC", esc(String(cell("sleep_start_at").value)));
    }
    if (eligible("sleep_end_at")) {
      add("Окончание сессии · UTC", esc(String(cell("sleep_end_at").value)));
    }
    if (eligible("sleep_time_in_bed_seconds")) {
      add("Время в постели", durationText(cell("sleep_time_in_bed_seconds").value));
    }
    [
      ["sleep_stage_light_seconds", "Лёгкий сон"],
      ["sleep_stage_deep_seconds", "Глубокий сон"],
      ["sleep_stage_rem_seconds", "Быстрый сон (REM)"],
      ["sleep_awake_waso_seconds", "Бодрствование внутри сессии"]
    ].forEach(function (item) {
      if (eligible(item[0])) add(item[1], durationText(cell(item[0]).value));
    });
    // Native Garmin score stays a per-session detail; Google has no promised score.
    if (series.provider === "garmin" && eligible("sleep_score")) {
      add("Оценка сна Garmin · сессия", fmtNumber(cell("sleep_score").value) + " баллы");
    }
    let html = "";
    if (rows.length) {
      html += '<dl class="sleep-timeline-session">' + rows.join("") + "</dl>";
    } else {
      html += '<p class="muted">Точные время и стадии этой сессии недоступны; запись сессии — в технических деталях.</p>';
    }
    if (session.record_id) {
      html += '<p class="muted">ID записи: ' + esc(session.record_id) + "</p>";
    }
    return html;
  }

  function showPoint(series, point) {
    if (!detail) return;
    current = { series: series, point: point };
    let html = "<h3>Ночь · " + esc(readableDate(point.wake_date)) + "</h3>";
    html += '<p class="sleep-timeline-detail-source">' + esc(series.label) + "</p>";
    if (point.state === "value") {
      html += "<p><strong>" + durationText(point.value_seconds) + "</strong> · " +
        fmtNumber(point.value_seconds) + " с (точное сохранённое значение)</p>";
      if (point.note) html += '<p class="uncertainty-note">' + esc(point.note) + "</p>";
      if (point.role_uncertain) {
        html += '<p class="uncertainty-note">Роль основного сна не подтверждена; запись показана отдельно.</p>';
      }
      const session = sessionFor(series, point);
      if (session) html += sessionDetails(series, session);
    } else if (point.state === "ambiguous") {
      html += '<p class="uncertainty-note">' + esc(point.note) +
        " Значения не объединяются и не усредняются.</p>";
    } else {
      html += "<p>" + esc(point.note || "Нет пригодного значения.") + "</p>";
    }
    detail.innerHTML = html;
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
    baseLine.setAttribute("stroke", lineColor);
    svgElement.appendChild(baseLine);
    const leftLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    leftLine.setAttribute("x1", pad.l);
    leftLine.setAttribute("y1", pad.t);
    leftLine.setAttribute("x2", pad.l);
    leftLine.setAttribute("y2", height - pad.b);
    leftLine.setAttribute("stroke", lineColor);
    svgElement.appendChild(leftLine);
    const spacing = width - pad.l - pad.r;
    let count = Math.min(8, dates.length, Math.max(2, Math.floor(spacing / 90) + 1));
    for (let index = 0; index < count; index += 1) {
      const dateIndex = count === 1 ? 0 : Math.round((dates.length - 1) * index / (count - 1));
      const x = xOf(dateIndex);
      const tick = document.createElementNS("http://www.w3.org/2000/svg", "line");
      tick.setAttribute("x1", x);
      tick.setAttribute("x2", x);
      tick.setAttribute("y1", height - pad.b);
      tick.setAttribute("y2", height - pad.b + 5);
      tick.setAttribute("stroke", lineColor);
      svgElement.appendChild(tick);
      const date = new Date(dates[dateIndex] + "T00:00:00Z");
      const anchor = index === 0 ? "start" : index === count - 1 ? "end" : "middle";
      const node = label(x, height - pad.b + 22, "", anchor, "x");
      node.setAttribute("data-date", dates[dateIndex]);
      [date.toLocaleDateString("ru-RU", {
        day: "numeric", month: "short", timeZone: "UTC"
      }), String(date.getUTCFullYear())].forEach(function (part, row) {
        const tspan = document.createElementNS("http://www.w3.org/2000/svg", "tspan");
        tspan.setAttribute("x", x);
        tspan.setAttribute("dy", row ? "16" : "0");
        tspan.textContent = part;
        node.appendChild(tspan);
      });
    }
    return label(minTickX, pad.t - 6, "ч", "start", "unit");
  }

  function draw() {
    const width = Math.max(340, host.clientWidth);
    const height = 320;
    const pad = { l: 56, r: 16, t: 22, b: 64 };
    const dates = data.dates;
    const high = (function () {
      let top = 0;
      data.series.forEach(function (series) {
        series.points.forEach(function (point) {
          if (plotted(point)) top = Math.max(top, point.value_hours);
        });
      });
      return Math.max(1, top * 1.08);
    })();
    const step = niceStep(high);
    const plotHeight = height - pad.t - pad.b;
    const plotWidth = width - pad.l - pad.r;
    const xOf = function (index) {
      return dates.length === 1 ? pad.l + plotWidth / 2 : pad.l + (index / (dates.length - 1)) * plotWidth;
    };
    const yOf = function (hours) {
      return pad.t + (1 - hours / high) * plotHeight;
    };
    host.innerHTML = "";
    svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("role", "group");
    svg.setAttribute("aria-label", "Длительность сна, часы по датам пробуждения");
    host.appendChild(svg);
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
    data.series.forEach(function (series) {
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
          path.setAttribute("stroke", color);
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
          const hit = document.createElementNS("http://www.w3.org/2000/svg", "circle");
          hit.setAttribute("cx", x);
          hit.setAttribute("cy", y);
          hit.setAttribute("r", 27);
          hit.setAttribute("fill", "transparent");
          const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
          dot.setAttribute("cx", x);
          dot.setAttribute("cy", y);
          dot.setAttribute("r", 4.5);
          dot.setAttribute("fill", color);
          dot.setAttribute("class", "sleep-timeline-dot");
          wrap.appendChild(hit);
          wrap.appendChild(dot);
          const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
          title.textContent = readableDate(point.wake_date) + " · " + durationText(point.value_seconds);
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
          diamond.setAttribute("stroke", unresolvedColor);
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
          tick.setAttribute("x", x - 1);
          tick.setAttribute("y", height - pad.b - 6);
          tick.setAttribute("width", "2");
          tick.setAttribute("height", "6");
          tick.setAttribute("fill", color);
          tick.setAttribute("opacity", "0.45");
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
    if (current) {
      const matches = focusables.filter(function (node) {
        return node.getAttribute("data-sleep-series-id") === current.series.series_id &&
          node.getAttribute("data-wake-date") === current.point.wake_date;
      });
      if (matches.length) matches[0].focus();
    }
    bindPoints();
  }

  function nearestFrom(event) {
    if (!svg || !svg.getScreenCTM) return null;
    const cursor = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    let nearest = null;
    let distance = Infinity;
    focusables.forEach(function (node) {
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
      if (node) showPoint(seriesFor(node), pointFor(node));
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
          const same = focusables.filter(function (item) {
            return item.getAttribute("data-sleep-series-id") === series.series_id;
          });
          const index = same.indexOf(node);
          const next = (index + (event.key === "ArrowRight" ? 1 : -1) + same.length) % same.length;
          same[next].focus();
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

  const markerCount = data.series.reduce(function (total, series) {
    return total + markerPoints(series).length;
  }, 0);
  if (!markerCount) {
    host.innerHTML = '<p class="muted">За выбранное окно нет сохранённых значений и спорных дат. ' +
      "Пропуски показаны в таблице ниже и не означают ноль.</p>";
    return;
  }
  bindLegend();
  draw();
  if (host.sleepResizeObserver) host.sleepResizeObserver.disconnect();
  host.sleepResizeObserver = new ResizeObserver(function () {
    draw();
  });
  host.sleepResizeObserver.observe(host);
})();
