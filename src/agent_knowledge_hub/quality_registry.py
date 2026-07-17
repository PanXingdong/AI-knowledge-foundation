from dataclasses import dataclass


@dataclass(frozen=True)
class ReasonCodeDefinition:
    scope: str
    severity: str
    recommended_action: str
    hard: bool


REASON_CODE_REGISTRY: dict[str, ReasonCodeDefinition] = {
    "release.integrity.no_documents": ReasonCodeDefinition(
        "release", "fatal", "block_release", True
    ),
    "document.integrity.canonical_missing": ReasonCodeDefinition(
        "document", "fatal", "block_document", True
    ),
    "document.integrity.canonical_invalid": ReasonCodeDefinition(
        "document", "fatal", "block_document", True
    ),
    "document.integrity.chunks_missing": ReasonCodeDefinition(
        "document", "fatal", "block_document", True
    ),
    "document.integrity.chunks_invalid": ReasonCodeDefinition(
        "document", "fatal", "block_document", True
    ),
    "document.integrity.no_chunks": ReasonCodeDefinition(
        "document", "fatal", "block_document", True
    ),
    "document.integrity.processing_record_missing": ReasonCodeDefinition(
        "document", "error", "block_document", True
    ),
    "document.integrity.processing_record_invalid": ReasonCodeDefinition(
        "document", "error", "block_document", True
    ),
    "document.integrity.quality_record_missing": ReasonCodeDefinition(
        "document", "error", "block_document", True
    ),
    "document.integrity.quality_record_invalid": ReasonCodeDefinition(
        "document", "error", "block_document", True
    ),
    "document.integrity.document_version_mismatch": ReasonCodeDefinition(
        "document", "fatal", "block_document", True
    ),
    "document.parse.failed": ReasonCodeDefinition(
        "document", "fatal", "block_document", True
    ),
    "document.parse.unsupported": ReasonCodeDefinition(
        "document", "fatal", "block_document", True
    ),
    "document.content.text_too_short": ReasonCodeDefinition(
        "document", "warning", "warn", False
    ),
    "document.parse.warning_count_high": ReasonCodeDefinition(
        "document", "warning", "warn", False
    ),
    "document.parse.fallback_used": ReasonCodeDefinition(
        "document", "warning", "warn", False
    ),
    "page.integrity.reference_out_of_range": ReasonCodeDefinition(
        "page", "error", "quarantine", True
    ),
    "page.integrity.document_version_mismatch": ReasonCodeDefinition(
        "page", "error", "quarantine", True
    ),
    "page.integrity.source_location_missing": ReasonCodeDefinition(
        "page", "error", "quarantine", True
    ),
    "page.content.text_too_short": ReasonCodeDefinition(
        "page", "warning", "warn", False
    ),
    "block.integrity.empty": ReasonCodeDefinition(
        "block", "error", "quarantine", True
    ),
    "block.integrity.type_invalid": ReasonCodeDefinition(
        "block", "error", "quarantine", True
    ),
    "block.integrity.page_range_invalid": ReasonCodeDefinition(
        "block", "error", "quarantine", True
    ),
    "block.integrity.document_version_mismatch": ReasonCodeDefinition(
        "block", "error", "quarantine", True
    ),
    "block.evidence.missing": ReasonCodeDefinition(
        "block", "error", "quarantine", True
    ),
    "block.evidence.hash_mismatch": ReasonCodeDefinition(
        "block", "error", "quarantine", True
    ),
    "block.evidence.block_reference_missing": ReasonCodeDefinition(
        "block", "error", "quarantine", True
    ),
    "block.content.too_long": ReasonCodeDefinition(
        "block", "warning", "warn", False
    ),
    "block.content.duplicate": ReasonCodeDefinition(
        "block", "warning", "warn", False
    ),
    "chunk.integrity.empty": ReasonCodeDefinition(
        "chunk", "error", "quarantine", True
    ),
    "chunk.evidence.missing": ReasonCodeDefinition(
        "chunk", "error", "quarantine", True
    ),
    "chunk.evidence.reference_missing": ReasonCodeDefinition(
        "chunk", "error", "quarantine", True
    ),
    "chunk.integrity.document_version_mismatch": ReasonCodeDefinition(
        "chunk", "error", "quarantine", True
    ),
    "chunk.content.too_short": ReasonCodeDefinition(
        "chunk", "warning", "warn", False
    ),
    "chunk.content.too_long": ReasonCodeDefinition(
        "chunk", "warning", "warn", False
    ),
    "chunk.content.duplicate": ReasonCodeDefinition(
        "chunk", "warning", "warn", False
    ),
}
