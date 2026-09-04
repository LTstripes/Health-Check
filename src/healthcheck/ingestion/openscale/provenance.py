"""Stable openScale webhook identities used at ingest persistence time."""

from __future__ import annotations

from healthcheck.db.models import AcquisitionSource, MeasurementAlgorithm
from healthcheck.db.repositories import ProvenanceRepositories
from healthcheck.ingestion.openscale.errors import OpenScaleIngestError

OPENSCALE_PROVIDER = "openscale"
OPENSCALE_S400_DEVICE = "xiaomi_s400"
OPENSCALE_WEIGHT_ALGORITHM = "openscale_s400_weight"
OPENSCALE_COMPOSITION_ALGORITHM = "openscale_s400_composition_unknown"
OPENSCALE_COMPOSITION_GROUP = "openscale-s400-composition-unknown"


def require_source_instance_id(source_instance_id: str | None) -> str:
    if source_instance_id is None or not str(source_instance_id).strip():
        raise OpenScaleIngestError(
            "ingest_not_configured",
            "openScale source_instance_id is not configured",
            status_code=503,
        )
    return str(source_instance_id).strip()


def ensure_openscale_acquisition_source(
    repositories: ProvenanceRepositories,
    *,
    source_instance_id: str,
    source_application: str | None = "openScale",
    source_application_version: str | None = None,
    configuration_fingerprint: str | None = None,
) -> AcquisitionSource:
    provider = repositories.providers.get_or_create(OPENSCALE_PROVIDER, "openScale", "scale_app")
    device = repositories.physical_devices.get_or_create(
        OPENSCALE_S400_DEVICE,
        manufacturer="Xiaomi",
        model="S400",
        display_name="Xiaomi Body Composition Scale S400",
    )
    return repositories.acquisition_sources.get_or_create(
        provider_id=provider.id,
        physical_device_id=device.id,
        input_method="webhook",
        source_instance_id=require_source_instance_id(source_instance_id),
        source_application=source_application,
        source_application_version=source_application_version,
        configuration_fingerprint=configuration_fingerprint,
    )


def algorithm_for_metric(
    repositories: ProvenanceRepositories,
    *,
    metric_code: str,
    algorithm_identity: str,
    config_identity: str,
) -> MeasurementAlgorithm:
    """Return openScale algorithms that never share Xiaomi composition groups."""

    version = f"{algorithm_identity}/{config_identity}"
    if metric_code == "weight":
        return repositories.measurement_algorithms.get_or_create(
            code=OPENSCALE_WEIGHT_ALGORITHM,
            version=version,
            metric_family="weight",
            producer="openscale",
            compatibility_group=OPENSCALE_WEIGHT_ALGORITHM,
        )
    return repositories.measurement_algorithms.get_or_create(
        code=OPENSCALE_COMPOSITION_ALGORITHM,
        version=version,
        metric_family="body_composition",
        producer="openscale",
        compatibility_group=OPENSCALE_COMPOSITION_GROUP,
    )


__all__ = [
    "OPENSCALE_COMPOSITION_ALGORITHM",
    "OPENSCALE_COMPOSITION_GROUP",
    "OPENSCALE_PROVIDER",
    "OPENSCALE_S400_DEVICE",
    "OPENSCALE_WEIGHT_ALGORITHM",
    "algorithm_for_metric",
    "ensure_openscale_acquisition_source",
    "require_source_instance_id",
]
