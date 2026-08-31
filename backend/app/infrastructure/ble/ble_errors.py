class BleIntegrationError(RuntimeError):
    code = "ble_integration_error"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)


def error_type(code: str):
    return type(code.title().replace("_", ""), (BleIntegrationError,), {"code": code})


WorkerUnavailable = error_type("worker_unavailable")
WorkerVersionMismatch = error_type("worker_version_mismatch")
IqRecoveryNotAvailable = error_type("iq_recovery_not_available")
UnsupportedContractVersion = error_type("unsupported_contract_version")
ArtifactManifestMissing = error_type("artifact_manifest_missing")
ArtifactHashMismatch = error_type("artifact_hash_mismatch")
ArtifactSchemaInvalid = error_type("artifact_schema_invalid")
ArtifactJobIdMismatch = error_type("artifact_job_id_mismatch")
ArtifactWorkerCommitMismatch = error_type("artifact_worker_commit_mismatch")
ArtifactCountMismatch = error_type("artifact_count_mismatch")
InvalidCrcPacketPublished = error_type("invalid_crc_packet_published")
DuplicatePacketId = error_type("duplicate_packet_id")
DuplicatePacketPublication = error_type("duplicate_packet_publication")
InvalidJsonlRecord = error_type("invalid_jsonl_record")
UndeclaredArtifact = error_type("undeclared_artifact")

