"""Opt-in planning from the unchanged bounded completed-day acquisition proof."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from healthcheck.db.models import GarminSource, Provider
from healthcheck.garmin.completed_steps_read import read_completed_steps_window
from healthcheck.garmin.normalization import GarminSourceIdentity
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore


class DailySummaryReacquisitionBlocked(ValueError):
    """Fixed-vocabulary proof failure; never includes IDs, paths or raw values."""


@dataclass(frozen=True, slots=True)
class DailySummaryReacquisitionPlan:
    source_id: str
    source_instance_id: str
    source_kind: str
    device_attributed: bool
    device_code: str | None
    device_model: str | None
    requested_days: frozenset[date]
    proven_days: frozenset[date]

    def matches(self, identity: GarminSourceIdentity) -> bool:
        return (
            identity.provider_code == "garmin_connect"
            and identity.source_instance_id == self.source_instance_id
            and identity.source_kind == self.source_kind
            and identity.device_attributed == self.device_attributed
            and identity.device_code == self.device_code
            and identity.device_model == self.device_model
        )


def plan_daily_summary_reacquisition(
    factory,
    store: ContentAddressedGarminPayloadStore,
    *,
    source_id: str,
    start: date,
    end: date,
    evaluated_at: datetime,
) -> DailySummaryReacquisitionPlan:
    """One unchanged reader request/snapshot for the entire bounded invocation.

    Acquisition proof is independent of the field's numeric availability. Nothing
    here reconstructs historic receipts or writes projection/coverage state.
    """
    if not isinstance(evaluated_at, datetime) or evaluated_at.utcoffset() is None:
        raise DailySummaryReacquisitionBlocked("evaluation_clock_invalid")
    with factory() as session:
        source = session.get(GarminSource, source_id)
        provider = session.get(Provider, source.provider_id) if source else None
        if (
            source is None
            or source.provider_code != "garmin_connect"
            or source.source_kind != "provider"
            or provider is None
            or provider.code != "garmin_connect"
        ):
            raise DailySummaryReacquisitionBlocked("source_binding_invalid")
        try:
            canonical = GarminSourceIdentity(
                source_kind=source.source_kind,
                provider_code=source.provider_code,
                device_attributed=source.device_attributed,
                device_code=source.device_code,
                device_model=source.device_model,
            )
        except ValueError:
            raise DailySummaryReacquisitionBlocked("source_binding_invalid") from None
        if (
            canonical.source_instance_id != source.source_instance_id
            or not source.acquisition_source_id
        ):
            raise DailySummaryReacquisitionBlocked("source_binding_invalid")
        window = read_completed_steps_window(
            session,
            payload_store=store,
            source_id=source_id,
            start_date=start,
            end_date=end,
            evaluated_at=evaluated_at,
        )
        if not window.search_complete:
            raise DailySummaryReacquisitionBlocked("proof_search_incomplete:" + str(window.reason))
        requested = frozenset(start + timedelta(days=i) for i in range((end - start).days + 1))
        if {cell.calendar_date for cell in window.cells} != requested:
            raise DailySummaryReacquisitionBlocked("dates_not_completed")
        if window.reason is not None or window.source_identity is None:
            raise DailySummaryReacquisitionBlocked("source_binding_invalid")
        proven = set()
        for cell in window.cells:
            # A clean non-successful acquisition can be reacquired. Contradictory
            # identity/spine/receipt metadata is a different failure: the reader
            # exposes it as unproven evidence even when its scan is complete.
            # A non-successful run can mask receipt defects behind that same
            # reason, so an existing unproven receipt requires separate diagnosis.
            if any(
                not item.acquisition_proven
                and (
                    item.reason != "acquisition_success_unproven"
                    or item.acquisition_receipt_version is not None
                )
                for item in cell.evidence
            ):
                raise DailySummaryReacquisitionBlocked("acquisition_metadata_invalid")
            if cell.state == "ambiguous":
                raise DailySummaryReacquisitionBlocked("latest_acquisition_ambiguous")
            latest = [item for item in cell.evidence if item.received_at == cell.latest_received_at]
            if latest and all(item.acquisition_proven for item in latest):
                proven.add(cell.calendar_date)
            elif cell.latest_received_at is not None and cell.latest_received_at >= evaluated_at:
                raise DailySummaryReacquisitionBlocked("clock_not_after_latest_acquisition")
        return DailySummaryReacquisitionPlan(
            source.id,
            source.source_instance_id,
            source.source_kind,
            source.device_attributed,
            source.device_code,
            source.device_model,
            requested,
            frozenset(proven),
        )
