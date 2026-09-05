"""Configured, provider-neutral vision extraction for real photo imports.

The adapter speaks the small OpenAI-compatible chat-completions surface needed
for one image and a strict JSON response.  It deliberately owns no persistence
and accepts bytes only through the existing extractor port, so the photo
service remains responsible for immutable storage, replay and confirmation.
"""

from __future__ import annotations

import base64
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from healthcheck.ingestion.photo.extractor import (
    CandidateField,
    ExtractionFailure,
    ExtractionRequest,
    ExtractionResult,
    MeasurementGroup,
)

VISION_EXTRACTOR_NAME = "healthcheck-openai-compatible-vision"
VISION_EXTRACTOR_VERSION = "1"
VISION_PROMPT_VERSION = "r01-xiaomi-s400-v1"
VISION_RESPONSE_SCHEMA_NAME = "healthcheck_photo_extraction"
MAX_PROVIDER_RESPONSE_BYTES = 512 * 1024
_ALLOWED_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_ALLOWED_PRECISIONS = frozenset({"date", "instant", "minute"})
_KG_METRICS = frozenset({"weight", "muscle_mass", "bone_mass"})
_PERCENT_METRICS = frozenset({"body_fat_pct", "water_pct", "bone_pct"})
_KG_UNITS = frozenset({"kg", "kilogram", "kilograms", "lb", "lbs", "pound", "pounds"})
_PERCENT_UNITS = frozenset({"%", "percent", "pct", "pp"})
_ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "provider_code",
        "physical_device_code",
        "source_application",
        "source_application_version",
        "source_timezone",
        "source_utc_offset_minutes",
        "groups",
    }
)
_REQUIRED_TOP_LEVEL_KEYS = _ALLOWED_TOP_LEVEL_KEYS
_ALLOWED_GROUP_KEYS = frozenset(
    {"key", "source_local_date", "source_timestamp", "temporal_precision", "fields"}
)
_REQUIRED_GROUP_KEYS = _ALLOWED_GROUP_KEYS
_ALLOWED_FIELD_KEYS = frozenset(
    {
        "metric_code",
        "value",
        "unit",
        "source_text",
        "confidence",
        "source_local_date",
        "source_timestamp",
        "temporal_precision",
        "evidence_region",
        "algorithm_code",
        "algorithm_version",
    }
)
_REQUIRED_FIELD_KEYS = _ALLOWED_FIELD_KEYS


@dataclass(frozen=True, slots=True)
class VisionHttpResponse:
    """The bounded, non-logging result of one provider HTTP request."""

    status_code: int
    body: bytes
    content_type: str | None = None


VisionHttpTransport = Callable[
    [str, Mapping[str, str], bytes, float], VisionHttpResponse
]


class UnconfiguredImageMeasurementExtractor:
    """Typed fail-closed extractor used when no real provider is configured."""

    name = VISION_EXTRACTOR_NAME
    version = "unconfigured"
    model_name = None
    model_version = None
    prompt_version = VISION_PROMPT_VERSION
    configured_provider_code = None
    configured_physical_device_code = None

    def extract(self, request: ExtractionRequest, image_bytes: bytes) -> ExtractionResult:
        del request, image_bytes
        raise ExtractionFailure(
            "extractor_not_configured",
            "real photo vision extractor is not configured",
        )

    def with_version(self, version: str) -> UnconfiguredImageMeasurementExtractor:
        del version
        return self


class OpenAICompatibleVisionExtractor:
    """Extract structured Xiaomi photo candidates through one configured endpoint."""

    name = VISION_EXTRACTOR_NAME
    prompt_version = VISION_PROMPT_VERSION

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        api_key: str | None = None,
        timeout_seconds: float = 45.0,
        transport: VisionHttpTransport | None = None,
        extractor_version: str = VISION_EXTRACTOR_VERSION,
        configured_provider_code: str | None = None,
        configured_physical_device_code: str | None = None,
        configured_source_application: str | None = None,
        configured_source_application_version: str | None = None,
    ):
        self.base_url = _validated_base_url(base_url)
        self.model_name = _required_text(model_name, "vision model")
        self.api_key = _optional_text(api_key)
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("vision timeout must be between 0 and 300 seconds")
        self.timeout_seconds = timeout_seconds
        self.version = _required_text(extractor_version, "extractor version")
        self.model_version = None
        self.configured_provider_code = _optional_text(configured_provider_code)
        self.configured_physical_device_code = _optional_text(configured_physical_device_code)
        self.configured_source_application = _optional_text(configured_source_application)
        self.configured_source_application_version = _optional_text(
            configured_source_application_version
        )
        self._transport = transport or _default_transport

    def with_version(self, version: str) -> OpenAICompatibleVisionExtractor:
        """Create an explicitly versioned reprocessing adapter without changing config."""

        return OpenAICompatibleVisionExtractor(
            base_url=self.base_url,
            model_name=self.model_name,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
            transport=self._transport,
            extractor_version=version,
            configured_provider_code=self.configured_provider_code,
            configured_physical_device_code=self.configured_physical_device_code,
            configured_source_application=self.configured_source_application,
            configured_source_application_version=self.configured_source_application_version,
        )

    def extract(self, request: ExtractionRequest, image_bytes: bytes) -> ExtractionResult:
        if request.media_type not in _ALLOWED_MEDIA_TYPES:
            raise ExtractionFailure(
                "extractor_invalid_request", "real photo media type is not supported"
            )
        if not image_bytes:
            raise ExtractionFailure("extractor_invalid_request", "real photo is empty")

        request_body = _request_body(request, image_bytes, model_name=self.model_name)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self._transport(
                _chat_completions_url(self.base_url),
                headers,
                request_body,
                self.timeout_seconds,
            )
        except ExtractionFailure:
            raise
        except Exception:
            raise ExtractionFailure(
                "extractor_network_error", "vision provider network request failed"
            ) from None

        if (
            not isinstance(response, VisionHttpResponse)
            or isinstance(response.status_code, bool)
            or not isinstance(response.status_code, int)
            or not isinstance(response.body, bytes)
        ):
            raise ExtractionFailure(
                "extractor_malformed_response", "vision provider response is malformed"
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ExtractionFailure(
                "extractor_provider_error", "vision provider returned an error"
            )
        if len(response.body) > MAX_PROVIDER_RESPONSE_BYTES:
            raise ExtractionFailure(
                "extractor_malformed_response", "vision provider response is too large"
            )

        try:
            envelope = json.loads(response.body.decode("utf-8"))
            structured, provider_model = _structured_content(envelope)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise ExtractionFailure(
                "extractor_malformed_response",
                "vision provider returned malformed structured response",
            ) from None

        try:
            result_request = ExtractionRequest(
                artifact_id=request.artifact_id,
                content_hash=request.content_hash,
                media_type=request.media_type,
                locale=request.locale,
                timezone=request.timezone,
                schema_version=request.schema_version,
                provider_code=request.provider_code or self.configured_provider_code,
                physical_device_code=(
                    request.physical_device_code or self.configured_physical_device_code
                ),
                source_application=(
                    request.source_application or self.configured_source_application
                ),
                source_application_version=(
                    request.source_application_version
                    or self.configured_source_application_version
                ),
                source_utc_offset_minutes=request.source_utc_offset_minutes,
            )
            return _result_from_payload(
                structured,
                result_request,
                extractor_name=self.name,
                extractor_version=self.version,
                model_name=self.model_name,
                model_version=provider_model,
                prompt_version=self.prompt_version,
            )
        except ExtractionFailure:
            raise
        except (TypeError, ValueError, KeyError):
            raise ExtractionFailure(
                "extractor_invalid_payload",
                "vision provider response failed schema validation",
            ) from None


def build_photo_extractor(
    settings: Any,
) -> OpenAICompatibleVisionExtractor | UnconfiguredImageMeasurementExtractor:
    """Build the production extractor from settings without making a network call."""

    base_url = _optional_text(getattr(settings, "photo_vision_base_url", None))
    model_name = _optional_text(getattr(settings, "photo_vision_model", None))
    secret = getattr(settings, "photo_vision_api_key", None)
    api_key = secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
    timeout_seconds = float(getattr(settings, "photo_vision_timeout_seconds", 45.0))
    configured_provider_code = _optional_text(
        getattr(settings, "photo_vision_provider_code", None)
    )
    configured_physical_device_code = _optional_text(
        getattr(settings, "photo_vision_physical_device_code", None)
    )
    configured_source_application = _optional_text(
        getattr(settings, "photo_vision_source_application", None)
    )
    configured_source_application_version = _optional_text(
        getattr(settings, "photo_vision_source_application_version", None)
    )
    if base_url is None or model_name is None:
        return UnconfiguredImageMeasurementExtractor()
    try:
        return OpenAICompatibleVisionExtractor(
            base_url=base_url,
            model_name=model_name,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            configured_provider_code=configured_provider_code,
            configured_physical_device_code=configured_physical_device_code,
            configured_source_application=configured_source_application,
            configured_source_application_version=configured_source_application_version,
        )
    except (TypeError, ValueError):
        return UnconfiguredImageMeasurementExtractor()


def _default_transport(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> VisionHttpResponse:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return VisionHttpResponse(
                status_code=int(response.getcode()),
                body=response.read(MAX_PROVIDER_RESPONSE_BYTES + 1),
                content_type=response.headers.get("Content-Type"),
            )
    except urllib.error.HTTPError as exc:
        # The body is intentionally not read: provider diagnostics can contain
        # prompts, values or credentials.  The caller receives only a code.
        exc.close()
        return VisionHttpResponse(status_code=int(exc.code), body=b"")


def _validated_base_url(value: str) -> str:
    text = _required_text(value, "vision base URL").rstrip("/")
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("vision base URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("vision base URL must not contain credentials or query data")
    return text


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url}/chat/completions"


def _request_body(request: ExtractionRequest, image_bytes: bytes, *, model_name: str) -> bytes:
    image_data = base64.b64encode(image_bytes).decode("ascii")
    declared_profile = {
        "provider_code": request.provider_code,
        "physical_device_code": request.physical_device_code,
        "source_application": request.source_application,
        "source_application_version": request.source_application_version,
    }
    user_text = (
        "Extract only measurement values and source evidence visibly present in this image. "
        "This is a Xiaomi S400 weight/body-composition screenshot review. "
        "Do not infer a metric that is absent, do not calculate a missing metric, and do not "
        "guess app/build/formula/version. Return null for identity or confidence that is not "
        "evidenced. For date-only evidence return a date and temporal_precision=date with a "
        "null timestamp; never create midnight UTC. For instant/minute timestamps include an "
        "explicit timezone offset or Z. The declared import profile is only a hint and must "
        "not override visible evidence: "
        f"{json.dumps(declared_profile, sort_keys=True)}. "
        f"Locale hint={request.locale or 'unknown'}; timezone hint={request.timezone or 'unknown'}."
    )
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a bounded extraction adapter. Respond with JSON matching the "
                    "provided schema and no prose or markdown. Preserve source evidence "
                    "exactly; confidence is nullable and never a default."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{request.media_type};base64,{image_data}"
                        },
                    },
                ],
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": VISION_RESPONSE_SCHEMA_NAME,
                "strict": True,
                "schema": _response_schema(),
            },
        },
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _response_schema() -> dict[str, Any]:
    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    nullable_integer = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    nullable_precision = {
        "anyOf": [
            {"type": "string", "enum": ["date", "instant", "minute"]},
            {"type": "null"},
        ]
    }
    field = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "metric_code": {"type": "string"},
            "value": {"type": "number"},
            "unit": {"type": "string"},
            "source_text": nullable_string,
            "confidence": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "source_local_date": nullable_string,
            "source_timestamp": nullable_string,
            "temporal_precision": nullable_precision,
            "evidence_region": {"anyOf": [{"type": "object"}, {"type": "null"}]},
            "algorithm_code": nullable_string,
            "algorithm_version": nullable_string,
        },
        "required": [
            "metric_code",
            "value",
            "unit",
            "source_text",
            "confidence",
            "source_local_date",
            "source_timestamp",
            "temporal_precision",
            "evidence_region",
            "algorithm_code",
            "algorithm_version",
        ],
    }
    group = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "key": {"type": "string"},
            "source_local_date": nullable_string,
            "source_timestamp": nullable_string,
            "temporal_precision": nullable_precision,
            "fields": {"type": "array", "minItems": 1, "items": field},
        },
        "required": [
            "key",
            "source_local_date",
            "source_timestamp",
            "temporal_precision",
            "fields",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string"},
            "provider_code": nullable_string,
            "physical_device_code": nullable_string,
            "source_application": nullable_string,
            "source_application_version": nullable_string,
            "source_timezone": nullable_string,
            "source_utc_offset_minutes": nullable_integer,
            "groups": {"type": "array", "minItems": 1, "items": group},
        },
        "required": [
            "schema_version",
            "provider_code",
            "physical_device_code",
            "source_application",
            "source_application_version",
            "source_timezone",
            "source_utc_offset_minutes",
            "groups",
        ],
    }


def _structured_content(envelope: Any) -> tuple[dict[str, Any], str | None]:
    if not isinstance(envelope, dict):
        raise ValueError("provider envelope is not an object")
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("provider envelope has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("provider choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("provider message is not an object")
    parsed = message.get("parsed")
    content = parsed if parsed is not None else message.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise ValueError("provider content is not text")
            parts.append(item["text"])
        content = "".join(parts)
    if isinstance(content, str):
        content = json.loads(content)
    if not isinstance(content, dict):
        raise ValueError("provider content is not structured JSON")
    provider_model = _optional_text(envelope.get("model"))
    return content, provider_model


def _result_from_payload(
    payload: dict[str, Any],
    request: ExtractionRequest,
    *,
    extractor_name: str,
    extractor_version: str,
    model_name: str,
    model_version: str | None,
    prompt_version: str,
) -> ExtractionResult:
    _reject_unknown_keys(payload, _ALLOWED_TOP_LEVEL_KEYS)
    _require_keys(payload, _REQUIRED_TOP_LEVEL_KEYS)
    schema_version = payload["schema_version"]
    schema_version = _required_text(schema_version, "schema_version")
    if schema_version != request.schema_version:
        raise ExtractionFailure("extractor_invalid_payload", "unsupported photo schema version")

    source_timezone = _optional_text(payload.get("source_timezone")) or request.timezone
    if source_timezone:
        try:
            ZoneInfo(source_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ExtractionFailure(
                "extractor_invalid_payload", "source timezone is not usable"
            ) from exc
    source_offset = _optional_offset(payload.get("source_utc_offset_minutes"))
    if source_offset is None:
        source_offset = request.source_utc_offset_minutes
    groups_value = payload.get("groups")
    if not isinstance(groups_value, list) or not groups_value:
        raise ExtractionFailure(
            "extractor_empty_result", "extractor returned no measurement groups"
        )

    groups = tuple(
        _parse_group(raw_group, source_timezone=source_timezone, source_offset=source_offset)
        for raw_group in groups_value
    )
    if not groups:
        raise ExtractionFailure(
            "extractor_empty_result", "extractor returned no measurement groups"
        )
    return ExtractionResult(
        extractor_name=extractor_name,
        extractor_version=extractor_version,
        schema_version=schema_version,
        provider_code=_optional_text(payload.get("provider_code")) or request.provider_code,
        physical_device_code=(
            _optional_text(payload.get("physical_device_code")) or request.physical_device_code
        ),
        groups=groups,
        model_name=model_name,
        model_version=model_version,
        prompt_version=prompt_version,
        source_application=(
            _optional_text(payload.get("source_application")) or request.source_application
        ),
        source_application_version=(
            _optional_text(payload.get("source_application_version"))
            or request.source_application_version
        ),
        source_timezone=source_timezone,
        source_utc_offset_minutes=source_offset,
    )


def _parse_group(
    raw_group: Any, *, source_timezone: str | None, source_offset: int | None
) -> MeasurementGroup:
    if not isinstance(raw_group, dict):
        raise ExtractionFailure("extractor_invalid_payload", "measurement group is not an object")
    _reject_unknown_keys(raw_group, _ALLOWED_GROUP_KEYS)
    _require_keys(raw_group, _REQUIRED_GROUP_KEYS)
    key = _required_text(raw_group.get("key"), "measurement group key")
    group_date = _parse_date(raw_group.get("source_local_date"))
    group_timestamp = _parse_timestamp(raw_group.get("source_timestamp"))
    group_precision = _parse_precision(raw_group.get("temporal_precision"))
    _validate_temporal_shape(group_precision, group_timestamp)
    fields_value = raw_group.get("fields")
    if not isinstance(fields_value, list) or not fields_value:
        raise ExtractionFailure("extractor_empty_result", "measurement group has no fields")
    fields = tuple(
        _parse_field(
            raw_field,
            group_date=group_date,
            group_timestamp=group_timestamp,
            group_precision=group_precision,
            source_timezone=source_timezone,
            source_offset=source_offset,
        )
        for raw_field in fields_value
    )
    return MeasurementGroup(
        key=key,
        fields=fields,
        source_local_date=group_date,
        source_timestamp=group_timestamp,
        temporal_precision=group_precision,
    )


def _parse_field(
    raw_field: Any,
    *,
    group_date: date | None,
    group_timestamp: datetime | None,
    group_precision: str | None,
    source_timezone: str | None,
    source_offset: int | None,
) -> CandidateField:
    if not isinstance(raw_field, dict):
        raise ExtractionFailure("extractor_invalid_payload", "candidate field is not an object")
    _reject_unknown_keys(raw_field, _ALLOWED_FIELD_KEYS)
    _require_keys(raw_field, _REQUIRED_FIELD_KEYS)
    metric_code = _required_text(raw_field.get("metric_code"), "candidate metric code")
    value = _finite_number(raw_field.get("value"), "candidate value")
    unit = _required_text(raw_field.get("unit"), "candidate unit")
    _validate_unit(metric_code, unit)
    source_text = _optional_text(raw_field.get("source_text"))
    confidence = _optional_confidence(raw_field.get("confidence"))
    field_date = _parse_date(raw_field.get("source_local_date"))
    field_timestamp = _parse_timestamp(raw_field.get("source_timestamp"))
    field_precision = _parse_precision(raw_field.get("temporal_precision"))
    _validate_temporal_shape(field_precision or group_precision, field_timestamp or group_timestamp)
    if group_date is not None and field_date is not None and group_date != field_date:
        raise ExtractionFailure("extractor_invalid_payload", "group and field dates disagree")
    if (
        group_timestamp is not None
        and field_timestamp is not None
        and group_timestamp != field_timestamp
    ):
        raise ExtractionFailure("extractor_invalid_payload", "group and field timestamps disagree")
    if (
        group_precision is not None
        and field_precision is not None
        and group_precision != field_precision
    ):
        raise ExtractionFailure("extractor_invalid_payload", "group and field precision disagree")
    evidence_region = raw_field.get("evidence_region")
    if evidence_region is not None and not isinstance(evidence_region, dict):
        raise ExtractionFailure("extractor_invalid_payload", "evidence region is not an object")
    return CandidateField(
        metric_code=metric_code,
        proposed_value=value,
        proposed_unit=unit,
        source_text=source_text,
        confidence=confidence,
        source_local_date=field_date,
        source_timestamp=field_timestamp,
        temporal_precision=field_precision,
        evidence_region=evidence_region,
        algorithm_code=_optional_text(raw_field.get("algorithm_code")),
        algorithm_version=_optional_text(raw_field.get("algorithm_version")),
    )


def _validate_temporal_shape(precision: str | None, timestamp: datetime | None) -> None:
    if precision == "date" and timestamp is not None:
        raise ExtractionFailure(
            "extractor_invalid_payload", "date-only evidence cannot contain a timestamp"
        )
    if precision in {"instant", "minute"} and timestamp is None:
        raise ExtractionFailure(
            "extractor_invalid_payload", "timestamp is required for instant or minute precision"
        )


def _validate_unit(metric_code: str, unit: str) -> None:
    normalized = unit.strip().lower()
    if metric_code in _KG_METRICS and normalized not in _KG_UNITS:
        raise ExtractionFailure("extractor_invalid_payload", "candidate unit is not supported")
    if metric_code in _PERCENT_METRICS and normalized not in _PERCENT_UNITS:
        raise ExtractionFailure("extractor_invalid_payload", "candidate unit is not supported")


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExtractionFailure("extractor_invalid_payload", "source date is malformed")
    try:
        if len(value) != 10 or value[4] != "-" or value[7] != "-":
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ExtractionFailure("extractor_invalid_payload", "source date is malformed") from exc


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or "T" not in value:
        raise ExtractionFailure("extractor_invalid_payload", "source timestamp is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExtractionFailure(
            "extractor_invalid_payload", "source timestamp is malformed"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExtractionFailure(
            "extractor_invalid_payload", "source timestamp must include an offset"
        )
    return parsed


def _parse_precision(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in _ALLOWED_PRECISIONS:
        raise ExtractionFailure("extractor_invalid_payload", "temporal precision is malformed")
    return value


def _optional_confidence(value: Any) -> float | None:
    if value is None:
        return None
    result = _finite_number(value, "confidence")
    if not 0 <= result <= 1:
        raise ExtractionFailure("extractor_invalid_payload", "confidence is out of range")
    return result


def _optional_offset(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not -840 <= value <= 840:
        raise ExtractionFailure("extractor_invalid_payload", "source UTC offset is malformed")
    return value


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExtractionFailure("extractor_invalid_payload", f"{label} is malformed")
    result = float(value)
    if not math.isfinite(result):
        raise ExtractionFailure("extractor_invalid_payload", f"{label} is malformed")
    return result


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is missing")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} is missing")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("text field is malformed")
    text = value.strip()
    return text or None


def _reject_unknown_keys(value: Mapping[str, Any], allowed: frozenset[str]) -> None:
    if set(value) - allowed:
        raise ExtractionFailure(
            "extractor_invalid_payload", "structured response has unknown fields"
        )


def _require_keys(value: Mapping[str, Any], required: frozenset[str]) -> None:
    if required - set(value):
        raise ExtractionFailure(
            "extractor_invalid_payload", "structured response is missing required fields"
        )


__all__ = [
    "MAX_PROVIDER_RESPONSE_BYTES",
    "OpenAICompatibleVisionExtractor",
    "UnconfiguredImageMeasurementExtractor",
    "VISION_EXTRACTOR_NAME",
    "VISION_EXTRACTOR_VERSION",
    "VISION_PROMPT_VERSION",
    "VisionHttpResponse",
    "build_photo_extractor",
]
