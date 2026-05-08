"""
Governance Module - Audit, Lineage, and Deterministic Output

Provides:
- Canonical JSON serialization for byte-identical outputs
- SHA256 hashing for files and JSON objects
- Deterministic run_id generation
- JSONL audit log writing
- Schema version registry
- Parameters archive loading
- Adapter mapping validation

All operations are deterministic: same inputs produce identical outputs.
No timestamps, no UUIDs, no network calls.
"""

from governance.audit_log import AuditErrorCode, AuditLog, AuditRecord, AuditStage, AuditStatus, StageIO, load_audit_log
from governance.canonical_json import canonical_dump, canonical_dumps, validate_canonical_json
from governance.hashing import (
    compute_input_hashes,
    hash_bytes,
    hash_canonical_json,
    hash_canonical_json_short,
    hash_file,
)
from governance.mapping_loader import (
    MappingLoadError,
    SchemaMismatchError,
    compute_mapping_hash,
    load_mapping,
    save_mapping,
    validate_source_schema,
)
from governance.output_writer import (
    build_input_lineage,
    get_environment_fingerprint,
    inject_governance_metadata,
    write_canonical_output,
)
from governance.params_loader import ParamsLoadError, compute_parameters_hash, load_params, save_params
from governance.run_id import compute_run_id, validate_run_id
from governance.schema_registry import (
    DEFAULT_SCORE_VERSION,
    PIPELINE_VERSION,
    SCHEMA_VERSION,
    SUPPORTED_SCORE_VERSIONS,
    get_schema_info,
    validate_schema_version,
    validate_score_version,
)

__all__ = [
    # Hashing
    "hash_file",
    "hash_bytes",
    "hash_canonical_json",
    "hash_canonical_json_short",
    "compute_input_hashes",
    # Canonical JSON
    "canonical_dumps",
    "canonical_dump",
    "validate_canonical_json",
    # Run ID
    "compute_run_id",
    "validate_run_id",
    # Audit
    "AuditLog",
    "AuditRecord",
    "AuditStage",
    "AuditStatus",
    "AuditErrorCode",
    "StageIO",
    "load_audit_log",
    # Schema
    "SCHEMA_VERSION",
    "PIPELINE_VERSION",
    "DEFAULT_SCORE_VERSION",
    "SUPPORTED_SCORE_VERSIONS",
    "validate_schema_version",
    "validate_score_version",
    "get_schema_info",
    # Params
    "load_params",
    "compute_parameters_hash",
    "save_params",
    "ParamsLoadError",
    # Mapping
    "load_mapping",
    "compute_mapping_hash",
    "save_mapping",
    "validate_source_schema",
    "MappingLoadError",
    "SchemaMismatchError",
    # Output
    "inject_governance_metadata",
    "write_canonical_output",
    "build_input_lineage",
    "get_environment_fingerprint",
]
