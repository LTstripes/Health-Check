"""Fail-closed LAN binding rules for the ingest-only listener."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True, slots=True)
class BindingDecision:
    allowed: bool
    host: str
    requires_plain_http_warning: bool
    reason_code: str
    message: str


def classify_ingest_bind_host(host: str) -> str:
    """Return ``loopback``, ``private``, ``unspecified``, or ``public``."""

    normalized = host.strip().lower()
    if not normalized:
        return "unspecified"
    if normalized in LOOPBACK_HOSTS:
        return "loopback"
    if normalized in {"0.0.0.0", "::", "[::]"}:
        return "unspecified"
    try:
        address = ipaddress.ip_address(normalized.strip("[]"))
    except ValueError:
        # Hostnames other than localhost are treated as potentially public.
        return "public"
    if address.is_loopback:
        return "loopback"
    if address.is_unspecified:
        return "unspecified"
    if address.is_private or address.is_link_local:
        return "private"
    return "public"


def evaluate_ingest_binding(host: str, *, trusted_private_lan_http: bool) -> BindingDecision:
    """Decide whether the ingest listener may bind ``host``.

    Fail-closed policy (R01 §4/§13):

    - loopback is always allowed without the plain-HTTP opt-in;
    - private/link-local binds require explicit ``trusted_private_lan_http``;
    - unspecified (``0.0.0.0`` / ``::``) and public binds are never allowed.
    """

    kind = classify_ingest_bind_host(host)
    if kind == "loopback":
        return BindingDecision(
            allowed=True,
            host=host,
            requires_plain_http_warning=False,
            reason_code="loopback",
            message="ingest bound to loopback",
        )
    if kind == "private":
        if not trusted_private_lan_http:
            return BindingDecision(
                allowed=False,
                host=host,
                requires_plain_http_warning=False,
                reason_code="plain_lan_opt_in_required",
                message=(
                    "plain private-LAN HTTP requires HEALTHCHECK_TRUSTED_PRIVATE_LAN_HTTP=true; "
                    "bearer credentials and health payloads lack transport confidentiality"
                ),
            )
        return BindingDecision(
            allowed=True,
            host=host,
            requires_plain_http_warning=True,
            reason_code="trusted_private_lan_http",
            message=(
                "WARNING: ingest is using plain private-LAN HTTP; "
                "bearer credentials and health payloads lack transport confidentiality"
            ),
        )
    if kind == "unspecified":
        return BindingDecision(
            allowed=False,
            host=host,
            requires_plain_http_warning=False,
            reason_code="public_bind_unsupported",
            message="binding the ingest listener to all interfaces is unsupported",
        )
    return BindingDecision(
        allowed=False,
        host=host,
        requires_plain_http_warning=False,
        reason_code="public_bind_unsupported",
        message="public internet exposure of the ingest listener is unsupported",
    )


__all__ = [
    "BindingDecision",
    "LOOPBACK_HOSTS",
    "classify_ingest_bind_host",
    "evaluate_ingest_binding",
]
