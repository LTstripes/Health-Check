/* The existing period indicator owns the shared scope description. */
(() => {
  "use strict";
  const indicator = document.querySelector(".brief-period[aria-describedby]");
  if (!indicator) return;
  const reveal = () => indicator.removeAttribute("data-tooltip-dismissed");
  indicator.addEventListener("focus", reveal);
  indicator.addEventListener("mouseenter", reveal);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && indicator.matches(":hover, :focus")) {
      indicator.setAttribute("data-tooltip-dismissed", "");
      event.preventDefault();
    }
  });
})();
