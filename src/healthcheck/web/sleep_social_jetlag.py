"""Two-night UI comparison over the accepted exact-source analysis inputs."""

from collections import Counter, defaultdict

from healthcheck.chat_evidence import _json
from healthcheck.saved_sleep_analysis import circular_local_clock


def _clock(minutes):
    rounded = round(minutes) % 1440
    return f"{rounded // 60:02d}:{rounded % 60:02d}"


def build_social_jetlag(inputs, settings, history=None):
    nights = inputs["nights"]
    exclusions = list(inputs["night_exclusions"])
    travel = {}
    previous_zone, previous_changed = None, False
    # Within-night changes are already excluded by the accepted reader, but
    # their following night must also be withheld from the comparison.
    prior = history or {"nights": [], "night_exclusions": []}
    sequence = sorted(prior["nights"] + nights + [dict(e, zone_change=True)
                               for e in prior["night_exclusions"] + exclusions
                               if e["reason"] == "within_night_timezone_change"],
                      key=lambda n: n["wake_date"])
    for night in sequence:
        if night.get("zone_change"):
            previous_changed, previous_zone = True, None
            continue
        zone = night["partition"]["local_clock_regime"]
        changed = previous_zone is not None and zone != previous_zone
        if changed or previous_changed:
            travel[night["record_id"]] = ("timezone_change" if changed else
                                          "night_after_timezone_change")
        previous_zone, previous_changed = zone, changed
    partitions = defaultdict(list)
    unknown = 0
    night_types = {}
    for night in nights:
        key = _json(night["partition"])
        partitions[key]  # Retain an insufficient row even if every night is excluded.
        kind = settings.day_type(night["wake_date"])
        reason = travel.get(night["record_id"])
        if reason is None and kind == "unknown":
            reason = "unknown_day_type"
            unknown += 1
        if reason:
            exclusions.append({"wake_date": night["wake_date"], "reason": reason})
        else:
            partitions[key].append((night, kind))
        night_types[night["wake_date"]] = {"day_type": "unknown" if reason else kind,
                                           "reason": reason}
    groups = []
    for key, rows in partitions.items():
        clocks = {kind: circular_local_clock(
            [n["midpoint"]["clock_minutes"] for n, k in rows if k == kind], min_nights=2)
            for kind in ("work", "free")}
        work, free = clocks["work"], clocks["free"]
        available = all(c["state"] == "sufficient" for c in clocks.values())
        signed = ((free["mean_clock_minutes"] - work["mean_clock_minutes"] + 720) % 1440
                  - 720) if available else None
        text = (f"Середина сна: рабочие дни {_clock(work['mean_clock_minutes'])} · "
                f"свободные {_clock(free['mean_clock_minutes'])} · сдвиг {signed:+.0f} мин "
                f"({work['n']} и {free['n']} ночи)") if available else (
                    f"Недостаточно ночей для сравнения (рабочих {work['n']}, "
                    f"свободных {free['n']})")
        if any(c["state"] == "undefined_direction" for c in clocks.values()):
            text = (f"Нет устойчивой середины сна для сравнения (рабочих {work['n']}, "
                    f"свободных {free['n']})")
        groups.append({"partition": next(n["partition"] for n in nights
                                         if _json(n["partition"]) == key),
                       "state": "sufficient" if available else "insufficient",
                       "groups": clocks, "signed_minutes": signed, "text": text})
    if not groups:
        groups.append({"partition": None, "state": "insufficient", "signed_minutes": None,
                       "groups": {k: circular_local_clock([], min_nights=2)
                                  for k in ("work", "free")},
                       "text": "Недостаточно ночей для сравнения (рабочих 0, свободных 0)"})
    counts = Counter(e["reason"] for e in exclusions)
    return {"groups": groups, "min_nights": 2, "unknown_nights": unknown,
            "night_types": night_types,
            "travel_history": "bounded_30_days" if history is not None else "unavailable",
            "travel_nights": sum(counts[r] for r in (
                "timezone_change", "night_after_timezone_change", "within_night_timezone_change")),
            "other_excluded_nights": len(inputs["night_exclusions"]) - counts[
                "within_night_timezone_change"],
            "exclusions": [{"reason": r, "count": n} for r, n in sorted(counts.items())]}
