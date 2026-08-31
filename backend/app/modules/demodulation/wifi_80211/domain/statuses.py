EVIDENCE_LEVELS = (
    "rf_activity",
    "preamble_candidate",
    "synchronized",
    "phy_header_valid",
    "psdu_recovered",
    "fcs_valid",
    "mac_parsed",
    "payload_clear",
    "payload_protected",
)

FAILURE_REASONS = {
    "synchronization_failed",
    "l_sig_invalid",
    "unsupported_rate",
    "insufficient_samples",
    "viterbi_failed",
    "descrambler_failed",
    "fcs_mismatch",
    "sample_gap",
    "unsupported_phy",
    "unsupported_spatial_streams",
}
