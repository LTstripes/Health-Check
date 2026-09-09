(function () {
  const dataNode = document.getElementById("garmin-dashboard-data");
  if (!dataNode) return;
  const payload = JSON.parse(dataNode.textContent || "{}");
  const state = {
    sourceId: (payload.source_selection && payload.source_selection.selected_source_id) || "",
    activities: payload.activities || [],
    series: payload.series || null,
    nativeLabels: payload.native_score_labels || {},
  };

  bindForms();
  populateActivities(state.activities);
  renderMetricWording();
  if (state.series) {
    renderSeries(state.series);
  } else {
    renderNoSeries(payload.unavailable_reason || (payload.source_selection && payload.source_selection.reason) || "no_data");
  }

  function bindForms() {
    const sourceForm = document.getElementById("source-form");
    if (sourceForm) {
      sourceForm.addEventListener("submit", function (event) {
        event.preventDefault();
        const sourceId = document.getElementById("garmin-source-id").value;
        const metric = document.getElementById("metric-code").value;
        const start = document.getElementById("series-start").value;
        const end = document.getElementById("series-end").value;
        const params = new URLSearchParams();
        if (sourceId) params.set("garmin_source_id", sourceId);
        if (metric) params.set("metric_code", metric);
        if (start) params.set("start_date", start);
        if (end) params.set("end_date", end);
        window.location = "/garmin?" + params.toString();
      });
    }

    const seriesForm = document.getElementById("series-form");
    if (seriesForm) {
      seriesForm.addEventListener("submit", function (event) {
        event.preventDefault();
        loadSeries();
      });
      const metricSelect = document.getElementById("metric-code");
      if (metricSelect) metricSelect.addEventListener("change", renderMetricWording);
    }

    const activityForm = document.getElementById("activity-form");
    if (activityForm) {
      activityForm.addEventListener("submit", function (event) {
        event.preventDefault();
        loadActivityComparison();
      });
      const activitySelect = document.getElementById("activity-ids");
      if (activitySelect) {
        activitySelect.addEventListener("change", syncReferenceOptions);
      }
    }

    const lagForm = document.getElementById("lag-form");
    if (lagForm) {
      lagForm.addEventListener("submit", function (event) {
        event.preventDefault();
        loadLaggedAssociation();
      });
    }
  }

  function requireSourceId() {
    const fromSelect = document.getElementById("garmin-source-id");
    const sourceId = (fromSelect && fromSelect.value) || state.sourceId;
    if (!sourceId) {
      throw new Error("Select an explicit Garmin source first");
    }
    return sourceId;
  }

  function loadSeries() {
    let sourceId;
    try {
      sourceId = requireSourceId();
    } catch (err) {
      renderNoSeries(err.message);
      return;
    }
    const metric = document.getElementById("metric-code").value;
    const start = document.getElementById("series-start").value;
    const end = document.getElementById("series-end").value;
    const params = new URLSearchParams({
      garmin_source_id: sourceId,
      metric_code: metric,
      start_date: start,
      end_date: end,
    });
    fetchJson("/api/garmin/series?" + params.toString())
      .then(function (body) {
        state.series = body;
        renderSeries(body);
      })
      .catch(function (err) {
        renderNoSeries(err.message || "request_failed");
      });
  }

  function loadActivityComparison() {
    let sourceId;
    try {
      sourceId = requireSourceId();
    } catch (err) {
      setHtml("activity-result", unavailable(err.message));
      return;
    }
    const selected = Array.from(document.getElementById("activity-ids").selectedOptions).map(
      function (option) {
        return option.value;
      }
    );
    const reference = document.getElementById("reference-activity-id").value;
    if (selected.length < 2) {
      setHtml("activity-result", unavailable("select 2..20 activity records"));
      return;
    }
    const params = new URLSearchParams({
      garmin_source_id: sourceId,
      activity_record_ids: selected.join(","),
      reference_activity_id: reference,
    });
    fetchJson("/api/garmin/activity-comparison?" + params.toString())
      .then(renderActivityResult)
      .catch(function (err) {
        setHtml("activity-result", unavailable(err.message || "request_failed"));
      });
  }

  function loadLaggedAssociation() {
    let sourceId;
    try {
      sourceId = requireSourceId();
    } catch (err) {
      setHtml("lag-result", unavailable(err.message));
      return;
    }
    const params = new URLSearchParams({
      garmin_source_id: sourceId,
      x_metric_code: document.getElementById("x-metric-code").value,
      y_metric_code: document.getElementById("y-metric-code").value,
      start_date: document.getElementById("lag-start").value,
      end_date: document.getElementById("lag-end").value,
      lag_days: document.getElementById("lag-days").value,
    });
    fetchJson("/api/garmin/lagged-association?" + params.toString())
      .then(renderLagResult)
      .catch(function (err) {
        setHtml("lag-result", unavailable(err.message || "request_failed"));
      });
  }

  function fetchJson(url) {
    return fetch(url, { method: "GET", headers: { Accept: "application/json" } }).then(
      function (response) {
        return response.json().then(function (body) {
          if (!response.ok) {
            const message = (body && (body.message || body.code)) || "request_failed";
            const error = new Error(message);
            error.body = body;
            throw error;
          }
          return body;
        });
      }
    );
  }

  function populateActivities(activities) {
    const multi = document.getElementById("activity-ids");
    const reference = document.getElementById("reference-activity-id");
    if (!multi || !reference) return;
    multi.innerHTML = "";
    reference.innerHTML = "";
    (activities || []).forEach(function (activity, index) {
      const label =
        (activity.activity_type || "activity") +
        " · " +
        (activity.source_local_date || activity.local_wall_time || activity.measured_at_utc || "undated") +
        " · " +
        shortId(activity.record_id);
      const option = document.createElement("option");
      option.value = activity.record_id;
      option.textContent = label;
      if (index < 2) option.selected = true;
      multi.appendChild(option);
      const refOption = document.createElement("option");
      refOption.value = activity.record_id;
      refOption.textContent = label;
      if (index === 0) refOption.selected = true;
      reference.appendChild(refOption);
    });
    syncReferenceOptions();
  }

  function syncReferenceOptions() {
    const multi = document.getElementById("activity-ids");
    const reference = document.getElementById("reference-activity-id");
    if (!multi || !reference) return;
    const selected = new Set(
      Array.from(multi.selectedOptions).map(function (option) {
        return option.value;
      })
    );
    Array.from(reference.options).forEach(function (option) {
      option.disabled = selected.size > 0 && !selected.has(option.value);
    });
    if (reference.selectedOptions.length && reference.selectedOptions[0].disabled) {
      const firstEnabled = Array.from(reference.options).find(function (option) {
        return !option.disabled;
      });
      if (firstEnabled) reference.value = firstEnabled.value;
    }
  }

  function renderMetricWording() {
    const node = document.getElementById("metric-wording");
    const select = document.getElementById("metric-code");
    if (!node || !select) return;
    const code = select.value;
    const metrics = payload.scalar_metrics || [];
    const match = metrics.find(function (item) {
      return item.metric_code === code;
    });
    if (!match) {
      node.textContent = "";
      return;
    }
    node.textContent = match.presentation_wording || match.description || "";
  }

  function renderNoSeries(reason) {
    setHtml(
      "series-chart",
      '<p class="unavailable">unavailable</p><p class="muted">Reason: ' +
        escapeHtml(reason || "no_data") +
        ". Missing values are not shown as 0.</p>"
    );
    setHtml("series-summary", "");
    setHtml("series-coverage", "");
    setText("result-identity", "no series result");
  }

  function renderSeries(series) {
    // Presentation only: plot already-computed usable/zero points. No fills,
    // trends, percentiles, or z-scores are calculated in the browser.
    const points = series.points || [];
    const plottable = points.filter(function (point) {
      return point.status === "usable" || point.status === "zero";
    });
    const chart = document.getElementById("series-chart");
    if (!chart) return;
    if (!plottable.length) {
      chart.innerHTML =
        '<p class="unavailable">no usable/zero points</p><p class="muted">Coverage/status details remain below. Unavailable is not zero.</p>';
    } else {
      const width = Math.max(640, plottable.length * 28);
      const height = 260;
      const pad = 28;
      const xs = plottable.map(function (_point, index) {
        return index;
      });
      const ys = plottable.map(function (point) {
        return Number(point.value);
      });
      const minY = Math.min.apply(null, ys);
      const maxY = Math.max.apply(null, ys);
      const spanY = maxY - minY || 1;
      const circles = plottable
        .map(function (point, index) {
          const x = pad + (xs[index] / Math.max(plottable.length - 1, 1)) * (width - pad * 2);
          const y = height - pad - ((ys[index] - minY) / spanY) * (height - pad * 2);
          const title =
            (point.analytic_date || "undated") +
            " · status=" +
            point.status +
            " · value=" +
            String(point.value);
          return (
            '<circle cx="' +
            x.toFixed(1) +
            '" cy="' +
            y.toFixed(1) +
            '" r="4" fill="' +
            (point.status === "zero" ? "#1d4e89" : "#0f6d6a") +
            '"><title>' +
            escapeHtml(title) +
            "</title></circle>"
          );
        })
        .join("");
      chart.innerHTML =
        '<svg viewBox="0 0 ' +
        width +
        " " +
        height +
        '" width="100%" height="' +
        height +
        '" role="img" aria-label="Scalar series">' +
        '<rect x="0" y="0" width="' +
        width +
        '" height="' +
        height +
        '" fill="#fffdf8"></rect>' +
        circles +
        "</svg>";
    }

    const presentation = series.metric_presentation || {};
    const baseline = series.baseline || {};
    const percentile = series.personal_percentile || {};
    const trend = series.trend || {};
    const deviation = series.deviation || {};
    setHtml(
      "series-summary",
      "<ul>" +
        "<li>Metric: <strong>" +
        escapeHtml(presentation.display_name || (series.metric_definition || {}).metric_code || "") +
        "</strong>" +
        (presentation.provider_native ? ' <span class="status-chip">provider-native</span>' : "") +
        "</li>" +
        "<li>Unit: " +
        escapeHtml(String((series.metric_definition || {}).unit || "n/a")) +
        "</li>" +
        "<li>Baseline: " +
        formatAvailable(baseline, function () {
          return (
            "count=" +
            baseline.count +
            ", mean=" +
            fmt(baseline.mean) +
            ", median=" +
            fmt(baseline.median) +
            ", p10=" +
            fmt(baseline.p10) +
            ", p90=" +
            fmt(baseline.p90)
          );
        }) +
        "</li>" +
        "<li>Personal-window percentile: " +
        formatAvailable(percentile, function () {
          return fmt(percentile.value) + " (latest=" + fmt(percentile.latest_value) + ")";
        }) +
        "</li>" +
        "<li>Trend slope/day: " +
        formatAvailable(trend, function () {
          return fmt(trend.slope_per_day);
        }) +
        "</li>" +
        "<li>Personal baseline deviation: " +
        formatAvailable(deviation, function () {
          return (
            "robust_z=" +
            fmt(deviation.robust_z) +
            ", flag=" +
            String(deviation.personal_baseline_deviation)
          );
        }) +
        "</li>" +
        "</ul>"
    );

    const availability = series.availability || {};
    setHtml(
      "series-coverage",
      "<p><strong>Coverage</strong></p><ul>" +
        "<li>candidate=" +
        (availability.candidate_count ?? "unavailable") +
        ", usable=" +
        (availability.usable_count ?? "unavailable") +
        ", zero=" +
        (availability.zero_count ?? "unavailable") +
        ", missing=" +
        (availability.missing_count ?? "unavailable") +
        ", null=" +
        (availability.null_count ?? "unavailable") +
        ", invalid=" +
        (availability.invalid_count ?? "unavailable") +
        ", partial=" +
        (availability.partial_count ?? "unavailable") +
        ", not_computable=" +
        (availability.not_computable_count ?? "unavailable") +
        "</li>" +
        "<li>Point statuses: " +
        points
          .slice(0, 40)
          .map(function (point) {
            return (
              '<span class="status-chip ' +
              escapeHtml(point.status || "") +
              '">' +
              escapeHtml((point.analytic_date || "?") + ":" + (point.status || "unknown")) +
              (point.status === "zero" ? "=0" : point.value === null || point.value === undefined ? "" : "") +
              "</span>"
            );
          })
          .join(" ") +
        (points.length > 40 ? " …" : "") +
        "</li></ul>"
    );

    setText(
      "result-identity",
      (series.algorithm || "?") +
        " / " +
        (series.rule_version || "?") +
        " / " +
        (series.result_hash || "?")
    );
  }

  function renderActivityResult(body) {
    const sessions = body.sessions || [];
    const comparisons = body.comparisons || [];
    const coverage = body.coverage || {};
    const native = body.native_score_labels || state.nativeLabels || {};
    let html = "<p class=\"muted\">" + escapeHtml(body.wording || "") + "</p>";
    html +=
      "<p>algorithm <code>" +
      escapeHtml(body.algorithm || "") +
      "</code> · rule <code>" +
      escapeHtml(body.rule_version || "") +
      "</code> · hash <code>" +
      escapeHtml(body.result_hash || "") +
      "</code></p>";
    html +=
      "<p>Coverage: usable=" +
      (coverage.usable_count ?? "unavailable") +
      ", zero=" +
      (coverage.zero_count ?? "unavailable") +
      ", missing=" +
      (coverage.missing_count ?? "unavailable") +
      ", null=" +
      (coverage.null_count ?? "unavailable") +
      ", comparable_pairs=" +
      (coverage.comparable_pair_count ?? "unavailable") +
      ", not_comparable_pairs=" +
      (coverage.not_comparable_pair_count ?? "unavailable") +
      "</p>";
    html += "<h3>Sessions</h3><table class=\"garmin-table\"><thead><tr>" +
      "<th>Record</th><th>Type</th><th>Reference</th><th>Native scores</th></tr></thead><tbody>";
    sessions.forEach(function (session) {
      const scores = (session.metric_coverage || [])
        .filter(function (metric) {
          return metric.metric_code === "training_effect" || metric.metric_code === "acute_training_load";
        })
        .map(function (metric) {
          const label = native[metric.metric_code];
          return (
            escapeHtml((label && label.display_name) || metric.metric_code) +
            ": " +
            statusValue(metric.status, metric.value)
          );
        })
        .join("; ");
      html +=
        "<tr><td class=\"code\">" +
        escapeHtml(shortId(session.record_id)) +
        "</td><td>" +
        escapeHtml(session.activity_type || "unknown") +
        "</td><td>" +
        (session.is_reference ? "yes" : "no") +
        "</td><td>" +
        (scores || "n/a") +
        "</td></tr>";
    });
    html += "</tbody></table>";
    html += "<h3>Comparisons</h3>";
    comparisons.forEach(function (block) {
      html +=
        "<p>Compared <code>" +
        escapeHtml(shortId(block.compared_record_id)) +
        "</code> vs reference <code>" +
        escapeHtml(shortId(block.reference_record_id)) +
        "</code> · same_activity_type=" +
        String(block.same_activity_type) +
        "</p><table class=\"garmin-table\"><thead><tr>" +
        "<th>Metric</th><th>Status</th><th>Abs Δ</th><th>% Δ</th><th>Notes</th></tr></thead><tbody>";
      (block.metrics || []).forEach(function (metric) {
        const nativeLabel = native[metric.metric_code];
        html +=
          "<tr><td>" +
          escapeHtml((nativeLabel && nativeLabel.display_name) || metric.metric_code) +
          "</td><td><span class=\"status-chip " +
          escapeHtml(metric.status || "") +
          "\">" +
          escapeHtml(metric.status || "unknown") +
          "</span></td><td>" +
          (metric.absolute_delta === null || metric.absolute_delta === undefined
            ? "unavailable"
            : fmt(metric.absolute_delta)) +
          "</td><td>" +
          (metric.percent_delta === null || metric.percent_delta === undefined
            ? escapeHtml(metric.percent_status || "unavailable")
            : fmt(metric.percent_delta)) +
          "</td><td class=\"muted\">" +
          escapeHtml(metric.reason || "") +
          (metric.same_activity_type ? "" : " · different activity type") +
          "</td></tr>";
      });
      html += "</tbody></table>";
    });
    setHtml("activity-result", html);
    setText(
      "result-identity",
      (body.algorithm || "?") + " / " + (body.rule_version || "?") + " / " + (body.result_hash || "?")
    );
  }

  function renderLagResult(body) {
    let html = "<p class=\"muted\">" + escapeHtml(body.wording || "") + "</p>";
    html +=
      "<p>algorithm <code>" +
      escapeHtml(body.algorithm || "") +
      "</code> · rule <code>" +
      escapeHtml(body.rule_version || "") +
      "</code> · hash <code>" +
      escapeHtml(body.result_hash || "") +
      "</code></p>";
    html +=
      "<table class=\"garmin-table\"><thead><tr>" +
      "<th>Lag days</th><th>Status</th><th>Spearman rho</th><th>n</th><th>Coverage</th><th>Reason</th>" +
      "</tr></thead><tbody>";
    (body.lags || []).forEach(function (lag) {
      const coverage = lag.coverage || {};
      html +=
        "<tr><td>" +
        escapeHtml(String(lag.lag_days)) +
        "</td><td><span class=\"status-chip " +
        escapeHtml(lag.status || "") +
        "\">" +
        escapeHtml(lag.status || "unknown") +
        "</span></td><td>" +
        (lag.rho === null || lag.rho === undefined ? "unavailable" : fmt(lag.rho, 4)) +
        "</td><td>" +
        escapeHtml(String(lag.n)) +
        "</td><td class=\"muted\">paired=" +
        (coverage.paired_usable_count ?? "unavailable") +
        ", x=" +
        (coverage.candidate_x_count ?? "unavailable") +
        ", y=" +
        (coverage.candidate_y_count ?? "unavailable") +
        "</td><td class=\"muted\">" +
        escapeHtml(lag.reason || "") +
        "</td></tr>";
    });
    html += "</tbody></table>";
    html +=
      "<p class=\"muted\">No p-values, significance labels, best-lag ranking, or causal claims are presented.</p>";
    setHtml("lag-result", html);
    setText(
      "result-identity",
      (body.algorithm || "?") + " / " + (body.rule_version || "?") + " / " + (body.result_hash || "?")
    );
  }

  function formatAvailable(block, whenAvailable) {
    if (!block || !block.available) {
      return '<span class="unavailable">unavailable</span> (' + escapeHtml((block && block.reason) || "no_data") + ")";
    }
    return whenAvailable();
  }

  function statusValue(status, value) {
    if (status === "zero") return '<span class="status-chip zero">zero (0)</span>';
    if (status === "usable") return fmt(value);
    return '<span class="status-chip ' + escapeHtml(status || "") + '">' + escapeHtml(status || "unavailable") + "</span>";
  }

  function unavailable(reason) {
    return (
      '<p class="unavailable">unavailable</p><p class="muted">Reason: ' +
      escapeHtml(reason || "no_data") +
      "</p>"
    );
  }

  function fmt(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "unavailable";
    return Number(value).toFixed(digits === undefined ? 3 : digits);
  }

  function shortId(value) {
    const text = String(value || "");
    return text.length <= 12 ? text : text.slice(0, 8) + "…";
  }

  function setHtml(id, html) {
    const node = document.getElementById(id);
    if (node) node.innerHTML = html;
  }

  function setText(id, text) {
    const node = document.getElementById(id);
    if (node) node.textContent = text;
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();
