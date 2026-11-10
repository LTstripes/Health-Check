"""Bounded, same-origin Owner forms for sleep day classification."""

from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from healthcheck.external_runtime_lock import (
    ExternalRuntimeOperationBusyError,
    ExternalRuntimeOperationLockError,
)
from healthcheck.sleep_schedule_settings import update_sleep_schedule_settings
from healthcheck.web.pages import render_error

router = APIRouter()


@router.post("/sleep/settings")
async def sleep_settings(request: Request):
    try:
        if request.headers.get("content-type", "").split(";", 1)[0] != (
                "application/x-www-form-urlencoded"):
            raise ValueError("invalid_form")
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > 8192:
                raise ValueError("oversize_form")
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True,
                          max_num_fields=20)
        if set(fields) - {"revision", "return_to", "operation", "weekday", "date", "day_type"}:
            raise ValueError("invalid_form")
        if any(len(values) != 1 for key, values in fields.items() if key != "weekday"):
            raise ValueError("duplicate_field")
        operation = fields["operation"][0]
        allowed = {"revision", "return_to", "operation"}
        allowed |= {"weekday"} if operation == "weekdays" else {"date", "day_type"}
        if set(fields) - allowed or operation not in {"weekdays", "override"}:
            raise ValueError("invalid_form")
        target = fields["return_to"][0]
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or parsed.path != "/sleep" or "\\" in target:
            raise ValueError("invalid_return")
        options = {"revision": fields["revision"][0]}
        if operation == "weekdays":
            raw = fields.get("weekday", [])
            if any(day not in {str(n) for n in range(7)} for day in raw):
                raise ValueError("invalid_weekday")
            options["work_weekdays"] = [int(day) for day in raw]
        else:
            options.update(override_date=fields["date"][0], day_type=fields["day_type"][0])
        update_sleep_schedule_settings(request.app.state.settings, **options)
    except (KeyError, ValueError, UnicodeError):
        return render_error(request, code="invalid_sleep_settings", status_code=422,
                            message="Проверьте дни и дату. Если настройки изменились, "
                            "перезагрузите страницу сна перед сохранением.")
    except (OSError, ExternalRuntimeOperationLockError, ExternalRuntimeOperationBusyError):
        return render_error(request, code="sleep_settings_unavailable", status_code=503,
                            message="Не удалось сохранить настройки сна. Повторите позже.")
    return RedirectResponse(target, status_code=303, headers={"Cache-Control": "no-store"})
