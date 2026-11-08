// Optional Owner theme choice. Without JavaScript the theme follows the Windows setting.
(function () {
  "use strict";
  var KEY = "healthcheck-theme";
  var root = document.documentElement;
  function read() {
    try { return window.localStorage.getItem(KEY) || "system"; } catch (error) { return "system"; }
  }
  function apply(choice) {
    if (choice === "dark" || choice === "light") root.setAttribute("data-theme", choice);
    else root.removeAttribute("data-theme");
  }
  apply(read());
  document.addEventListener("DOMContentLoaded", function () {
    var box = document.querySelector("[data-owner-theme]");
    if (!box) return;
    var buttons = box.querySelectorAll("[data-theme-choice]");
    function sync(choice) {
      buttons.forEach(function (button) {
        button.setAttribute("aria-pressed", String(button.getAttribute("data-theme-choice") === choice));
      });
    }
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        var choice = button.getAttribute("data-theme-choice");
        try {
          if (choice === "system") window.localStorage.removeItem(KEY);
          else window.localStorage.setItem(KEY, choice);
        } catch (error) { /* storage unavailable: the choice lasts for this page only */ }
        apply(choice);
        sync(choice);
      });
    });
    sync(read());
    box.hidden = false;
  });
}());
