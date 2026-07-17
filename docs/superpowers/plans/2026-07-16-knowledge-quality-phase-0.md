# Knowledge Quality Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立知识质量控制平面的阶段0基础，使处理产物、FTS索引、向量索引和检索能够绑定到同一个不可变 release，并生成可重复的质量基线。

**Architecture:** 保留现有 `layer1.processed.v1` 文件格式，通过每文档 `processing-record.json` 和 release 级 `release-manifest.json` 增加控制平面元数据。release manifest 显式列出文档版本和文件哈希；索引及检索只消费该清单，不再为 release-aware 路径自行推断“最新版”。候选 release 完成索引、基线和一致性验证后才能原子激活。

现有 `layer1.processed.v1` 中的 `blocks.page_start/page_end`、`EvidenceSpan.page/bbox` 和 chunk 页面范围继续作为阶段0的页面、block 与证据定位契约。`quality-record.json` 只增加画像和质量信号，不复制正文模型；阶段3再通过新 schema 版本扩展字符范围和更细粒度坐标。

**Tech Stack:** Python 3.11+、标准库 dataclasses/json/pathlib/sqlite3、现有 pytest、现有 FTS5 与本地向量索引。

## Global Constraints

- 不修改 `layer1.processed.v1` 现有字段语义；阶段0只新增 sidecar 契约。
- 不增加新的强制运行时依赖。
- 旧的 processed-dir API 保持可用；新增 release-aware API 必须有独立测试。
- release-aware 路径必须使用 manifest 中的精确文档版本，禁止重新扫描并选择最新版。
- release ID 必须由有序文档产物哈希和版本化处理规则确定，不能依赖当前时间。
- manifest 中的产物路径相对 `processed_dir` 保存，禁止把机器绝对路径纳入 release ID。
- 任何文件哈希不匹配都必须阻止索引、检索或激活。
- active release 使用临时文件加 `Path.replace()` 原子切换。
- 阶段0不改变解析器、OCR、chunker 或生产质量门策略。
- 每个任务遵循 TDD：先失败测试，再最小实现，再全量相关测试，再提交。

## File Map

新建：

- `src/agent_knowledge_hub/processing_record.py`：文档处理记录数据结构、生成、加载和历史产物推断。
- `src/agent_knowledge_hub/quality_contracts.py`：阶段0文档画像、分层质量信号和不可用指标契约。
- `src/agent_knowledge_hub/release_manifest.py`：release 数据结构、候选清单、精确产物迭代、校验、完成和激活。
- `src/agent_knowledge_hub/quality_baseline.py`：从指定 release 生成可比较的基线报告。
- `src/agent_knowledge_hub/release_pipeline.py`：串联候选清单、索引、基线、完成验证。
- `schemas/knowledge-release.v1/release-manifest.schema.json`：release manifest JSON Schema。
- `schemas/knowledge-release.v1/processing-record.schema.json`：processing record JSON Schema。
- `schemas/knowledge-release.v1/quality-record.schema.json`：画像与分层质量记录 JSON Schema。
- `schemas/knowledge-release.v1/README.md`：sidecar 契约说明。
- `tests/test_processing_record.py`：处理记录测试。
- `tests/test_quality_contracts.py`：画像和分层质量契约测试。
- `tests/test_release_manifest.py`：候选、哈希、完成和激活测试。
- `tests/test_release_bound_indexes.py`：索引 release 绑定测试。
- `tests/test_release_retrieval.py`：release 精确检索及错配阻断测试。
- `tests/test_quality_baseline.py`：基线确定性测试。
- `tests/test_release_pipeline.py`：阶段0端到端测试。

修改：

- `src/agent_knowledge_hub/models.py`：`IngestResult` 增加 processing record 路径。
- `src/agent_knowledge_hub/pipeline.py`：入库时写处理记录。
- `src/agent_knowledge_hub/fts_index.py`：支持从 release manifest 建索引并记录 release ID。
- `src/agent_knowledge_hub/vector_index.py`：支持从 release manifest 建索引并记录 release ID。
- `src/agent_knowledge_hub/retrieval.py`：支持按 manifest 加载、缓存和校验索引。
- `src/agent_knowledge_hub/cli.py`：增加 `build-release`、`activate-release` 及 release-aware 参数。
- `tests/test_document_ingest_pipeline.py`：验证入库 sidecar。
- `tests/test_fts_index.py`：覆盖 FTS metadata。
- `tests/test_vector_index.py`：覆盖向量 metadata。
- `docs/知识库前处理与检索说明.md`：说明 release-aware 阶段0流程。

---

### Task 1: 文档处理记录与质量契约 sidecar

**Files:**

- Create: `src/agent_knowledge_hub/processing_record.py`
- Create: `src/agent_knowledge_hub/quality_contracts.py`
- Create: `schemas/knowledge-release.v1/processing-record.schema.json`
- Create: `schemas/knowledge-release.v1/quality-record.schema.json`
- Modify: `src/agent_knowledge_hub/models.py:107-129`
- Modify: `src/agent_knowledge_hub/pipeline.py:14-77`
- Test: `tests/test_processing_record.py`
- Test: `tests/test_quality_contracts.py`
- Test: `tests/test_document_ingest_pipeline.py`

**Interfaces:**

- Produces: `PROCESSING_RECORD_SCHEMA_VERSION = "knowledge-processing-record.v1"`
- Produces: `build_processing_record(...) -> ProcessingRecord`
- Produces: `load_or_infer_processing_record(version_dir: Path) -> ProcessingRecord`
- Produces: `write_processing_record(path: Path, record: ProcessingRecord) -> None`
- Produces: `QUALITY_RECORD_SCHEMA_VERSION = "knowledge-quality-record.v1"`
- Produces: `build_quality_record(canonical: dict, chunks: list[dict]) -> QualityRecord`
- Produces: `write_quality_record(path: Path, record: QualityRecord) -> None`
- Changes: `IngestResult.processing_record_path: Path`
- Changes: `IngestResult.quality_record_path: Path`

- [ ] **Step 1: Write failing processing-record tests**

```python
# tests/test_processing_record.py
import json
from pathlib import Path

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.processing_record import (
    PROCESSING_RECORD_SCHEMA_VERSION,
    load_or_infer_processing_record,
)
from agent_knowledge_hub.utils import file_sha256


def test_ingest_writes_hash_bound_processing_record(tmp_path: Path):
    source = tmp_path / "spec.md"
    source.write_text("# API\n\nMsgSend() sends a message.", encoding="utf-8")

    result = ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title="API",
        document_version="v1",
    )

    payload = json.loads(result.processing_record_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == PROCESSING_RECORD_SCHEMA_VERSION
    assert payload["document_version_id"] == result.document_version_id
    assert payload["canonical_sha256"] == file_sha256(result.document_json_path)
    assert payload["chunks_sha256"] == file_sha256(result.chunks_jsonl_path)
    assert payload["processing_run_id"].startswith("run_")
    assert payload["parser_name"]
    assert payload["chunker_version"] == "section-aware-block-chunker-v1"
    assert payload["quality_rules_version"] == "parse-quality-gate-v1"


def test_legacy_processing_record_is_inferred_without_mutating_files(tmp_path: Path):
    version_dir = tmp_path / "doc" / "v1"
    version_dir.mkdir(parents=True)
    (version_dir / "canonical-document.json").write_text(
        '{"document_version":{"document_version_id":"docver_1","file_hash":"source_hash"},'
        '"parse_report":{"parser_name":"legacy-parser"}}',
        encoding="utf-8",
    )
    (version_dir / "chunks.jsonl").write_text('{"chunk_id":"chunk_1"}\n', encoding="utf-8")

    record = load_or_infer_processing_record(version_dir)

    assert record.document_version_id == "docver_1"
    assert record.record_origin == "legacy_inferred"
    assert not (version_dir / "processing-record.json").exists()
```

```python
# tests/test_quality_contracts.py
import json
from pathlib import Path

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.quality_contracts import QUALITY_RECORD_SCHEMA_VERSION


def test_ingest_writes_explicit_observed_and_unavailable_quality_metrics(tmp_path: Path):
    source = tmp_path / "spec.md"
    source.write_text("# API\n\nMsgSend() sends a message.", encoding="utf-8")

    result = ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title="API",
        document_version="v1",
    )

    payload = json.loads(result.quality_record_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == QUALITY_RECORD_SCHEMA_VERSION
    assert payload["document_version_id"] == result.document_version_id
    assert payload["profile"]["block_count"] == 2
    assert payload["profile"]["chunk_count"] >= 1
    assert payload["signals"]["traceable_chunk_ratio"]["status"] == "observed"
    assert payload["signals"]["traceable_chunk_ratio"]["value"] == 1.0
    assert payload["signals"]["column_count"]["status"] == "unavailable"
    assert payload["signals"]["ocr_confidence"]["status"] == "unavailable"
    assert payload["signals"]["table_structure_score"]["status"] == "unavailable"
    assert payload["signals"]["bbox_coverage"]["status"] == "unavailable"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_processing_record.py -q
```

Expected: collection fails because `agent_knowledge_hub.processing_record` and `quality_contracts` do not exist.

- [ ] **Step 3: Implement the processing record contract**

```python
# src/agent_knowledge_hub/processing_record.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.utils import file_sha256, stable_id, write_json

PROCESSING_RECORD_SCHEMA_VERSION = "knowledge-processing-record.v1"
CHUNKER_VERSION = "section-aware-block-chunker-v1"
QUALITY_RULES_VERSION = "parse-quality-gate-v1"


@dataclass(frozen=True)
class ProcessingRecord:
    schema_version: str
    processing_run_id: str
    document_version_id: str
    source_file_hash: str
    parser_name: str
    chunker_version: str
    quality_rules_version: str
    canonical_sha256: str
    chunks_sha256: str
    record_origin: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_processing_record(
    *,
    document_version_id: str,
    source_file_hash: str,
    parser_name: str,
    canonical_path: Path,
    chunks_path: Path,
) -> ProcessingRecord:
    canonical_sha256 = file_sha256(canonical_path)
    chunks_sha256 = file_sha256(chunks_path)
    run_id = stable_id(
        "run",
        document_version_id,
        source_file_hash,
        parser_name,
        CHUNKER_VERSION,
        QUALITY_RULES_VERSION,
        canonical_sha256,
        chunks_sha256,
    )
    return ProcessingRecord(
        schema_version=PROCESSING_RECORD_SCHEMA_VERSION,
        processing_run_id=run_id,
        document_version_id=document_version_id,
        source_file_hash=source_file_hash,
        parser_name=parser_name,
        chunker_version=CHUNKER_VERSION,
        quality_rules_version=QUALITY_RULES_VERSION,
        canonical_sha256=canonical_sha256,
        chunks_sha256=chunks_sha256,
        record_origin="ingestion",
    )


def load_or_infer_processing_record(version_dir: Path) -> ProcessingRecord:
    record_path = version_dir / "processing-record.json"
    if record_path.exists():
        return ProcessingRecord(**json.loads(record_path.read_text(encoding="utf-8")))
    canonical_path = version_dir / "canonical-document.json"
    chunks_path = version_dir / "chunks.jsonl"
    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    version = payload.get("document_version") or {}
    report = payload.get("parse_report") or {}
    inferred = build_processing_record(
        document_version_id=str(version.get("document_version_id") or ""),
        source_file_hash=str(version.get("file_hash") or ""),
        parser_name=str(report.get("parser_name") or "legacy"),
        canonical_path=canonical_path,
        chunks_path=chunks_path,
    )
    return ProcessingRecord(**{**inferred.to_dict(), "record_origin": "legacy_inferred"})


def write_processing_record(path: Path, record: ProcessingRecord) -> None:
    write_json(path, record.to_dict())
```

Implement the phase0 quality contract without inventing unavailable values:

```python
# src/agent_knowledge_hub/quality_contracts.py
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.utils import write_json

QUALITY_RECORD_SCHEMA_VERSION = "knowledge-quality-record.v1"
QUALITY_EVALUATOR_VERSION = "phase0-baseline-v1"


@dataclass(frozen=True)
class QualitySignal:
    status: str
    value: float | int | str | bool | None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentProfile:
    source_format: str
    page_count: int | None
    block_count: int
    chunk_count: int
    table_count: int
    text_character_count: int


@dataclass(frozen=True)
class QualityRecord:
    schema_version: str
    document_version_id: str
    evaluator_version: str
    profile: DocumentProfile
    signals: dict[str, QualitySignal]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_quality_record(
    canonical: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> QualityRecord:
    version = canonical["document_version"]
    report = canonical.get("parse_report") or {}
    blocks = canonical.get("blocks") or []
    evidence_ids = {
        str(item.get("evidence_id"))
        for item in canonical.get("evidence_spans") or []
        if item.get("evidence_id")
    }
    traceable = sum(
        1
        for chunk in chunks
        if chunk.get("evidence_ids")
        and all(str(item) in evidence_ids for item in chunk["evidence_ids"])
    )
    ratio = traceable / len(chunks) if chunks else 0.0
    unavailable = QualitySignal(
        status="unavailable",
        value=None,
        reason_codes=("not_measured_in_phase0",),
    )
    return QualityRecord(
        schema_version=QUALITY_RECORD_SCHEMA_VERSION,
        document_version_id=str(version["document_version_id"]),
        evaluator_version=QUALITY_EVALUATOR_VERSION,
        profile=DocumentProfile(
            source_format=str(report.get("source_format") or "unknown"),
            page_count=report.get("page_count"),
            block_count=len(blocks),
            chunk_count=len(chunks),
            table_count=int(report.get("table_count") or 0),
            text_character_count=sum(len(str(block.get("text") or "")) for block in blocks),
        ),
        signals={
            "traceable_chunk_ratio": QualitySignal("observed", ratio),
            "parse_quality_status": QualitySignal(
                "observed",
                str((report.get("quality_report") or {}).get("status") or "unknown"),
            ),
            "parse_quality_score": QualitySignal(
                "observed",
                (report.get("quality_report") or {}).get("score"),
            ),
            "column_count": unavailable,
            "ocr_confidence": unavailable,
            "table_structure_score": unavailable,
            "bbox_coverage": unavailable,
        },
    )


def write_quality_record(path: Path, record: QualityRecord) -> None:
    write_json(path, record.to_dict())
```

In `pipeline.ingest_file()`, write `canonical-document.json` and `chunks.jsonl` first, then build/write the record:

```python
processing_record_path = version_output_dir / "processing-record.json"
quality_record_path = version_output_dir / "quality-record.json"
processing_record = build_processing_record(
    document_version_id=canonical.document_version.document_version_id,
    source_file_hash=canonical.document_version.file_hash,
    parser_name=canonical.parse_report.parser_name,
    canonical_path=document_json_path,
    chunks_path=chunks_jsonl_path,
)
write_processing_record(processing_record_path, processing_record)
quality_record = build_quality_record(
    canonical.to_dict(),
    [chunk.to_dict() for chunk in chunks],
)
write_quality_record(quality_record_path, quality_record)
```

Add `processing_record_path: Path` and `quality_record_path: Path` to `IngestResult`, include both in `to_summary_dict()`, and pass them when constructing the result.

- [ ] **Step 4: Add the processing-record JSON Schema**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://ai-knowledge-foundation.local/schemas/knowledge-release.v1/processing-record.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "processing_run_id", "document_version_id",
    "source_file_hash", "parser_name", "chunker_version",
    "quality_rules_version", "canonical_sha256", "chunks_sha256",
    "record_origin"
  ],
  "properties": {
    "schema_version": {"const": "knowledge-processing-record.v1"},
    "processing_run_id": {"type": "string", "minLength": 1},
    "document_version_id": {"type": "string", "minLength": 1},
    "source_file_hash": {"type": "string", "minLength": 1},
    "parser_name": {"type": "string", "minLength": 1},
    "chunker_version": {"type": "string", "minLength": 1},
    "quality_rules_version": {"type": "string", "minLength": 1},
    "canonical_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
    "chunks_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
    "record_origin": {"enum": ["ingestion", "legacy_inferred"]}
  }
}
```

Add `quality-record.schema.json` with the exact required top-level fields and signal shape:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://ai-knowledge-foundation.local/schemas/knowledge-release.v1/quality-record.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "document_version_id", "evaluator_version", "profile", "signals"],
  "properties": {
    "schema_version": {"const": "knowledge-quality-record.v1"},
    "document_version_id": {"type": "string", "minLength": 1},
    "evaluator_version": {"type": "string", "minLength": 1},
    "profile": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_format", "page_count", "block_count", "chunk_count", "table_count", "text_character_count"],
      "properties": {
        "source_format": {"type": "string"},
        "page_count": {"type": ["integer", "null"]},
        "block_count": {"type": "integer", "minimum": 0},
        "chunk_count": {"type": "integer", "minimum": 0},
        "table_count": {"type": "integer", "minimum": 0},
        "text_character_count": {"type": "integer", "minimum": 0}
      }
    },
    "signals": {
      "type": "object",
      "minProperties": 1,
      "additionalProperties": {
        "type": "object",
        "additionalProperties": false,
        "required": ["status", "value", "reason_codes"],
        "properties": {
          "status": {"enum": ["observed", "unavailable"]},
          "value": {"type": ["number", "integer", "string", "boolean", "null"]},
          "reason_codes": {"type": "array", "items": {"type": "string"}}
        }
      }
    }
  }
}
```

- [ ] **Step 5: Run focused and existing ingestion tests**

Run:

```powershell
python -m pytest tests/test_processing_record.py tests/test_quality_contracts.py tests/test_document_ingest_pipeline.py tests/test_incremental_ingest.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_knowledge_hub/processing_record.py src/agent_knowledge_hub/quality_contracts.py src/agent_knowledge_hub/models.py src/agent_knowledge_hub/pipeline.py schemas/knowledge-release.v1/processing-record.schema.json schemas/knowledge-release.v1/quality-record.schema.json tests/test_processing_record.py tests/test_quality_contracts.py tests/test_document_ingest_pipeline.py
git commit -m "feat: record processing and baseline quality metadata"
```

---

### Task 2: 候选 release manifest 与精确产物迭代

**Files:**

- Create: `src/agent_knowledge_hub/release_manifest.py`
- Create: `schemas/knowledge-release.v1/release-manifest.schema.json`
- Create: `schemas/knowledge-release.v1/README.md`
- Test: `tests/test_release_manifest.py`

**Interfaces:**

- Produces: `RELEASE_MANIFEST_SCHEMA_VERSION = "knowledge-release.v1"`
- Produces: `create_candidate_release(processed_dir: Path, releases_dir: Path) -> ReleaseManifest`
- Produces: `load_release_manifest(path: Path) -> ReleaseManifest`
- Produces: `iter_release_documents(manifest_path: Path) -> list[tuple[Path, dict[str, Any]]]`
- Produces: `validate_release_artifacts(manifest_path: Path) -> list[str]`

- [ ] **Step 1: Write failing manifest tests**

```python
# tests/test_release_manifest.py
import json
from pathlib import Path

import pytest

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.release_manifest import (
    create_candidate_release,
    iter_release_documents,
    validate_release_artifacts,
)


def _ingest_version(root: Path, source: Path, version: str, text: str):
    source.write_text(text, encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=root,
        title="Demo",
        document_version=version,
    )


def test_candidate_release_pins_one_explicit_version(tmp_path: Path):
    processed = tmp_path / "processed"
    source = tmp_path / "demo.md"
    old = _ingest_version(processed, source, "v1", "# V1\n\nold")
    new = _ingest_version(processed, source, "v2", "# V2\n\nnew")

    manifest = create_candidate_release(processed, tmp_path / "releases")
    selected = iter_release_documents(manifest.manifest_path)

    assert manifest.status == "candidate"
    assert manifest.release_id.startswith("release_")
    assert [item.document_version_id for item in manifest.documents] == [
        new.document_version_id
    ]
    assert old.document_version_id not in [
        item.document_version_id for item in manifest.documents
    ]
    assert len(selected) == 1


def test_release_validation_detects_mutated_chunks(tmp_path: Path):
    processed = tmp_path / "processed"
    result = _ingest_version(
        processed, tmp_path / "demo.md", "v1", "# V1\n\noriginal"
    )
    manifest = create_candidate_release(processed, tmp_path / "releases")
    result.chunks_jsonl_path.write_text('{"chunk_id":"mutated"}\n', encoding="utf-8")

    errors = validate_release_artifacts(manifest.manifest_path)

    assert errors == [f"chunks_hash_mismatch:{result.document_version_id}"]
    with pytest.raises(ValueError, match="chunks_hash_mismatch"):
        iter_release_documents(manifest.manifest_path)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_release_manifest.py -q
```

Expected: collection fails because `release_manifest` does not exist.

- [ ] **Step 3: Implement release dataclasses and candidate creation**

Use the existing latest-version ordering only once, inside candidate creation. Persist the selected relative paths and hashes:

```python
RELEASE_MANIFEST_SCHEMA_VERSION = "knowledge-release.v1"


@dataclass(frozen=True)
class ReleaseDocument:
    document_id: str
    document_version_id: str
    canonical_path: str
    chunks_path: str
    processing_record_path: str | None
    quality_record_path: str
    canonical_sha256: str
    chunks_sha256: str
    quality_record_sha256: str
    processing_run_id: str
    quality_status: str
    quality_score: float | None


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: str
    release_id: str
    status: str
    created_at: str
    processed_dir: str
    quality_rules_version: str
    documents: tuple[ReleaseDocument, ...]
    indexes: dict[str, dict[str, str]]
    baseline: dict[str, str] | None
    manifest_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "status": self.status,
            "created_at": self.created_at,
            "processed_dir": self.processed_dir,
            "quality_rules_version": self.quality_rules_version,
            "documents": [asdict(item) for item in self.documents],
            "indexes": self.indexes,
            "baseline": self.baseline,
        }

    def resolve_artifact(self, name: str) -> Path:
        relative_path = self.indexes[name]["path"]
        return (self.manifest_path.parent / relative_path).resolve()
```

Candidate creation requirements:

```python
def create_candidate_release(
    processed_dir: Path,
    releases_dir: Path,
) -> ReleaseManifest:
    processed_root = processed_dir.resolve()
    selected = _select_latest_processed_versions(processed_root)
    documents = tuple(
        sorted(
            (_release_document(processed_root, chunks, canonical) for chunks, canonical in selected),
            key=lambda item: (item.document_id, item.document_version_id),
        )
    )
    if not documents:
        raise ValueError("Cannot create a release without documents")
    release_id = stable_id(
        "release",
        RELEASE_MANIFEST_SCHEMA_VERSION,
        QUALITY_RULES_VERSION,
        *[
            f"{item.document_version_id}:{item.canonical_sha256}:"
            f"{item.chunks_sha256}:{item.quality_record_sha256}"
            for item in documents
        ],
    )
    manifest_path = releases_dir.resolve() / release_id / "release-manifest.json"
    manifest = ReleaseManifest(
        schema_version=RELEASE_MANIFEST_SCHEMA_VERSION,
        release_id=release_id,
        status="candidate",
        created_at=utc_now_iso(),
        processed_dir=str(processed_root),
        quality_rules_version=QUALITY_RULES_VERSION,
        documents=documents,
        indexes={},
        baseline=None,
        manifest_path=manifest_path,
    )
    write_json(manifest_path, manifest.to_dict())
    return manifest
```

`_release_document()` must load `quality-record.json` for new ingests. For historical directories without that sidecar, it must build the same record in memory with `build_quality_record()`, write it into the candidate release directory under `derived-quality/<document_version_id>.json`, and bind that relative path and hash in the manifest. It must never modify the historical version directory.

`iter_release_documents()` must call `validate_release_artifacts()` first, resolve canonical/chunks paths under `processed_dir` and derived quality paths under the release directory, reject `..` traversal, verify all three hashes, and return exactly the manifest-selected canonical/chunks pairs.

- [ ] **Step 4: Add strict release schema**

The schema must require:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://ai-knowledge-foundation.local/schemas/knowledge-release.v1/release-manifest.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "release_id", "status", "created_at",
    "processed_dir", "quality_rules_version", "documents",
    "indexes", "baseline"
  ],
  "properties": {
    "schema_version": {"const": "knowledge-release.v1"},
    "release_id": {"type": "string", "pattern": "^release_[0-9a-f]+$"},
    "status": {"enum": ["candidate", "ready"]},
    "created_at": {"type": "string", "minLength": 1},
    "processed_dir": {"type": "string", "minLength": 1},
    "quality_rules_version": {"type": "string", "minLength": 1},
    "documents": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/document"}},
    "indexes": {"type": "object"},
    "baseline": {"type": ["object", "null"]}
  },
  "$defs": {
    "document": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "document_id", "document_version_id", "canonical_path", "chunks_path",
        "processing_record_path", "quality_record_path", "canonical_sha256",
        "chunks_sha256", "quality_record_sha256",
        "processing_run_id", "quality_status", "quality_score"
      ],
      "properties": {
        "document_id": {"type": "string", "minLength": 1},
        "document_version_id": {"type": "string", "minLength": 1},
        "canonical_path": {"type": "string", "minLength": 1},
        "chunks_path": {"type": "string", "minLength": 1},
        "processing_record_path": {"type": ["string", "null"]},
        "quality_record_path": {"type": "string", "minLength": 1},
        "canonical_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
        "chunks_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
        "quality_record_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
        "processing_run_id": {"type": "string", "minLength": 1},
        "quality_status": {"type": "string", "minLength": 1},
        "quality_score": {"type": ["number", "null"]}
      }
    }
  }
}
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/test_release_manifest.py tests/test_schema_contracts.py -q
```

Expected: all tests pass. Extend `test_schema_contracts.py` to assert both new schema files exist and their `const` values match module constants.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_knowledge_hub/release_manifest.py schemas/knowledge-release.v1 tests/test_release_manifest.py tests/test_schema_contracts.py
git commit -m "feat: add immutable candidate release manifests"
```

---

### Task 3: Release-bound FTS and vector indexes

**Files:**

- Modify: `src/agent_knowledge_hub/fts_index.py:11-151`
- Modify: `src/agent_knowledge_hub/vector_index.py:80-189`
- Test: `tests/test_release_bound_indexes.py`
- Test: `tests/test_fts_index.py`
- Test: `tests/test_vector_index.py`

**Interfaces:**

- Changes: `build_fts_index(..., release_manifest_path: Path | str | None = None)`
- Changes: `build_vector_index(..., release_manifest_path: Path | str | None = None)`
- Changes: both build summaries add `release_id: str | None`
- Produces: `read_fts_release_id(index_path: Path) -> str | None`
- Produces: `read_vector_release_id(index_path: Path) -> str | None`

- [ ] **Step 1: Write failing index-binding tests**

```python
from pathlib import Path

from agent_knowledge_hub.fts_index import build_fts_index, read_fts_release_id
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.release_manifest import create_candidate_release
from agent_knowledge_hub.vector_index import (
    build_vector_index,
    read_vector_release_id,
)


def _ingest(processed: Path, source: Path, title: str, text: str):
    source.write_text(f"# {title}\n\n{text}", encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=processed,
        title=title,
        document_version="v1",
    )


def test_indexes_pin_release_and_ignore_later_ingest(tmp_path: Path):
    processed = tmp_path / "processed"
    first = _ingest(processed, tmp_path / "first.md", "First", "alpha")
    release = create_candidate_release(processed, tmp_path / "releases")
    _ingest(processed, tmp_path / "second.md", "Second", "beta")

    fts_path = tmp_path / "indexes" / "chunks.db"
    vector_path = tmp_path / "indexes" / "chunks.json"
    fts = build_fts_index(
        processed_dir=processed,
        index_path=fts_path,
        release_manifest_path=release.manifest_path,
    )
    vector = build_vector_index(
        processed_dir=processed,
        index_path=vector_path,
        release_manifest_path=release.manifest_path,
    )

    assert fts.release_id == release.release_id
    assert vector.release_id == release.release_id
    assert fts.indexed_document_count == 1
    assert vector.indexed_document_count == 1
    assert read_fts_release_id(fts_path) == release.release_id
    assert read_vector_release_id(vector_path) == release.release_id
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/test_release_bound_indexes.py -q
```

Expected: FAIL because index builders reject `release_manifest_path`.

- [ ] **Step 3: Implement a shared input branch**

In both index builders:

```python
release_id: str | None = None
if release_manifest_path is None:
    processed_versions = _iter_latest_processed_versions(processed_root)
else:
    manifest = load_release_manifest(Path(release_manifest_path))
    if Path(manifest.processed_dir).resolve() != processed_root:
        raise ValueError("release_processed_dir_mismatch")
    processed_versions = iter_release_documents(manifest.manifest_path)
    release_id = manifest.release_id
```

Add `release_id` to both summaries. For FTS, create metadata in the same transaction:

```python
connection.execute(
    "CREATE TABLE release_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
)
if release_id is not None:
    connection.execute(
        "INSERT INTO release_metadata(key, value) VALUES ('release_id', ?)",
        (release_id,),
    )
```

For vector JSON, add:

```python
"release_id": release_id,
```

Implement exact readers:

```python
def read_fts_release_id(index_path: Path | str) -> str | None:
    connection = sqlite3.connect(Path(index_path).resolve())
    try:
        row = connection.execute(
            "SELECT value FROM release_metadata WHERE key = 'release_id'"
        ).fetchone()
        return str(row[0]) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()
```

```python
def read_vector_release_id(index_path: Path | str) -> str | None:
    resolved = Path(index_path).resolve()
    payload_path = resolved.with_suffix(".metadata.json") if resolved.suffix == ".npz" else resolved
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    value = payload.get("release_id")
    return str(value) if value else None
```

Apply release metadata to local JSON and both BGE index build paths.

- [ ] **Step 4: Run focused index tests**

Run:

```powershell
python -m pytest tests/test_release_bound_indexes.py tests/test_fts_index.py tests/test_vector_index.py -q
```

Expected: all tests pass, including existing legacy index calls with `release_id is None`.

- [ ] **Step 5: Commit**

```powershell
git add src/agent_knowledge_hub/fts_index.py src/agent_knowledge_hub/vector_index.py tests/test_release_bound_indexes.py tests/test_fts_index.py tests/test_vector_index.py
git commit -m "feat: bind search indexes to release manifests"
```

---

### Task 4: Release-aware retrieval and mismatch blocking

**Files:**

- Modify: `src/agent_knowledge_hub/retrieval.py:1589-1950`
- Modify: `src/agent_knowledge_hub/retrieval.py:2157-2361`
- Modify: `src/agent_knowledge_hub/retrieval.py:2872-2902`
- Test: `tests/test_release_retrieval.py`
- Test: `tests/test_context_pack_retrieval.py`

**Interfaces:**

- Changes: `build_context_pack_for_processed_dir(..., release_manifest_path=None)`
- Changes: `trace_evidence_in_processed_dir(..., release_manifest_path=None)`
- Produces: `_assert_release_index_compatibility(...) -> None`
- Cache key becomes `processed_dir|release_id`, not only `processed_dir`.

- [ ] **Step 1: Write failing release retrieval tests**

```python
from pathlib import Path

import pytest

from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.release_manifest import create_candidate_release
from agent_knowledge_hub.retrieval import build_context_pack_for_processed_dir


def _ingest(processed: Path, source: Path, title: str, text: str):
    source.write_text(f"# {title}\n\n{text}", encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=processed,
        title=title,
        document_version="v1",
    )


def test_release_retrieval_excludes_post_release_documents(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "old.md", "Old", "release_only_token")
    release = create_candidate_release(processed, tmp_path / "releases")
    _ingest(processed, tmp_path / "new.md", "New", "later_only_token")

    result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        release_manifest_path=release.manifest_path,
        query="later_only_token",
        top_k=5,
    )

    assert all(chunk.document_title != "New" for chunk in result.selected_chunks)


def test_release_retrieval_rejects_mismatched_index(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha")
    first = create_candidate_release(processed, tmp_path / "releases")
    index_path = tmp_path / "chunks.db"
    build_fts_index(
        processed_dir=processed,
        index_path=index_path,
        release_manifest_path=first.manifest_path,
    )
    _ingest(processed, tmp_path / "two.md", "Two", "beta")
    second = create_candidate_release(processed, tmp_path / "releases")

    with pytest.raises(ValueError, match="fts_release_mismatch"):
        build_context_pack_for_processed_dir(
            processed_dir=processed,
            release_manifest_path=second.manifest_path,
            fts_index_path=index_path,
            query="alpha",
        )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_release_retrieval.py -q
```

Expected: FAIL because retrieval does not accept `release_manifest_path`.

- [ ] **Step 3: Add exact manifest loading and cache isolation**

At the public entry:

```python
manifest = (
    load_release_manifest(Path(release_manifest_path))
    if release_manifest_path is not None
    else None
)
if manifest is not None and Path(manifest.processed_dir).resolve() != processed_root:
    raise ValueError("release_processed_dir_mismatch")
_assert_release_index_compatibility(
    release_id=manifest.release_id if manifest else None,
    fts_index_path=fts_index_path,
    vector_index_path=vector_index_path,
)
loaded_chunks = _load_processed_chunks(processed_root, manifest)
```

Implement:

```python
def _assert_release_index_compatibility(
    *,
    release_id: str | None,
    fts_index_path: Path | str | None,
    vector_index_path: Path | str | None,
) -> None:
    if release_id is None:
        return
    if fts_index_path is not None:
        actual = read_fts_release_id(fts_index_path)
        if actual != release_id:
            raise ValueError(f"fts_release_mismatch:expected={release_id}:actual={actual}")
    if vector_index_path is not None:
        actual = read_vector_release_id(vector_index_path)
        if actual != release_id:
            raise ValueError(f"vector_release_mismatch:expected={release_id}:actual={actual}")
```

Change loader:

```python
def _load_processed_chunks(
    processed_dir: Path,
    manifest: ReleaseManifest | None = None,
) -> list[_LoadedChunk]:
    cache_key = f"{processed_dir}|{manifest.release_id if manifest else 'legacy-latest'}"
    if cache_key in _CHUNK_CACHE:
        return _CHUNK_CACHE[cache_key]
    versions = (
        iter_release_documents(manifest.manifest_path)
        if manifest is not None
        else _iter_latest_processed_versions(processed_dir)
    )
    # Existing chunk conversion loop continues over `versions`.
```

Use the same manifest-selected versions in evidence trace. Add the following backward-compatible optional field to `ContextPackResult` immediately before the existing defaulted token fields:

```python
release_id: str | None = None
token_used: int = 0
token_budget: int | None = None
```

Set it to `manifest.release_id` for release-aware calls and `None` for legacy calls. Include `"release_id": self.release_id` in both `to_json_dict()` and `to_summary_dict()`. Assert both serialization paths in `tests/test_release_retrieval.py`.

- [ ] **Step 4: Run retrieval regression**

Run:

```powershell
python -m pytest tests/test_release_retrieval.py tests/test_context_pack_retrieval.py tests/test_layer1_contract.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/agent_knowledge_hub/retrieval.py tests/test_release_retrieval.py tests/test_context_pack_retrieval.py
git commit -m "feat: retrieve from exact release artifacts"
```

---

### Task 5: 可重复基线、release 完成验证与原子激活

**Files:**

- Create: `src/agent_knowledge_hub/quality_baseline.py`
- Extend: `src/agent_knowledge_hub/release_manifest.py`
- Test: `tests/test_quality_baseline.py`
- Extend: `tests/test_release_manifest.py`

**Interfaces:**

- Produces: `build_quality_baseline(manifest_path: Path) -> QualityBaseline`
- Produces: `finalize_release(manifest_path, fts_index_path, vector_index_path, baseline_path) -> ReleaseManifest`
- Produces: `activate_release(manifest_path: Path, active_pointer_path: Path) -> None`
- Produces: `load_active_release(active_pointer_path: Path) -> ReleaseManifest`

- [ ] **Step 1: Write failing baseline/finalization tests**

```python
from pathlib import Path

import pytest

from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.quality_baseline import build_quality_baseline
from agent_knowledge_hub.release_manifest import (
    activate_release,
    create_candidate_release,
    finalize_release,
    load_active_release,
)
from agent_knowledge_hub.utils import write_json
from agent_knowledge_hub.vector_index import build_vector_index


def _ingest(processed: Path, source: Path, title: str):
    source.write_text(f"# {title}\n\n{title} evidence", encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=processed,
        title=title,
        document_version="v1",
    )


def _build_candidate_with_two_documents(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One")
    _ingest(processed, tmp_path / "two.md", "Two")
    return create_candidate_release(processed, tmp_path / "releases")


def _build_release_artifacts(tmp_path: Path):
    release = _build_candidate_with_two_documents(tmp_path)
    processed = Path(release.processed_dir)
    release_dir = release.manifest_path.parent
    fts_path = release_dir / "indexes" / "chunks.db"
    vector_path = release_dir / "indexes" / "chunks.json"
    baseline_path = release_dir / "quality-baseline.json"
    build_fts_index(
        processed_dir=processed,
        index_path=fts_path,
        release_manifest_path=release.manifest_path,
    )
    build_vector_index(
        processed_dir=processed,
        index_path=vector_path,
        release_manifest_path=release.manifest_path,
    )
    write_json(
        baseline_path,
        build_quality_baseline(release.manifest_path).to_dict(),
    )
    return release, fts_path, vector_path, baseline_path


def test_baseline_is_deterministic_for_same_release(tmp_path: Path):
    release = _build_candidate_with_two_documents(tmp_path)

    first = build_quality_baseline(release.manifest_path)
    second = build_quality_baseline(release.manifest_path)

    assert first.to_dict() == second.to_dict()
    assert first.release_id == release.release_id
    assert first.document_count == 2
    assert first.traceable_chunk_ratio == 1.0


def test_activation_requires_ready_release_and_is_atomic(tmp_path: Path):
    release, fts_path, vector_path, baseline_path = _build_release_artifacts(tmp_path)
    pointer = tmp_path / "active-release.json"

    with pytest.raises(ValueError, match="release_not_ready"):
        activate_release(release.manifest_path, pointer)

    ready = finalize_release(
        release.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )
    activate_release(ready.manifest_path, pointer)

    active = load_active_release(pointer)
    assert active.release_id == ready.release_id
    assert not pointer.with_suffix(pointer.suffix + ".tmp").exists()
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_quality_baseline.py tests/test_release_manifest.py -q
```

Expected: FAIL because baseline/finalization APIs do not exist.

- [ ] **Step 3: Implement deterministic baseline**

`QualityBaseline.to_dict()` must exclude generation timestamps so repeat runs compare equal. It contains:

```python
@dataclass(frozen=True)
class QualityBaseline:
    schema_version: str
    release_id: str
    document_count: int
    chunk_count: int
    evidence_count: int
    traceable_chunk_count: int
    traceable_chunk_ratio: float
    quality_status_counts: dict[str, int]
    parser_counts: dict[str, int]
    source_format_counts: dict[str, int]
    warning_count: int
```

For every manifest document:

- Load canonical and chunks through `iter_release_documents()`.
- Count a chunk as traceable only when every `evidence_id` exists in canonical `evidence_spans`.
- Sort all dictionaries before constructing the dataclass.
- Keep `build_quality_baseline()` free of file writes; `release_pipeline` serializes the returned object.

- [ ] **Step 4: Implement finalization and atomic pointer**

Finalization must validate:

```python
errors = validate_release_artifacts(manifest_path)
if errors:
    raise ValueError(";".join(errors))
if read_fts_release_id(fts_index_path) != manifest.release_id:
    raise ValueError("fts_release_mismatch")
if read_vector_release_id(vector_index_path) != manifest.release_id:
    raise ValueError("vector_release_mismatch")
baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
if baseline.get("release_id") != manifest.release_id:
    raise ValueError("baseline_release_mismatch")
```

Write `status="ready"` plus relative index/baseline paths and SHA-256 hashes to a temporary manifest, then replace the candidate manifest. Activation writes:

```python
payload = {
    "schema_version": "active-knowledge-release.v1",
    "release_id": manifest.release_id,
    "manifest_path": str(manifest.manifest_path.resolve()),
}
temp_path = active_pointer_path.with_suffix(active_pointer_path.suffix + ".tmp")
write_json(temp_path, payload)
temp_path.replace(active_pointer_path)
```

Activation must reject a non-ready manifest and rerun artifact/hash validation.

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/test_quality_baseline.py tests/test_release_manifest.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_knowledge_hub/quality_baseline.py src/agent_knowledge_hub/release_manifest.py tests/test_quality_baseline.py tests/test_release_manifest.py
git commit -m "feat: finalize and atomically activate quality releases"
```

---

### Task 6: 一键 release 流水线、CLI、文档与端到端验收

**Files:**

- Create: `src/agent_knowledge_hub/release_pipeline.py`
- Modify: `src/agent_knowledge_hub/cli.py:1-470`
- Modify: `docs/知识库前处理与检索说明.md`
- Create: `tests/test_release_pipeline.py`

**Interfaces:**

- Produces: `build_release_bundle(processed_dir, releases_dir) -> ReleaseManifest`
- CLI: `build-release --processed-dir ... --releases-dir ...`
- CLI: `activate-release --manifest-path ... --active-pointer ...`

- [ ] **Step 1: Write failing end-to-end and CLI tests**

```python
import json
from pathlib import Path

from agent_knowledge_hub.cli import main
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.release_pipeline import build_release_bundle
from agent_knowledge_hub.retrieval import build_context_pack_for_processed_dir


def _ingest(processed: Path, source: Path, title: str, text: str):
    source.write_text(f"# {title}\n\n{text}", encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=processed,
        title=title,
        document_version="v1",
    )


def test_build_release_bundle_produces_ready_consistent_release(tmp_path: Path):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha API")
    _ingest(processed, tmp_path / "two.md", "Two", "beta API")

    ready = build_release_bundle(processed, tmp_path / "releases")

    assert ready.status == "ready"
    assert ready.indexes["fts"]["sha256"]
    assert ready.indexes["vector"]["sha256"]
    assert ready.baseline["sha256"]
    result = build_context_pack_for_processed_dir(
        processed_dir=processed,
        release_manifest_path=ready.manifest_path,
        fts_index_path=ready.resolve_artifact("fts"),
        vector_index_path=ready.resolve_artifact("vector"),
        query="alpha",
    )
    assert result.selected_chunks


def test_build_and_activate_release_cli(tmp_path: Path, capsys):
    processed = tmp_path / "processed"
    _ingest(processed, tmp_path / "one.md", "One", "alpha")
    releases = tmp_path / "releases"

    assert main([
        "build-release",
        "--processed-dir", str(processed),
        "--releases-dir", str(releases),
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    manifest_path = payload["manifest_path"]

    assert main([
        "activate-release",
        "--manifest-path", manifest_path,
        "--active-pointer", str(releases / "active-release.json"),
    ]) == 0
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_release_pipeline.py -q
```

Expected: FAIL because `release_pipeline` and CLI commands do not exist.

- [ ] **Step 3: Implement orchestration**

```python
def build_release_bundle(
    processed_dir: Path | str,
    releases_dir: Path | str,
) -> ReleaseManifest:
    candidate = create_candidate_release(Path(processed_dir), Path(releases_dir))
    release_dir = candidate.manifest_path.parent
    fts_path = release_dir / "indexes" / "chunks.fts.sqlite"
    vector_path = release_dir / "indexes" / "chunks.vector.json"
    baseline_path = release_dir / "quality-baseline.json"
    build_fts_index(
        processed_dir=processed_dir,
        index_path=fts_path,
        release_manifest_path=candidate.manifest_path,
    )
    build_vector_index(
        processed_dir=processed_dir,
        index_path=vector_path,
        release_manifest_path=candidate.manifest_path,
    )
    baseline = build_quality_baseline(candidate.manifest_path)
    write_json(baseline_path, baseline.to_dict())
    return finalize_release(
        candidate.manifest_path,
        fts_index_path=fts_path,
        vector_index_path=vector_path,
        baseline_path=baseline_path,
    )
```

On any exception, leave the candidate release unactivated and re-raise. Do not delete diagnostic artifacts.

- [ ] **Step 4: Add CLI commands**

Parser definitions:

```python
build_release_parser = subparsers.add_parser(
    "build-release",
    help="Build a release-bound FTS index, vector index, and quality baseline.",
)
build_release_parser.add_argument("--processed-dir", required=True, type=Path)
build_release_parser.add_argument("--releases-dir", required=True, type=Path)

activate_release_parser = subparsers.add_parser(
    "activate-release",
    help="Atomically point production at a ready release.",
)
activate_release_parser.add_argument("--manifest-path", required=True, type=Path)
activate_release_parser.add_argument("--active-pointer", required=True, type=Path)
```

Dispatch:

```python
elif args.command == "build-release":
    release = build_release_bundle(args.processed_dir, args.releases_dir)
    payload = {
        **release.to_dict(),
        "manifest_path": str(release.manifest_path),
    }
elif args.command == "activate-release":
    activate_release(args.manifest_path, args.active_pointer)
    payload = {
        "release_id": load_release_manifest(args.manifest_path).release_id,
        "active_pointer": str(args.active_pointer.resolve()),
    }
```

- [ ] **Step 5: Update operational documentation**

Add this exact sequence to `docs/知识库前处理与检索说明.md`:

```powershell
python -m agent_knowledge_hub.cli build-release `
  --processed-dir ".\data\processed" `
  --releases-dir ".\data\releases"

python -m agent_knowledge_hub.cli activate-release `
  --manifest-path ".\data\releases\<release_id>\release-manifest.json" `
  --active-pointer ".\data\releases\active-release.json"
```

Document:

- `build-release` does not activate automatically.
- Legacy direct index commands remain supported during migration.
- release-aware retrieval must use indexes from the same manifest.
- hash mismatch or index release mismatch is a blocker.
- stage 1 will add hard publication quality gates; stage 0 only establishes identity, consistency and baseline.

- [ ] **Step 6: Run phase0 verification**

Run:

```powershell
python -m pytest tests/test_processing_record.py tests/test_release_manifest.py tests/test_release_bound_indexes.py tests/test_release_retrieval.py tests/test_quality_baseline.py tests/test_release_pipeline.py -q
```

Expected: all phase0 tests pass.

Run:

```powershell
python -m pytest -q
```

Expected: full suite passes with zero failures.

Run:

```powershell
git diff --check
```

Expected: exit code 0 with no output.

- [ ] **Step 7: Commit**

```powershell
git add src/agent_knowledge_hub/release_pipeline.py src/agent_knowledge_hub/cli.py docs/知识库前处理与检索说明.md tests/test_release_pipeline.py
git commit -m "feat: add phase zero release quality pipeline"
```

## Phase 0 Completion Gate

阶段0只有在以下条件全部满足后才算完成：

- 新入库文档写出 hash-bound processing record。
- 历史 v1 产物可以无修改地推断 processing record 并进入候选 release。
- release manifest 精确固定文档版本和产物哈希。
- FTS 与所有向量索引格式均写入相同 release ID。
- release-aware 检索拒绝索引错配和文件哈希变化。
- 同一 release 重复生成的质量基线完全一致。
- 只有 `ready` release 可以原子激活。
- 旧 processed-dir 入口的现有测试保持通过。
- 全量测试通过且 `git diff --check` 无错误。

阶段0完成后，使用真实 QNX、Qualcomm 和正常 PDF 语料生成第一份生产基线。阶段1的门禁阈值和误拦截预算必须基于该基线单独规划，不在阶段0中预设。
