"""Read-only, literal lab history projections; no clinical interpretation."""

from __future__ import annotations

import unicodedata
from collections import defaultdict

from healthcheck.labs.schema import sha


def normalized_name(value: str) -> str:
    value = " ".join(value.casefold().split())
    while value and unicodedata.category(value[-1]).startswith("P"):
        value = value[:-1].rstrip()
    return value


def analyte_key(name: str) -> str:
    return "analyte-" + sha(normalized_name(name).encode("utf-8"))[:24]


def unit_key(value: str | None) -> str | None:
    # Punctuation can be meaningful in a unit. Missing is distinct from blank.
    return " ".join(value.casefold().split()) if value is not None else None


def history_date(value: dict | None) -> str:
    if not value:
        return "Не указана"
    raw = value["value"]
    date = f"{raw[8:10]}.{raw[5:7]}.{raw[:4]}"
    return date if value["precision"] == "date" else date + " " + raw[11:]


def histories(reports: list[dict], drafts: list[dict]) -> list[dict]:
    """Use current accepted snapshots only; never merge units or synonyms."""
    by_name = {}
    for report in reports:
        snapshot = report["snapshot"]
        date = snapshot["result_date"] or snapshot["printed_date"]
        for row in snapshot["rows"]:
            key = analyte_key(row["label_raw"])
            item = by_name.setdefault(key, {"key": key, "rows": [], "draft_count": 0})
            item["rows"].append({
                "row": row, "report": report, "date": date,
                "date_text": history_date(date),
                "date_kind": "result" if snapshot["result_date"] else "printed",
                "sort_date": date["value"] if date else "",
            })
    for draft in drafts:
        for row in draft["rows"]:
            key = analyte_key(row["label_raw"])
            item = by_name.setdefault(key, {
                "key": key, "name": row["label_raw"], "rows": [], "draft_count": 0,
            })
            item["draft_count"] += 1
    for item in by_name.values():
        # Local printed clocks are kept literal; no timezone or time is inferred.
        item["rows"].sort(key=lambda r: r["sort_date"], reverse=True)
        groups = defaultdict(list)
        for entry in item["rows"]:
            groups[unit_key(entry["row"]["unit_raw"])].append(entry)
        item["groups"] = [
            {"unit": entries[0]["row"]["unit_raw"], "rows": entries}
            for entries in groups.values()
        ]
        dated = [r for r in item["rows"] if r["date"]]
        item["count"] = len(item["rows"])
        item["first_date"] = history_date(dated[-1]["date"]).split(" ")[0] if dated else None
        item["last_date"] = history_date(dated[0]["date"]).split(" ")[0] if dated else None
        item["undated_count"] = item["count"] - len(dated)
        item["printed_count"] = sum(r["date_kind"] == "printed" for r in dated)
        if item["rows"]:
            item["latest"] = item["rows"][0]
            item["name"] = item["latest"]["row"]["label_raw"]
    return sorted(by_name.values(), key=lambda i: normalized_name(i["name"]))
