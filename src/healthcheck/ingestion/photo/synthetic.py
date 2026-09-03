"""Synthetic PNG fixtures with structured extraction payloads.

Images are generated at runtime.  They are never real screenshots and must
not be committed to Git.
"""

from __future__ import annotations

import json
import struct
import zlib
from datetime import date, timedelta
from typing import Any

SYNTHETIC_TEXT_KEY = "healthcheck"


def _chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def encode_synthetic_png(payload: dict[str, Any], *, width: int = 8, height: int = 8) -> bytes:
    """Encode a tiny RGB PNG whose tEXt chunk carries the extraction payload."""

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    digest = zlib.crc32(json.dumps(payload, sort_keys=True).encode("utf-8")) & 0xFFFFFFFF
    rows = bytearray()
    for row in range(height):
        rows.append(0)
        for column in range(width):
            rows.extend(
                (
                    (digest + row * 13 + column) & 0xFF,
                    (digest >> 8) & 0xFF,
                    (digest >> 16) & 0xFF,
                )
            )
    text = (
        SYNTHETIC_TEXT_KEY.encode("latin-1")
        + b"\x00"
        + json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    return signature + b"".join(
        (
            _chunk(b"IHDR", ihdr),
            _chunk(b"tEXt", text),
            _chunk(b"IDAT", zlib.compress(bytes(rows), 9)),
            _chunk(b"IEND", b""),
        )
    )


def read_png_text_chunks(image_bytes: bytes) -> dict[str, str]:
    if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return {}
    offset = 8
    values: dict[str, str] = {}
    length = len(image_bytes)
    while offset + 12 <= length:
        chunk_length = int.from_bytes(image_bytes[offset : offset + 4], "big")
        tag = image_bytes[offset + 4 : offset + 8]
        start = offset + 8
        end = start + chunk_length
        if end + 4 > length:
            break
        data = image_bytes[start:end]
        offset = end + 4
        if tag == b"IEND":
            break
        if tag == b"tEXt":
            key, separator, value = data.partition(b"\x00")
            if separator:
                values[key.decode("latin-1")] = value.decode("utf-8")
    return values


def decode_synthetic_payload(image_bytes: bytes) -> dict[str, Any] | None:
    raw = read_png_text_chunks(image_bytes).get(SYNTHETIC_TEXT_KEY)
    if raw is None:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("synthetic photo payload must be an object")
    return parsed


def weigh_in_payload(
    *,
    source_local_date: date,
    weight_kg: float,
    body_fat_pct: float | None = None,
    muscle_mass_kg: float | None = None,
    weight_confidence: float | None = None,
    body_fat_confidence: float | None = None,
    provider_code: str = "xiaomi_home",
    source_application: str = "Xiaomi Home",
    source_application_version: str | None = None,
    physical_device_code: str = "xiaomi_s400",
    extra_fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {
            "metric_code": "weight",
            "value": weight_kg,
            "unit": "kg",
            "source_text": f"{weight_kg} kg",
            "confidence": weight_confidence,
        }
    ]
    if body_fat_pct is not None:
        fields.append(
            {
                "metric_code": "body_fat_pct",
                "value": body_fat_pct,
                "unit": "%",
                "source_text": f"{body_fat_pct} %",
                "confidence": body_fat_confidence,
            }
        )
    if muscle_mass_kg is not None:
        fields.append(
            {
                "metric_code": "muscle_mass",
                "value": muscle_mass_kg,
                "unit": "kg",
                "source_text": f"{muscle_mass_kg} kg",
                "confidence": None,
            }
        )
    if extra_fields:
        fields.extend(extra_fields)
    return {
        "schema_version": "r01-photo-v1",
        "provider_code": provider_code,
        "source_application": source_application,
        "source_application_version": source_application_version,
        "physical_device_code": physical_device_code,
        "groups": [
            {
                "key": "weigh-in",
                "source_local_date": source_local_date.isoformat(),
                "temporal_precision": "date",
                "fields": fields,
            }
        ],
    }


def six_month_synthetic_batch(
    *,
    start: date = date(2026, 1, 7),
    count: int = 26,
) -> list[tuple[str, bytes, dict[str, Any]]]:
    """Return 26 weekly synthetic images covering about six months."""

    batch: list[tuple[str, bytes, dict[str, Any]]] = []
    for index in range(count):
        observed = start + timedelta(days=7 * index)
        # Even weeks keep confidence absent; odd weeks report a varying model
        # score.  None of these values is a hidden default applied by code.
        weight_confidence = None if index % 2 == 0 else round(0.41 + (index % 4) * 0.11, 2)
        body_fat_confidence = None if index % 3 == 0 else round(0.37 + (index % 5) * 0.08, 2)
        payload = weigh_in_payload(
            source_local_date=observed,
            weight_kg=round(80.0 - index * 0.15, 2),
            body_fat_pct=round(24.0 - index * 0.05, 2),
            muscle_mass_kg=round(32.0 + index * 0.02, 2) if index % 4 == 0 else None,
            weight_confidence=weight_confidence,
            body_fat_confidence=body_fat_confidence,
        )
        filename = f"synthetic-week-{index + 1:02d}.png"
        batch.append((filename, encode_synthetic_png(payload), payload))
    return batch
