(function () {
  const dataNode = document.getElementById("dashboard-data");
  if (dataNode) {
    const payload = JSON.parse(dataNode.textContent);
    renderDashboard(payload);
  }
  bindReview();
  bindUpload();

  function renderDashboard(payload) {
    const series = payload.series || {};
    const summary = payload.summary || {};
    renderGoalDistance();
    renderHeroRate(summary.rate || {});
    renderHeroStatus(payload);
    drawWeightChart(series);
    renderTrendStatus(series);
    renderRate(summary.rate || {});
    renderCoverage(summary.coverage);
    renderLatestComposition(summary.latest_composition || {});
    renderSimilar(summary.similar_weight || {});
    renderCompositionGroups(series.composition_by_group || {});
  }

  function isNumber(value) {
    return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  }

  function fmt(value, digits) {
    return isNumber(value) ? Number(value).toFixed(digits) : "unavailable";
  }

  function renderGoalDistance() {
    const stat = document.querySelector("[data-current-value][data-goal-value]");
    const valueNode = document.getElementById("goal-distance");
    const noteNode = document.getElementById("goal-distance-note");
    if (!stat || !valueNode || !noteNode) return;
    const current = stat.getAttribute("data-current-value");
    const goal = stat.getAttribute("data-goal-value");
    if (!isNumber(current) || !isNumber(goal)) return;
    const difference = Number(current) - Number(goal);
    if (Math.abs(difference) < 0.05) {
      valueNode.textContent = "At goal";
      noteNode.textContent = "Configured goal " + fmt(goal, 1) + " kg";
      return;
    }
    valueNode.textContent = fmt(Math.abs(difference), 1) + " kg";
    noteNode.textContent = (difference > 0 ? "Above" : "Below") + " configured goal · " + fmt(goal, 1) + " kg";
  }

  function renderHeroRate(rate) {
    const valueNode = document.getElementById("hero-rate");
    const noteNode = document.getElementById("hero-rate-note");
    if (!valueNode || !noteNode) return;
    if (!rate.available || !isNumber(rate.slope_kg_per_week)) {
      valueNode.innerHTML = '<span class="unavailable">Unavailable</span>';
      noteNode.textContent = "Not enough compatible observations yet";
      return;
    }
    const slope = Number(rate.slope_kg_per_week);
    valueNode.textContent = (slope > 0 ? "+" : "") + fmt(slope, 2) + " kg/week";
    noteNode.textContent = "Trailing 90 days · " + rate.observation_count + " observations";
  }

  function renderHeroStatus(payload) {
    const node = document.getElementById("hero-status");
    if (!node) return;
    const canonical = payload.canonical || {};
    if (canonical.stale) {
      node.innerHTML = '<span class="unavailable">Review freshness</span>';
      return;
    }
    if (canonical.available && canonical.fresh) {
      node.textContent = "Current snapshot";
      return;
    }
    node.innerHTML = '<span class="unavailable">Awaiting data</span>';
  }

  function renderTrendStatus(series) {
    const node = document.getElementById("trend-status");
    if (!node) return;
    if (series.trend_available) {
      node.textContent = "21-day time-aware trend · " + (series.input_count || 0) + " confirmed observations";
    } else {
      node.textContent = "Trend unavailable · " + (series.trend_reason || "no_data");
    }
  }

  function renderRate(rate) {
    const node = document.getElementById("rate-panel");
    if (!node) return;
    if (!rate.available || !isNumber(rate.slope_kg_per_week)) {
      node.innerHTML = '<p class="panel-value unavailable">Unavailable</p><p class="metric-note">' +
        escapeHtml(rate.reason || "No compatible observations yet") + ". Missing rate is not shown as 0.</p>";
      return;
    }
    const slope = Number(rate.slope_kg_per_week);
    node.innerHTML = '<p class="panel-value">' + (slope > 0 ? "+" : "") + fmt(slope, 3) + " kg/week</p>" +
      '<p class="metric-note">' + rate.observation_count + " observations spanning " + rate.covered_span_days +
      " days · " + escapeHtml(rate.window_start_date || "") + " to " + escapeHtml(rate.window_end_date || "") + ".</p>";
  }

  function renderCoverage(coverage) {
    const node = document.getElementById("coverage-panel");
    if (!node) return;
    if (!coverage) {
      node.innerHTML = '<p class="unavailable">Unavailable</p><p class="muted">Reason: no_data</p>';
      return;
    }
    const counts = coverage.status_counts || {};
    const count = function (key) {
      return counts[key] === null || counts[key] === undefined ? "unavailable" : counts[key];
    };
    node.innerHTML = '<dl class="panel-list">' +
      metric("Observed dates", coverage.observed_dates ? coverage.observed_dates.length : null) +
      metric("Covered cadence", (coverage.covered_bin_count ?? "unavailable") + " / " + (coverage.expected_bin_count ?? "unavailable")) +
      metric("Freshness", nullable(coverage.freshness_days, " days")) +
      metric("Longest gap", nullable(coverage.longest_gap_days, " days")) +
      '</dl><p class="metric-note">States · present ' + count("present") + " · unknown " + count("unknown") +
      " · unavailable " + count("unavailable") + " · failed " + count("failed") +
      " · confirmed empty " + count("confirmed_empty") + "</p>";
  }

  function nullable(value, suffix) {
    return isNumber(value) ? value + suffix : "unavailable";
  }

  function metric(label, value) {
    return "<div><dt>" + label + "</dt><dd>" + escapeHtml(String(value)) + "</dd></div>";
  }

  function renderLatestComposition(item) {
    const node = document.getElementById("composition-latest");
    if (!node) return;
    if (!item.available) {
      node.innerHTML = '<p class="panel-value unavailable">Unavailable</p><p class="metric-note">Reason: ' +
        escapeHtml(item.reason || "no_data") + "</p>";
      return;
    }
    const sourceMuscle = isNumber(item.source_muscle_mass_kg) ? fmt(item.source_muscle_mass_kg, 1) + " kg" : "unavailable";
    node.innerHTML = '<div class="composition-list">' +
      compositionItem("Body fat", fmt(item.body_fat_pct, 1) + "%", "source") +
      compositionItem("Estimated fat mass", fmt(item.estimated_fat_mass_kg, 1) + " kg", "Health-Check derived") +
      compositionItem("Estimated lean mass", fmt(item.estimated_lean_mass_kg, 1) + " kg", "Health-Check derived") +
      compositionItem("Source muscle mass", sourceMuscle, "source · not estimated lean mass") +
      '</div><p class="caution">Same algorithm group: ' + escapeHtml(item.compatibility_group || "unknown") +
      ". " + escapeHtml(item.caution || "Consumer BIA values are estimates.") + "</p>";
  }

  function compositionItem(label, value, origin) {
    return '<div class="composition-item"><span>' + label + '<span class="origin">' + origin +
      '</span></span><strong>' + escapeHtml(value) + "</strong></div>";
  }

  function renderSimilar(item) {
    const node = document.getElementById("similar-panel");
    if (!node) return;
    if (!item.available) {
      node.innerHTML = '<p class="panel-value unavailable">Unavailable</p><p class="metric-note">' +
        escapeHtml(item.reason || "no_data") + ". More compatible, spaced observations are needed.</p>";
      return;
    }
    node.innerHTML = '<p class="panel-value">' + escapeHtml(item.earlier_date) + " → " + escapeHtml(item.later_date) +
      '</p><p class="metric-note">' + item.days_apart + " days apart · weight " + fmt(item.earlier_weight_kg, 1) +
      " → " + fmt(item.later_weight_kg, 1) + " kg</p><p class=\"metric-note\">Body fat " +
      fmt(item.earlier_body_fat_pct, 1) + " → " + fmt(item.later_body_fat_pct, 1) +
      " pp · same group " + escapeHtml(item.compatibility_group || "") +
      ". Not a claim of real muscle gain or fat loss.</p>";
  }

  function renderCompositionGroups(groups) {
    const node = document.getElementById("composition-groups");
    if (!node) return;
    const names = Object.keys(groups);
    if (!names.length) {
      node.innerHTML = '<div class="empty-state"><strong>No confirmed composition series.</strong><br>Compatible body-composition data will appear here after confirmation.</div>';
      return;
    }
    node.innerHTML = "";
    names.forEach(function (group) {
      const wrap = document.createElement("div");
      wrap.className = "algorithm-group";
      wrap.innerHTML = '<div class="group-heading"><h3>Algorithm group <code>' + escapeHtml(group) +
        '</code></h3><p>' + groups[group].length + " compatible readings</p></div>";
      const chart = document.createElement("div");
      chart.className = "chart chart-shell";
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
      host.innerHTML = '<div class="chart-empty"><p class="unavailable">No confirmed weight observations yet.</p></div>';
      return;
    }
    const points = raw.map(function (item) {
      return { date: item.observed_date, value: item.value_kg, id: item.evidence_id, kind: "raw", provenance: item.provenance };
    });
    const trendPoints = trend.map(function (item) {
      return { date: item.observed_date, value: item.trend_kg, kind: "trend" };
    });
    const allValues = points.concat(trendPoints).map(function (item) { return item.value; });
    if (isNumber(series.goal_kg)) allValues.push(series.goal_kg);
    host.innerHTML = "";
    host.appendChild(svgSeries(points, trendPoints, series.goal_kg, allValues, function (point) {
      showProvenance(point.provenance || { evidence_id: point.id });
    }, "kg"));
  }

  function drawCompositionChart(host, points, group) {
    const fat = (points || []).filter(function (item) { return isNumber(item.body_fat_pct); }).map(function (item) {
      return { date: item.observed_date, value: item.body_fat_pct, kind: "raw" };
    });
    if (!fat.length) {
      host.innerHTML = '<div class="chart-empty"><p class="unavailable">No body-fat points in ' + escapeHtml(group) + ".</p></div>";
      return;
    }
    host.appendChild(svgSeries(fat, [], null, fat.map(function (item) { return item.value; }), null, "%"));
    const tableWrap = document.createElement("div");
    tableWrap.className = "table-scroll";
    const table = document.createElement("table");
    table.innerHTML = '<thead><tr><th>Date</th><th>Body fat %<br><span class="muted">source</span></th><th>Fat mass kg<br><span class="muted">derived</span></th><th>Lean mass kg<br><span class="muted">derived</span></th><th>Muscle kg<br><span class="muted">source</span></th></tr></thead>';
    const body = document.createElement("tbody");
    points.forEach(function (item) {
      const row = document.createElement("tr");
      row.innerHTML = "<td>" + escapeHtml(item.observed_date) + "</td><td>" + fmt(item.body_fat_pct, 1) +
        "</td><td>" + fmt(item.estimated_fat_mass_kg, 1) + "</td><td>" + fmt(item.estimated_lean_mass_kg, 1) +
        "</td><td>" + fmt(item.source_muscle_mass_kg, 1) + "</td>";
      body.appendChild(row);
    });
    table.appendChild(body);
    tableWrap.appendChild(table);
    host.appendChild(tableWrap);
  }

  function svgSeries(rawPoints, trendPoints, goal, values, onClick, unit) {
    const width = 1000;
    const height = 300;
    const pad = { l: 56, r: 24, t: 20, b: 42 };
    const dates = rawPoints.concat(trendPoints).map(function (item) { return Date.parse(item.date); });
    const minX = Math.min.apply(null, dates);
    const maxX = Math.max.apply(null, dates);
    const minY = Math.min.apply(null, values);
    const maxY = Math.max.apply(null, values);
    const spanY = maxY === minY ? 1 : maxY - minY;
    const spanX = maxX === minX ? 1 : maxX - minX;
    const yMin = minY - spanY * 0.12;
    const yMax = maxY + spanY * 0.12;
    const ySpan = yMax - yMin || 1;
    const xOf = function (date) { return pad.l + ((Date.parse(date) - minX) / spanX) * (width - pad.l - pad.r); };
    const yOf = function (value) { return pad.t + (1 - (value - yMin) / ySpan) * (height - pad.t - pad.b); };
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Time series chart");
    const grid = document.createElementNS("http://www.w3.org/2000/svg", "g");
    grid.setAttribute("class", "chart-grid");
    for (let index = 0; index <= 4; index += 1) {
      const value = yMin + ((yMax - yMin) * index) / 4;
      const y = yOf(value);
      grid.appendChild(svgLine(pad.l, y, width - pad.r, y, "#dbe5df", "1"));
      grid.appendChild(svgText(pad.l - 8, y + 4, fmt(value, 1), "end", "#627169"));
    }
    const datePoints = rawPoints.concat(trendPoints);
    if (datePoints.length) {
      [datePoints[0], datePoints[datePoints.length - 1]].forEach(function (item, index) {
        grid.appendChild(svgText(xOf(item.date), height - 13, shortDate(item.date), index ? "end" : "start", "#627169"));
      });
    }
    svg.appendChild(grid);
    if (isNumber(goal)) {
      const goalLine = svgLine(pad.l, yOf(goal), width - pad.r, yOf(goal), "#76639c", "2");
      goalLine.setAttribute("stroke-dasharray", "7 5");
      goalLine.setAttribute("data-series", "goal");
      svg.appendChild(goalLine);
    }
    if (trendPoints.length > 1) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", trendPoints.map(function (item, index) { return (index ? "L" : "M") + xOf(item.date) + " " + yOf(item.value); }).join(" "));
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "#d46b3c");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
      path.setAttribute("stroke-width", "4");
      path.setAttribute("data-series", "trend");
      svg.appendChild(path);
    }
    rawPoints.forEach(function (item) {
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", xOf(item.date));
      circle.setAttribute("cy", yOf(item.value));
      circle.setAttribute("r", "5");
      circle.setAttribute("fill", "#547a70");
      circle.setAttribute("stroke", "#ffffff");
      circle.setAttribute("stroke-width", "2");
      circle.setAttribute("data-series", "raw");
      circle.setAttribute("data-evidence-id", item.id || "");
      circle.setAttribute("tabindex", "0");
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = item.date + " · " + fmt(item.value, 1) + " " + (unit || "kg");
      circle.appendChild(title);
      attachTooltip(svg, circle, title.textContent);
      if (onClick) {
        circle.addEventListener("click", function () { onClick(item); });
        circle.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onClick(item); }
        });
      }
      svg.appendChild(circle);
    });
    return svg;
  }

  function svgLine(x1, y1, x2, y2, stroke, width) {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", x1); line.setAttribute("y1", y1); line.setAttribute("x2", x2); line.setAttribute("y2", y2);
    line.setAttribute("stroke", stroke); line.setAttribute("stroke-width", width);
    return line;
  }

  function svgText(x, y, value, anchor, fill) {
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", x); text.setAttribute("y", y); text.setAttribute("text-anchor", anchor); text.setAttribute("fill", fill); text.setAttribute("font-size", "12");
    text.textContent = value;
    return text;
  }

  function shortDate(value) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function attachTooltip(svg, target, value) {
    target.addEventListener("mouseenter", function () { showTooltip(svg, target, value); });
    target.addEventListener("focus", function () { showTooltip(svg, target, value); });
    target.addEventListener("mouseleave", function () { hideTooltip(svg); });
    target.addEventListener("blur", function () { hideTooltip(svg); });
  }

  function showTooltip(svg, target, value) {
    const host = svg.parentElement;
    if (!host) return;
    let tooltip = host.querySelector(".chart-tooltip");
    if (!tooltip) {
      tooltip = document.createElement("div");
      tooltip.className = "chart-tooltip";
      host.appendChild(tooltip);
    }
    const targetRect = target.getBoundingClientRect();
    const hostRect = host.getBoundingClientRect();
    tooltip.textContent = value;
    tooltip.style.left = (targetRect.left - hostRect.left + targetRect.width / 2) + "px";
    tooltip.style.top = (targetRect.top - hostRect.top) + "px";
    tooltip.classList.add("visible");
  }

  function hideTooltip(svg) {
    const tooltip = svg.parentElement && svg.parentElement.querySelector(".chart-tooltip");
    if (tooltip) tooltip.classList.remove("visible");
  }

  function showProvenance(info) {
    const node = document.getElementById("provenance-panel");
    if (!node) return;
    const lines = [
      "evidence_id: " + (info.evidence_id || "unavailable"),
      "provider: " + (info.provider_code || "unavailable") + " (" + (info.provider_display_name || "") + ")",
      "device: " + (info.device_code || "unavailable") + " (" + (info.device_display_name || "") + ")",
      "input_method: " + (info.input_method || "unavailable"),
      "source_application: " + (info.source_application || "unavailable"),
      "algorithm: " + (info.algorithm_code || "unavailable") + " @ " + (info.algorithm_version || "unavailable"),
      "compatibility_group: " + (info.compatibility_group || "unavailable"),
      "temporal_precision: " + (info.temporal_precision || "unavailable"),
      "source_local_date: " + (info.source_local_date || "unavailable"),
      "source_timestamp_utc: " + (info.source_timestamp_utc || "null (date-only, no invented midnight)"),
      "artifact_content_hash: " + (info.artifact_content_hash || "unavailable"),
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
    const selectionCount = document.getElementById("selection-count");
    function refresh() {
      const selected = boxes.filter(function (box) { return box.checked; });
      [confirmIds, rejectIds].forEach(function (host) { if (host) host.innerHTML = ""; });
      selected.forEach(function (box) {
        [confirmIds, rejectIds].forEach(function (host) {
          if (!host) return;
          const input = document.createElement("input");
          input.type = "hidden"; input.name = "candidate_ids"; input.value = box.value;
          host.appendChild(input);
        });
      });
      if (selectionCount) selectionCount.textContent = selected.length + " selected";
      if (confirmButton) { confirmButton.disabled = selected.length === 0; confirmButton.textContent = selected.length ? "Confirm selected (" + selected.length + ")" : "Confirm selected"; }
      if (rejectButton) { rejectButton.disabled = selected.length === 0; rejectButton.textContent = selected.length ? "Reject selected (" + selected.length + ")" : "Reject selected"; }
      if (!preview) return;
      if (!selected.length) {
        preview.classList.add("empty"); preview.textContent = "Select candidates to preview committed values."; return;
      }
      const items = selected.map(function (box) {
        const row = box.closest(".candidate-row");
        const value = row.getAttribute("data-value");
        return row.getAttribute("data-metric") + ": " + (value && value !== "None" ? value : "missing") + " " +
          (row.getAttribute("data-unit") || "") + " on " + (row.getAttribute("data-date") || "unknown date") +
          (row.getAttribute("data-committed") === "true" ? " (already confirmed, replay)" : " (will confirm)");
      });
      preview.classList.remove("empty");
      preview.innerHTML = "<ul>" + items.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("") + "</ul>";
    }
    boxes.forEach(function (box) { box.addEventListener("change", refresh); });
    refresh();
  }

  function bindUpload() {
    const input = document.getElementById("photo-files");
    const note = document.getElementById("upload-selection");
    if (!input || !note) return;
    input.addEventListener("change", function () {
      const count = input.files ? input.files.length : 0;
      note.textContent = count ? count + (count === 1 ? " image ready for extraction." : " images ready for extraction.") : "No files selected yet.";
    });
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
})();
