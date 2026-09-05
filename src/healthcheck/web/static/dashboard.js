(function () {
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
    renderLatestComposition(summary.latest_composition || {});
    renderSimilar(summary.similar_weight || {});
    renderCompositionGroups(series.composition_by_group || {});
  }

  function fmt(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "unavailable";
    }
    return Number(value).toFixed(digits);
  }

  function renderTrendStatus(series) {
    const node = document.getElementById("trend-status");
    if (!node) return;
    if (series.trend_available) {
      node.textContent =
        "Trend algorithm " +
        (series.trend_algorithm || "weight_trend_taewma_v1") +
        " · " +
        (series.input_count || 0) +
        " confirmed observations";
    } else {
      node.textContent = "Trend unavailable (" + (series.trend_reason || "no_data") + ")";
    }
  }

  function renderRate(rate) {
    const node = document.getElementById("rate-panel");
    if (!node) return;
    if (!rate.available) {
      node.innerHTML =
        '<p class="unavailable">unavailable</p><p class="muted">Reason: ' +
        escapeHtml(rate.reason || "no_data") +
        ". Missing rate is not shown as 0.</p>";
      return;
    }
    node.innerHTML =
      "<p><strong>" +
      fmt(rate.slope_kg_per_week, 3) +
      " kg/week</strong></p>" +
      "<p class=\"muted\">" +
      rate.observation_count +
      " daily points spanning " +
      rate.covered_span_days +
      " days (" +
      (rate.window_start_date || "") +
      " to " +
      (rate.window_end_date || "") +
      ").</p>";
  }

  function renderCoverage(coverage) {
    const node = document.getElementById("coverage-panel");
    if (!node) return;
    if (!coverage) {
      node.innerHTML = '<p class="unavailable">unavailable</p><p class="muted">Reason: no_data</p>';
      return;
    }
    const counts = coverage.status_counts || {};
    node.innerHTML =
      "<ul>" +
      "<li>Observed dates: " +
      (coverage.observed_dates ? coverage.observed_dates.length : 0) +
      "</li>" +
      "<li>Covered cadence bins: " +
      (coverage.covered_bin_count ?? "unavailable") +
      " / " +
      (coverage.expected_bin_count ?? "unavailable") +
      "</li>" +
      "<li>Freshness (days): " +
      (coverage.freshness_days === null || coverage.freshness_days === undefined
        ? "unavailable"
        : coverage.freshness_days) +
      "</li>" +
      "<li>Longest gap (days): " +
      (coverage.longest_gap_days === null || coverage.longest_gap_days === undefined
        ? "unavailable"
        : coverage.longest_gap_days) +
      "</li>" +
      "<li>States — present " +
      (counts.present || 0) +
      ", unknown " +
      (counts.unknown || 0) +
      ", unavailable " +
      (counts.unavailable || 0) +
      ", failed " +
      (counts.failed || 0) +
      ", confirmed empty " +
      (counts.confirmed_empty || 0) +
      "</li>" +
      "</ul>";
  }

  function renderLatestComposition(item) {
    const node = document.getElementById("composition-latest");
    if (!node) return;
    if (!item.available) {
      node.innerHTML =
        '<p class="unavailable">unavailable</p><p class="muted">Reason: ' +
        escapeHtml(item.reason || "no_data") +
        "</p>";
      return;
    }
    node.innerHTML =
      "<p>Body fat " +
      fmt(item.body_fat_pct, 1) +
      "% (source)</p>" +
      "<p>Estimated fat mass " +
      fmt(item.estimated_fat_mass_kg, 1) +
      " kg (Health-Check derived)</p>" +
      "<p>Estimated lean mass " +
      fmt(item.estimated_lean_mass_kg, 1) +
      " kg (Health-Check derived)</p>" +
      "<p class=\"muted\">Group " +
      escapeHtml(item.compatibility_group || "unknown") +
      ". " +
      escapeHtml(item.caution || "") +
      "</p>";
  }

  function renderSimilar(item) {
    const node = document.getElementById("similar-panel");
    if (!node) return;
    if (!item.available) {
      node.innerHTML =
        '<p class="unavailable">unavailable</p><p class="muted">Reason: ' +
        escapeHtml(item.reason || "no_data") +
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
      " days)</p>" +
      "<p>Weight " +
      fmt(item.earlier_weight_kg, 1) +
      " → " +
      fmt(item.later_weight_kg, 1) +
      " kg</p>" +
      "<p>Body fat " +
      fmt(item.earlier_body_fat_pct, 1) +
      " → " +
      fmt(item.later_body_fat_pct, 1) +
      " pp (source)</p>" +
      "<p class=\"muted\">Same group " +
      escapeHtml(item.compatibility_group || "") +
      ". Not a claim of real muscle gain or fat loss.</p>";
  }

  function renderCompositionGroups(groups) {
    const node = document.getElementById("composition-groups");
    if (!node) return;
    const names = Object.keys(groups);
    if (!names.length) {
      node.innerHTML = '<p class="unavailable">No confirmed composition series.</p>';
      return;
    }
    node.innerHTML = "";
    names.forEach(function (group) {
      const wrap = document.createElement("div");
      wrap.innerHTML = "<h3>Algorithm group <code>" + escapeHtml(group) + "</code></h3>";
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
      host.innerHTML = '<p class="unavailable">No confirmed weight observations.</p>';
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
      host.innerHTML = '<p class="unavailable">No body-fat points in ' + escapeHtml(group) + ".</p>";
      return;
    }
    host.appendChild(svgSeries(fat, [], null, fat.map(function (item) { return item.value; }), null, "%"));
    const table = document.createElement("table");
    table.innerHTML =
      "<thead><tr><th>Date</th><th>Body fat % (source)</th><th>Est. fat mass kg (derived)</th><th>Est. lean mass kg (derived)</th><th>Source muscle kg</th></tr></thead>";
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
          ? "unavailable"
          : fmt(item.source_muscle_mass_kg, 1)) +
        "</td>";
      body.appendChild(row);
    });
    table.appendChild(body);
    host.appendChild(table);
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
      goalLine.setAttribute("stroke", "#6b4ea2");
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
      path.setAttribute("stroke", "#c45c26");
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
      title.textContent = item.date + " · " + fmt(item.value, 1) + (unit || " kg");
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
    const lines = [
      "evidence_id: " + (info.evidence_id || ""),
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
        preview.textContent = "Select candidates to preview committed values.";
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
          " on " +
          (row.getAttribute("data-date") || "unknown date") +
          (row.getAttribute("data-committed") === "true" ? " (already confirmed, replay)" : " (will confirm)")
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
