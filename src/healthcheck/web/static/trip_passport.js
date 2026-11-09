"use strict";
(() => {
  const event = document.querySelector('.passport-fields [name="event_id"]');
  if (event) event.addEventListener("change", () => {
    // Switching the event must not retain dates/title from the previous event.
    for (const name of ["start_date", "end_date", "title"]) event.form.elements[name].value = "";
  });
  const payload = document.getElementById("passport-downloads");
  if (!payload) return;
  const downloads = JSON.parse(payload.textContent);
  const urls = [];
  for (const [kind, media] of [["json", "application/json"], ["md", "text/markdown"]]) {
    const link = document.getElementById(`passport-download-${kind}`);
    const url = URL.createObjectURL(new Blob([downloads[kind]], {type: `${media};charset=utf-8`}));
    urls.push(url);
    link.href = url;
    link.download = `${downloads.filename}.${kind}`;
    link.hidden = false;
  }
  window.addEventListener("pagehide", (event) => {
    if (!event.persisted) urls.forEach((url) => URL.revokeObjectURL(url));
  });
})();
