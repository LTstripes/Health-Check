/* Reuse T6 for every already-read source session, without selecting or fetching. */
(function () {
  "use strict";
  const packet = document.getElementById("sleep-source-night-data");
  if (!packet || !window.healthcheckSleepNightCard) return;
  let data;
  try { data = JSON.parse(packet.textContent); } catch (_) { return; }
  document.querySelectorAll("[data-source-night-card]").forEach(function (host, index) {
    const source = (data && data.sources || [])[Number(host.dataset.sourceIndex)];
    const session = source && source.sessions[Number(host.dataset.sessionIndex)];
    if (!session) return;
    const series = {provider: host.dataset.provider, label: host.dataset.sourceLabel};
    const duration = session.metrics.sleep_duration_asleep_seconds;
    const point = {wake_date: session.wake_date, state: duration.eligible ? "value" : "unavailable",
      value_seconds: duration.eligible ? duration.value : null};
    const card = window.healthcheckSleepNightCard;
    // Keep the single server-rendered empty state when every metric is withheld.
    if (!Object.values(session.metrics).some(cell => cell.eligible)) return;
    // A page may contain several cards: SVG/heading IDs must remain local to each.
    host.innerHTML = '<div class="night-card">' + (card.head(series, point) + card.session(series, session))
      .replaceAll("night-card-stages-title", "source-night-stages-" + index)
      .replaceAll('id="night-hypno-hatch"', 'id="source-night-hatch-' + index + '"')
      .replaceAll("url(#night-hypno-hatch)", "url(#source-night-hatch-" + index + ")") + '</div>';
  });
})();
