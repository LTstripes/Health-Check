/* Source-local civil date/time only; no browser-zone conversion. */
(function () {
  "use strict";
  window.healthcheckOwnerDate = function (value, sourcePrecision = false) {
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(:\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/.exec(String(value || ""));
    if (!match) return "Дата не указана";
    const months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
    const month = months[Number(match[2]) - 1];
    if (!month) return "Дата не указана";
    let text = Number(match[3]) + " " + month + " " + match[1];
    if (match[4]) text += ", " + match[4] + ":" + match[5];
    if (sourcePrecision && match[6]) text += match[6];
    if (match[7]) text += ["Z", "+00:00"].includes(match[7]) ? " UTC" : " UTC" + match[7];
    return text;
  };
})();
