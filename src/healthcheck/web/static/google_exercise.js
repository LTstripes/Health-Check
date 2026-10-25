"use strict";

// History navigation may restore unsubmitted edits over server-rendered results.
// Restore only Google's forms to the filters that produced those results.
window.addEventListener("pageshow", () => {
  document.getElementById("google-exercise")?.querySelectorAll("form").forEach(form => {
    form.reset();
  });
});
