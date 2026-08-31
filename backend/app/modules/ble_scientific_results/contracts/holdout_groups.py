"""Real TRAIN/VALIDATION/FUTURE_TEST group assignment for a dataset --
Fase-1 closure item 10. Frozen the same way every other identity-bearing
object in this codebase is (StudioContract: immutable, content-hashable);
a correction never overwrites, it creates a new set of assignments for
the same dataset (list_holdout_groups returns all of them, most-recent
first).

Building this mechanism does NOT mean real groups exist yet -- no 20-day
campaign has run, so there is nothing real to assign FUTURE_TEST to today.
This contract and its repository methods exist so a later phase has
exactly one place to freeze real groups into, never a second competing
mechanism invented once the data exists.
"""
from __future__ import annotations

from typing import Literal

from .common import StudioContract, identity_hash

HOLDOUT_GROUP_SCHEMA_VERSION = "ble-scientific-results-holdout-group-v1"

HoldoutGroup = Literal["TRAIN", "VALIDATION", "FUTURE_TEST"]


class HoldoutGroupAssignment(StudioContract):
    schema_version: str = HOLDOUT_GROUP_SCHEMA_VERSION
    assignment_id: str
    dataset_id: str
    dataset_version: str
    group: HoldoutGroup

    physical_unit_ids: list[str] = []
    day_ids: list[str] = []
    session_ids: list[str] = []

    frozen_at: str
    group_manifest_sha256: str

    @staticmethod
    def make_assignment_id(*, dataset_id: str, dataset_version: str, group: str, frozen_at: str) -> str:
        return identity_hash(dataset_id, dataset_version, group, frozen_at, prefix="holdout-group")
