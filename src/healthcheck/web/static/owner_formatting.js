/* Display only. Exact values, quality, pairing and export remain unchanged. */
(function () {
  function number(value, digits = 1, signed = false) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "Не предоставлено";
    const rounded = value.toFixed(digits);
    let text = rounded.includes(".") ? rounded.replace(/0+$/, "").replace(/\.$/, "") : rounded;
    if (Number(text) === 0) text = "0";
    const parts = text.split(".");
    if (!/[eE]/.test(text)) parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, "\u202f");
    text = parts.join(",").replace("-", "−");
    return signed && value > 0 && text !== "0" ? "+" + text : text;
  }
  function plural(n, one, few, many) {
    if (typeof n !== "number" || !Number.isFinite(n)) return many;
    n = Math.abs(n);
    if (!Number.isInteger(n)) return few;
    return n % 100 >= 11 && n % 100 <= 14 ? many : n % 10 === 1 ? one : n % 10 >= 2 && n % 10 <= 4 ? few : many;
  }
  function duration(value, signed = false) {
    if (typeof value !== "number" || !Number.isFinite(value) || (!signed && value < 0)) return "Недоступно";
    const seconds = Math.abs(value), sign = value < 0 ? "−" : signed && value > 0 ? "+" : "";
    if (seconds >= 3.6e12) {
      const [coefficient, exponent] = (seconds / 3600).toExponential(2).split("e");
      return sign + "≈" + coefficient.replace(/\.?0+$/, "").replace(".", ",") + " × 10^" + Number(exponent) + " ч";
    }
    if (seconds > 0 && seconds < 60) return sign + "<1 мин";
    const minutes = Math.floor(seconds / 60 + 0.5);
    const hours = Math.floor(minutes / 60);
    return sign + (hours ? hours + " ч " + String(minutes % 60).padStart(2, "0") : minutes % 60) + " мин";
  }
  // Source-local instant of a session endpoint: one exactly paired offset, else UTC.
  function endpointLocal(cell, session, code) {
    if (!cell || !cell.eligible) return null;
    // Reject zone-less strings: Date must never use the browser's local timezone.
    const parse = value => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : NaN;
    // Date's millisecond precision must not turn distinct retained instants into proof.
    const key = value => typeof value === "string" ? value.replace(/\+00:00$/, "Z")
      .replace(/\.0+Z$/, "Z").replace(/(\.\d*?[1-9])0+Z$/, "$1Z") : null;
    const stamp = parse(cell.value);
    if (!Number.isFinite(stamp)) return {valid: false};
    const side = {sleep_start_at: "start", sleep_end_at: "end"}[code];
    const offsets = new Set();
    if (side) [cell, ...Object.values(session.metrics || {})].forEach(item => {
      const evidence = item.evidence || {}, candidates = [];
      const record = session.temporal_evidence || {};
      if (side === "start") candidates.push({precision: record.precision,
        measured_at_utc: record.source_timestamp_utc, source_utc_offset_minutes: record.source_utc_offset_minutes});
      candidates.push(((evidence.quality_inputs || {}).summary_boundary || {})[side]);
      (evidence.interval_snapshots || []).forEach(snapshot => {
        if (snapshot[side + "_precision"] === "instant") candidates.push(snapshot[side + "_temporal"]);
      });
      candidates.forEach(temporal => {
        if (!temporal || temporal.precision !== "instant") return;
        const offset = temporal.source_utc_offset_minutes;
        if (typeof offset === "number" && Number.isInteger(offset) && Math.abs(offset) <= 1439 &&
            parse(temporal.measured_at_utc) === stamp && key(temporal.measured_at_utc) === key(cell.value)) offsets.add(offset);
      });
    });
    const offset = offsets.size === 1 ? [...offsets][0] : 0;
    return {valid: true, offset, local: new Date(stamp + offset * 60000)};
  }
  const pad = value => String(value).padStart(2, "0");
  function zone(offset) {
    const abs = Math.abs(offset);
    return offset === 0 ? " UTC" : " UTC" + (offset < 0 ? "−" : "+") + pad(Math.floor(abs / 60)) + pad(abs % 60);
  }
  function endpoint(cell, session, code) {
    const parts = endpointLocal(cell, session, code);
    if (!parts) return "—";
    if (!parts.valid) return "Время недоступно";
    const {local, offset} = parts;
    const text = local.toLocaleDateString("ru-RU", {day: "numeric", month: "long", year: "numeric", timeZone: "UTC"}) + ", " +
      pad(local.getUTCHours()) + ":" + pad(local.getUTCMinutes());
    return text + zone(offset);
  }
  // Short clock for the main view; a UTC fallback keeps its explicit zone.
  function clock(cell, session, code) {
    const parts = endpointLocal(cell, session, code);
    if (!parts || !parts.valid) return null;
    const time = pad(parts.local.getUTCHours()) + ":" + pad(parts.local.getUTCMinutes());
    return {text: time + (parts.offset === 180 ? "" : zone(parts.offset)), day: parts.local.toISOString().slice(0, 10)};
  }
  window.healthcheckOwnerFormat = Object.freeze({number, plural, duration, endpoint, clock});
})();
