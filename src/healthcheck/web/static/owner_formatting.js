/* Display only. Exact values, quality, pairing and export remain unchanged. */
(function () {
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
    return sign + (hours ? hours + " ч " : "") + (minutes % 60) + " мин";
  }
  function endpoint(cell, session, code) {
    if (!cell || !cell.eligible) return "—";
    // Reject zone-less strings: Date must never use the browser's local timezone.
    const parse = value => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : NaN;
    // Date's millisecond precision must not turn distinct retained instants into proof.
    const key = value => typeof value === "string" ? value.replace(/\+00:00$/, "Z")
      .replace(/\.0+Z$/, "Z").replace(/(\.\d*?[1-9])0+Z$/, "$1Z") : null;
    const stamp = parse(cell.value);
    if (!Number.isFinite(stamp)) return "Время недоступно";
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
    const local = new Date(stamp + offset * 60000);
    const text = local.toLocaleDateString("ru-RU", {day: "numeric", month: "long", year: "numeric", timeZone: "UTC"}) + ", " +
      String(local.getUTCHours()).padStart(2, "0") + ":" + String(local.getUTCMinutes()).padStart(2, "0");
    const abs = Math.abs(offset);
    return text + (offset === 0 ? " UTC" : " UTC" + (offset < 0 ? "−" : "+") + String(Math.floor(abs / 60)).padStart(2, "0") + String(abs % 60).padStart(2, "0"));
  }
  window.healthcheckOwnerFormat = Object.freeze({duration, endpoint});
})();
