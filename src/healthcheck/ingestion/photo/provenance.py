"""Stable Xiaomi photo-import identities used at confirmation time."""

from __future__ import annotations

import uuid

from healthcheck.db.models import AcquisitionSource, MeasurementAlgorithm
from healthcheck.db.repositories import ProvenanceRepositories, canonical_json

XIAOMI_S400_DEVICE = "xiaomi_s400"
XIAOMI_HOME_PROVIDER = "xiaomi_home"
XIAOMI_APP_UNKNOWN_PROVIDER = "xiaomi_app_unknown"

WEIGHT_ALGORITHM_CODE = "xiaomi_s400_weight"
XIAOMI_HOME_COMPOSITION_ALGORITHM = "xiaomi_home_s400_unknown_version"
XIAOMI_UNKNOWN_APP_ALGORITHM = "xiaomi_s400_unknown_app_algorithm"
PHOTO_ACQUISITION_NAMESPACE = uuid.UUID("8f3c2a10-6b91-5d4e-9a77-1c0d4e8f2b65")


def resolve_provider_code(provider_code: str | None) -> str:
    """Map missing/unrecognized providers to unknown — never silently to Xiaomi Home."""

    if provider_code == XIAOMI_HOME_PROVIDER:
        return XIAOMI_HOME_PROVIDER
    return XIAOMI_APP_UNKNOWN_PROVIDER


def photo_acquisition_instance_id(
    *,
    provider_code: str | None,
    physical_device_code: str | None,
    source_application: str | None,
    source_application_version: str | None,
) -> str:
    """Stable photo-import source identity including application/version."""

    payload = canonical_json(
        {
            "input_method": "photo_import",
            "provider_code": resolve_provider_code(provider_code),
            "physical_device_code": physical_device_code,
            "source_application": source_application,
            "source_application_version": source_application_version,
        }
    )
    return str(uuid.uuid5(PHOTO_ACQUISITION_NAMESPACE, payload))


def ensure_photo_acquisition_source(
    repositories: ProvenanceRepositories,
    *,
    provider_code: str | None = None,
    physical_device_code: str = XIAOMI_S400_DEVICE,
    source_application: str | None = None,
    source_application_version: str | None = None,
) -> AcquisitionSource:
    resolved = resolve_provider_code(provider_code)
    if resolved == XIAOMI_HOME_PROVIDER:
        provider = repositories.providers.get_or_create(
            XIAOMI_HOME_PROVIDER, "Xiaomi Home", "scale_app"
        )
        application = source_application or "Xiaomi Home"
    else:
        provider = repositories.providers.get_or_create(
            XIAOMI_APP_UNKNOWN_PROVIDER, "Unknown Xiaomi app", "scale_app"
        )
        application = source_application
    device = repositories.physical_devices.get_or_create(
        physical_device_code,
        manufacturer="Xiaomi",
        model="S400",
        display_name="Xiaomi Body Composition Scale S400",
    )
    return repositories.acquisition_sources.get_or_create(
        provider_id=provider.id,
        physical_device_id=device.id,
        input_method="photo_import",
        source_instance_id=photo_acquisition_instance_id(
            provider_code=resolved,
            physical_device_code=physical_device_code,
            source_application=application,
            source_application_version=source_application_version,
        ),
        source_application=application,
        source_application_version=source_application_version,
    )


def algorithm_for_metric(
    repositories: ProvenanceRepositories,
    *,
    metric_code: str,
    provider_code: str,
    algorithm_code: str | None = None,
    algorithm_version: str | None = None,
) -> MeasurementAlgorithm:
    version = algorithm_version or "unknown"
    if metric_code == "weight":
        code = algorithm_code or WEIGHT_ALGORITHM_CODE
        return repositories.measurement_algorithms.get_or_create(
            code=code,
            version=version,
            metric_family="weight",
            producer="xiaomi",
            compatibility_group=code,
        )
    code = algorithm_code or (
        XIAOMI_UNKNOWN_APP_ALGORITHM
        if provider_code == XIAOMI_APP_UNKNOWN_PROVIDER
        else XIAOMI_HOME_COMPOSITION_ALGORITHM
    )
    return repositories.measurement_algorithms.get_or_create(
        code=code,
        version=version,
        metric_family="body_composition",
        producer="xiaomi",
        compatibility_group=code,
    )


def provider_code_for_source(
    repositories: ProvenanceRepositories, acquisition_source: AcquisitionSource
) -> str:
    loaded = repositories.providers.get(acquisition_source.provider_id)
    if loaded is None:
        return XIAOMI_APP_UNKNOWN_PROVIDER
    return loaded.code
