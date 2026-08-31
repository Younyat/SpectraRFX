"""Identity of one scientific-results run: which frozen protocol, which
dataset/split/model-set fingerprints it points at, and where its own
(read-only-derived) output directory lives. `dataset_fingerprint` /
`split_fingerprint` / `model_set_fingerprint` are populated as the run's
inputs are declared (Fase 1 fills them from the dataset/split the protocol
references; `model_set_fingerprint` stays empty until a later phase that
actually runs model branches)."""
from __future__ import annotations

from .common import StudioContract, identity_hash

PAPER_RUN_SCHEMA_VERSION = "ble-scientific-results-paper-run-v1"


class PaperRunRecord(StudioContract):
    schema_version: str = PAPER_RUN_SCHEMA_VERSION
    paper_run_id: str
    campaign_id: str
    protocol_id: str
    protocol_version: int

    # Concrete ble_rffi_studio pointers this run's preflight/analysis reads
    # from -- the *_fingerprint fields below are the hashes recomputed from
    # these files at preflight time, checked against the frozen protocol's
    # own dataset_policy_hash/split_manifest_hash (see
    # ScientificResultsRepository.run_preflight).
    dataset_id: str
    dataset_version: str
    scientific_task: str

    dataset_fingerprint: str | None = None
    split_fingerprint: str | None = None
    model_set_fingerprint: str | None = None

    analysis_code_commit: str
    analysis_environment_hash: str

    storage_path: str
    created_at: str

    @staticmethod
    def make_paper_run_id(*, protocol_id: str, created_at: str) -> str:
        return identity_hash(protocol_id, created_at, prefix="paper-run")
