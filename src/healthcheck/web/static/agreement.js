(function () {
  const node = document.getElementById("agreement-data");
  if (!node) return;
  render(JSON.parse(node.textContent));

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/\"/g, "&quot;");
  }

  function value(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "unavailable";
    return digits === undefined ? esc(value) : Number(value).toFixed(digits);
  }

  function render(payload) {
    renderSummary(payload);
    renderGroups(payload.groups || []);
    renderQuality(payload.source_data_quality || []);
  }

  function renderSummary(payload) {
    const host = document.getElementById("agreement-summary");
    if (!host) return;
    if (!payload.available) {
      host.innerHTML = '<p class="unavailable">Exploratory agreement is unavailable.</p><p class="muted">Reason: ' + esc(payload.reason || "unknown") + "</p>";
      return;
    }
    const groups = payload.groups || [];
    const ready = groups.filter(function (item) { return item.progress && item.progress.exploratory_available; }).length;
    host.innerHTML =
      "<h2>Report status</h2>" +
      "<p><strong>" + (payload.mode === "exploratory" ? "Exploratory packet available" : "Accumulating evidence") + "</strong> · " +
      ready + " of " + groups.length + " metric/cohort groups at N=" + esc(payload.threshold.exploratory_n) + "</p>" +
      "<p class=\"muted\">Each summary below keeps device_pair (Fitbit device evidence) distinct from family_pair (Google wearable family evidence).</p>";
  }

  function renderGroups(groups) {
    const host = document.getElementById("agreement-groups");
    if (!host) return;
    host.innerHTML = "";
    if (!groups.length) {
      host.innerHTML = '<section class="card"><p class="unavailable">No frozen metric groups.</p></section>';
      return;
    }
    groups.forEach(function (group) {
      const card = document.createElement("section");
      card.className = "card agreement-group";
      const stats = group.accepted_statistics;
      const progress = group.progress || {};
      const coverage = group.coverage || {};
      const exclusions = Object.keys(group.exclusions || {}).map(function (reason) {
        return "<li>" + esc(reason) + ": " + esc(group.exclusions[reason]) + "</li>";
      }).join("");
      const points = (group.chart && group.chart.points) || [];
      card.innerHTML =
        "<header><h2>" + esc(group.metric_code) + "</h2><span class=\"status-chip " + esc(group.cohort) + "\">" + esc(group.cohort) + "</span></header>" +
        "<p class=\"muted\">" + esc(group.source_attribution.cohort_label) + " · source classes: " + esc((group.source_attribution.source_classes || []).join(", ") || "unknown") + "</p>" +
        "<dl class=\"agreement-metrics\"><div><dt>N</dt><dd>" + esc(group.n) + "</dd></div><div><dt>Paired nights</dt><dd>" + esc(group.paired_nights) + "</dd></div><div><dt>Coverage</dt><dd>" + esc(coverage.requested_calendar_nights === null ? "unknown" : coverage.metric_valid_nights + "/" + coverage.requested_calendar_nights) + "</dd></div><div><dt>Progress</dt><dd>" + esc(progress.remaining_n ? "" + progress.remaining_n + " nights to N=14" : "N=14 reached") + "</dd></div></dl>" +
        (stats ? renderStats(stats) : '<p class="unavailable">Accepted statistics are withheld until N=14. Accumulation diagnostics remain available.</p>') +
        (exclusions ? "<p><strong>Metric exclusions</strong></p><ul class=\"exclusion-list\">" + exclusions + "</ul>" : "") +
        "<div class=\"agreement-chart\" aria-label=\"Agreement differences\"><svg viewBox=\"0 0 900 150\" role=\"img\"></svg></div>" +
        "<p><a href=\"" + esc(group.drilldown_url) + "\">Open frozen night drill-down</a></p>";
      host.appendChild(card);
      drawChart(card.querySelector("svg"), points);
    });
  }

  function renderStats(stats) {
    return "<details open><summary>Accepted exploratory statistics (N=" + esc(stats.n) + ")</summary>" +
      "<p>Bias " + value(stats.bias, 2) + ", MAE " + value(stats.mae, 2) + ", RMSE " + value(stats.rmse, 2) + " · gate " + esc((stats.gate || {}).exploratory || "unknown") + "</p>" +
      "<p class=\"muted\">Difference convention: Google − Garmin. These statistics are exploratory evidence, not an accuracy or canonical-source decision.</p></details>";
  }

  function drawChart(svg, points) {
    if (!svg || !points.length) {
      if (svg) svg.outerHTML = '<p class="unavailable">No comparable points.</p>';
      return;
    }
    const width = 900, height = 150, left = 40, right = 12, top = 12, bottom = 24;
    const values = points.map(function (point) { return Number(point.difference); }).filter(Number.isFinite);
    const min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    const span = max === min ? 1 : max - min;
    const path = points.map(function (point, index) {
      const x = left + (index / Math.max(1, points.length - 1)) * (width - left - right);
      const y = top + (1 - (Number(point.difference) - min) / span) * (height - top - bottom);
      return (index ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }).join(" ");
    svg.innerHTML = '<line x1="' + left + '" y1="' + (height - bottom) + '" x2="' + (width - right) + '" y2="' + (height - bottom) + '" stroke="#d9d0c3"/><path d="' + path + '" fill="none" stroke="#0f6d6a" stroke-width="2"/><text x="' + left + '" y="' + (height - 5) + '" font-size="11">' + esc(points[0].wake_date) + '</text><text x="' + (width - 120) + '" y="' + (height - 5) + '" font-size="11">' + esc(points[points.length - 1].wake_date) + '</text>';
  }

  function renderQuality(facts) {
    const host = document.getElementById("agreement-quality");
    if (!host) return;
    if (!facts.length) {
      host.innerHTML = '<p class="unavailable">Data quality state: unknown / not established.</p>';
      return;
    }
    const rows = facts.map(function (item) {
      return "<tr><td>" + esc(item.provider_display_name || item.provider_code) + "</td><td>" + esc(item.state) + "</td><td>" + esc(item.last_successful_sync || "unknown") + "</td><td>" + esc(item.last_actual_measurement_or_evidence_date || "unknown") + "</td><td>" + esc(item.last_sync_status || "unknown") + "</td></tr>";
    }).join("");
    host.innerHTML = '<table><thead><tr><th>Provider</th><th>State</th><th>Last successful sync</th><th>Last actual measurement/evidence</th><th>Last sync status</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }
})();
