"""Pure facts-first presentation of an already frozen weekly packet."""

from __future__ import annotations

from healthcheck.weekly_digest import _activity, _sleep, _steps, _weight


def weekly_preview_presentation(packet: dict) -> dict[str, list[str]]:
    """Reuse accepted renderer guards and wording without reading or changing evidence."""
    sections = packet["evidence"]["sections"]
    facts: list[str] = []
    gaps: list[str] = []
    weight = sections.get("weight")
    if weight is not None:
        (facts if weight["daily_series"]["rows"] else gaps).append(_weight(weight))
    count = sections["activity"]["providers"]["garmin"]["metrics"]["activity_session_count"]
    if count["aggregation"]["value"] is not None and count["search"]["complete"]:
        facts.append(_activity(sections["activity"]))
    else:
        gaps.append("Занятия Garmin: надёжного количества записей нет.")

    for key, label in (("steps", "Garmin"), ("google_steps", "Google")):
        section = sections.get(key)
        if section is not None and any(
            cell["state"] in {"value", "zero"} and cell["value"] is not None
            for cell in section["cells"]
        ):
            facts.append(_steps(section, label))
        else:
            gaps.append(f"Шаги {label}: " + (
                "источник не выбран." if section is None else "пригодных наблюдений нет."))

    for provider, item in sections["sleep"]["providers"].items():
        label = "Garmin" if provider == "garmin" else "Google"
        window = item["source_range"]
        if window and any(
            point["state"] == "value" and point["value"] is not None
            and not point["role_uncertain"]
            for series in window["series"] for point in series["points"]
        ):
            # Existing renderer retains source separation, wake dates and duration wording.
            facts.append(_sleep({"providers": {provider: item}}).removesuffix(
                " Дневной сон и записи с неопределённой ролью не добавляются к основному."))
        else:
            gaps.append(f"Сон {label}: пригодной длительности основного сна нет.")

    paragraphs = packet["text"].split("\n\n")
    notices = [paragraphs[0]]
    if gaps:
        notices.append("Пропуски и исключённые записи — не ноль "
                       "и не отсутствие активности или сна.")
    notices.append(paragraphs[-1])
    return {"facts": facts, "gaps": gaps, "notices": notices}
