"""Owner-declared wake-day classification in the existing profile config.toml.

No Context text/tag inference, database migration, or provider operation.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256

from healthcheck.config import Settings
from healthcheck.external_runtime_lock import ExternalRuntimeOperationLock
from healthcheck.runtime import resolve_runtime_paths

MAX_CONFIG_BYTES = 256 * 1024
MAX_OVERRIDES = 3660
_TABLE = re.compile(r"(?m)^\s*\[sleep_schedule\]\s*(?:#.*)?$")
_NEXT_TABLE = re.compile(r"(?m)^\s*\[")


@dataclass(frozen=True)
class SleepScheduleSettings:
    work_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    overrides: dict[str, str] = field(default_factory=dict)
    state: str = "available"
    revision: str = ""

    def day_type(self, wake_date: str) -> str:
        if self.state != "available":
            return "unknown"
        return self.overrides.get(wake_date, "work" if date.fromisoformat(
            wake_date).weekday() in self.work_weekdays else "free")


def _validate(weekdays, overrides):
    if (not isinstance(weekdays, (list, tuple)) or len(weekdays) > 7
            or any(type(d) is not int or not 0 <= d <= 6 for d in weekdays)
            or len(set(weekdays)) != len(weekdays)
            or not isinstance(overrides, dict) or len(overrides) > MAX_OVERRIDES):
        raise ValueError("invalid_sleep_schedule_settings")
    for day, kind in overrides.items():
        if (not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
                or kind not in {"work", "free"}):
            raise ValueError("invalid_sleep_day_override")


def _read(settings):
    path = resolve_runtime_paths(settings).config
    if path.is_symlink() or path.stat().st_nlink != 1:
        raise ValueError("unsafe_config")
    with path.open("rb") as handle:
        raw = handle.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("config_too_large")
    text = raw.decode("utf-8")
    document = tomllib.loads(text)
    section = document.get("sleep_schedule", {})
    if not isinstance(section, dict) or set(section) - {"work_weekdays", "overrides"}:
        raise ValueError("invalid_sleep_schedule_settings")
    weekdays = section.get("work_weekdays", [0, 1, 2, 3, 4])
    overrides = section.get("overrides", {})
    _validate(weekdays, overrides)
    return text, document, SleepScheduleSettings(
        tuple(weekdays), overrides, revision=sha256(raw).hexdigest())


def read_sleep_schedule_settings(settings: Settings) -> SleepScheduleSettings:
    try:
        return _read(settings)[2]
    except (OSError, ValueError, TypeError):
        # Unreadable/malformed configuration is not the default working week.
        return SleepScheduleSettings(state="unavailable")


def update_sleep_schedule_settings(
    settings: Settings, *, revision: str, work_weekdays: list[int] | None = None,
    override_date: str | None = None, day_type: str | None = None,
) -> None:
    paths = resolve_runtime_paths(settings)
    with ExternalRuntimeOperationLock(paths):
        text, document, current = _read(settings)
        if revision != current.revision:
            raise ValueError("sleep_settings_changed_reload")
        weekdays = current.work_weekdays if work_weekdays is None else work_weekdays
        overrides = dict(current.overrides)
        if override_date is not None:
            if date.fromisoformat(override_date).isoformat() != override_date:
                raise ValueError("invalid_sleep_day_override")
            if day_type == "default":
                overrides.pop(override_date, None)
            else:
                overrides[override_date] = day_type
        _validate(weekdays, overrides)
        section = {"work_weekdays": list(weekdays), "overrides": overrides}
        block = "[sleep_schedule]\nwork_weekdays = " + json.dumps(list(weekdays)) + "\n"
        block += "overrides = {" + ", ".join(
            json.dumps(day) + " = " + json.dumps(kind)
            for day, kind in sorted(overrides.items())) + "}\n"
        match = _TABLE.search(text)
        if match:
            following = _NEXT_TABLE.search(text, match.end())
            stop = following.start() if following else len(text)
            updated = text[:match.start()] + block + "\n" + text[stop:]
        else:
            updated = text.rstrip() + "\n\n" + block
        # Refuse nonstandard table layouts rather than losing other settings.
        document["sleep_schedule"] = section
        if tomllib.loads(updated) != document or len(updated.encode()) > MAX_CONFIG_BYTES:
            raise ValueError("unsupported_config_layout")
        descriptor, temporary = tempfile.mkstemp(prefix=".sleep-config-", dir=paths.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, paths.config)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
