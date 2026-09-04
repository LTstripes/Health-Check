"""Static Garmin capability contracts for the R02 preparation slice."""

from healthcheck.garmin.capabilities import (
    CAPABILITY_CONTRACT_VERSION,
    CAPABILITY_MATRIX,
    GARMIN_CAPABILITY_INVENTORY,
    GARMIN_PROVIDER_CODE,
    GARMINCONNECT_VERSION,
    VIVOACTIVE_5_DEVICE_CODE,
    VIVOACTIVE_5_MODEL,
    CapabilityStatus,
    DeviceSupport,
    GarminCapability,
    GarminCapabilityInventory,
    GarminStream,
    capability_inventory,
    capability_matrix,
    get_capability,
    live_spike_questions,
)
from healthcheck.garmin.contracts import (
    CAPABILITY_FIXTURE_CONTRACT_VERSION,
    GarminCapabilityFixture,
    GarminCapabilityFixtureError,
    load_synthetic_fixture,
)

__all__ = [
    "CAPABILITY_CONTRACT_VERSION",
    "CAPABILITY_FIXTURE_CONTRACT_VERSION",
    "CAPABILITY_MATRIX",
    "GARMIN_CAPABILITY_INVENTORY",
    "GARMINCONNECT_VERSION",
    "GARMIN_PROVIDER_CODE",
    "VIVOACTIVE_5_DEVICE_CODE",
    "VIVOACTIVE_5_MODEL",
    "CapabilityStatus",
    "DeviceSupport",
    "GarminCapability",
    "GarminCapabilityFixture",
    "GarminCapabilityFixtureError",
    "GarminCapabilityInventory",
    "GarminStream",
    "capability_inventory",
    "capability_matrix",
    "get_capability",
    "live_spike_questions",
    "load_synthetic_fixture",
]
