/* Source-local civil date/time only; no browser-zone conversion. */
(function () {
  "use strict";
  window.healthcheckOwnerDate = function (value, sourcePrecision = false) {
    if (typeof value !== "string") return "Дата не указана";
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(:\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/.exec(value);
    if (!match) return "Дата не указана";
    // Validate the supplied civil fields, never Date's normalizing/zone-converting parser.
    const year = Number(match[1]), monthNumber = Number(match[2]), day = Number(match[3]);
    const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (year < 1 || monthNumber < 1 || monthNumber > 12 || day < 1 || day > daysInMonth[monthNumber - 1]) return "Дата не указана";
    if (match[4]) {
      const seconds = match[6] ? Number(match[6].slice(1, 3)) : 0;
      if (Number(match[4]) > 23 || Number(match[5]) > 59 || seconds > 59) return "Дата не указана";
      const offset = match[7];
      if (offset && offset !== "Z" && (Number(offset.slice(1, 3)) > 23 || Number(offset.slice(4, 6)) > 59)) return "Дата не указана";
    }
    const months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
    const month = months[monthNumber - 1];
    let text = day + " " + month + " " + match[1];
    if (match[4]) text += ", " + match[4] + ":" + match[5];
    if (sourcePrecision && match[6]) text += match[6];
    if (match[7]) text += ["Z", "+00:00"].includes(match[7]) ? " UTC" : " UTC" + match[7];
    return text;
  };
})();
