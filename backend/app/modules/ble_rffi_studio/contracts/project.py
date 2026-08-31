from __future__ import annotations

from typing import Literal

from .common import StudioContract

PROJECT_SCHEMA_VERSION = "ble-rffi-studio-project-v1"
CAMPAIGN_SCHEMA_VERSION = "ble-rffi-studio-campaign-v1"


class ProjectRecord(StudioContract):
    """The top-level experimental context every other artifact belongs to.
    Nothing in this module is ever stored in a global, context-free space."""

    schema_version: Literal["ble-rffi-studio-project-v1"] = PROJECT_SCHEMA_VERSION
    project_id: str
    name: str
    description: str = ""
    device_family: str
    created_at: str


class CampaignRecord(StudioContract):
    schema_version: Literal["ble-rffi-studio-campaign-v1"] = CAMPAIGN_SCHEMA_VERSION
    campaign_id: str
    project_id: str
    name: str
    protocol_reference: str | None = None
    status: Literal["ACTIVE", "CLOSED"] = "ACTIVE"
    created_at: str
