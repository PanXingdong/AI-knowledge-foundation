# Knowledge Quality Phase 1 Observe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有发布和检索行为的前提下，实现四层确定性质量检测、版本化 observe policy、质量报告、publication preview、quarantine preview 和评估 CLI。

**Architecture:** 新增独立的质量模型、reason registry、detector、policy engine 和 observe orchestrator。Detector 只生成事实 signal，policy engine 生成 recommended/effective decision；observe 模式保留全部 chunk，只记录 `would_quarantine` 和 `would_block`。现有 `quality.py`、release v1、索引和 retrieval 逻辑在本 PR 中保持不变。

**Tech Stack:** Python 3.11+、标准库 dataclasses/json/pathlib/hashlib、现有 pytest、现有 `stable_id`/`sha256_text`/`write_json` 工具。

## Global Constraints

- PR 1 只实现 Observe，不实现 `knowledge-release.v2`、candidate 强制或 production 强制。
- 不修改现有 `quality.py` 的 `_context_pack_gate()` 行为。
- 不删除 retrieval 中现有 gate bypass 或全量 fallback；它们属于 PR 3。
- 不修改 FTS、vector index、release manifest 或 active pointer 行为。
- 不增加运行时依赖。
- 不使用 LLM 生成 signal 或 decision。
- 硬 signal 只来自确定性完整性检查。
- 多栏、表格、目录噪声和标题碎片只产生 soft signal。
- reason code 不包含厂商、项目名或文件名特例。
- 相同 artifacts 与 policy 必须产生相同 signal ID、decision ID、顺序和 determinism fingerprint。
- 报告 fingerprint 不包含绝对路径、生成时间或机器相关信息。
- observe 模式下，recommended action 可以是 quarantine/block，但 effective action 只能是 allow/warn。
- 原始 canonical、chunks、processing record 和 quality record 保持只读。
- 所有新增行为遵循 TDD；每个任务独立提交。

## File Map

新建：

- `src/agent_knowledge_hub/quality_models.py`：Phase 1 signal、policy、decision、report 和 preview 数据契约。
- `src/agent_knowledge_hub/quality_registry.py`：reason code 注册表和默认 observe policy。
- `src/agent_knowledge_hub/quality_policy.py`：policy 加载、校验和 decision engine。
- `src/agent_knowledge_hub/quality_evaluators.py`：document/page/block/chunk 确定性 evaluator。
- `src/agent_knowledge_hub/quality_observe.py`：processed tree 评估、聚合、preview 和 bundle 输出。
- `schemas/knowledge-quality.v1/README.md`：Phase 1 Observe 契约说明。
- `schemas/knowledge-quality.v1/quality-policy.schema.json`：policy schema。
- `schemas/knowledge-quality.v1/quality-report.schema.json`：signal、decision 和 report schema。
- `schemas/knowledge-quality.v1/publication-preview.schema.json`：observe publication preview schema。
- `schemas/knowledge-quality.v1/quarantine-preview.schema.json`：observe quarantine preview schema。
- `tests/test_quality_models.py`：数据契约和确定性 ID 测试。
- `tests/test_quality_policy.py`：registry、policy 和 observe action 测试。
- `tests/test_quality_evaluators.py`：四层 evaluator 测试。
- `tests/test_quality_observe.py`：processed tree、报告和 preview 测试。
- `tests/test_quality_observe_cli.py`：CLI 端到端测试。
- `tests/fixtures/quality/cases.json`：厂商无关 Golden case 定义。

修改：

- `src/agent_knowledge_hub/cli.py`：增加 `evaluate-quality` 命令。
- `tests/test_schema_contracts.py`：检查 Phase 1 schema 文件和版本常量。
- `docs/知识库前处理与检索说明.md`：增加 observe 评估命令和产物说明。

明确不修改：

- `src/agent_knowledge_hub/quality.py`
- `src/agent_knowledge_hub/retrieval.py`
- `src/agent_knowledge_hub/release_manifest.py`
- `src/agent_knowledge_hub/release_pipeline.py`
- `src/agent_knowledge_hub/fts_index.py`
- `src/agent_knowledge_hub/vector_index.py`

---

### Task 1: Phase 1质量数据契约与Schema

**Files:**

- Create: `src/agent_knowledge_hub/quality_models.py`
- Create: `schemas/knowledge-quality.v1/README.md`
- Create: `schemas/knowledge-quality.v1/quality-policy.schema.json`
- Create: `schemas/knowledge-quality.v1/quality-report.schema.json`
- Create: `schemas/knowledge-quality.v1/publication-preview.schema.json`
- Create: `schemas/knowledge-quality.v1/quarantine-preview.schema.json`
- Create: `tests/test_quality_models.py`
- Modify: `tests/test_schema_contracts.py`

**Interfaces:**

- Produces: `KNOWLEDGE_QUALITY_SCHEMA_VERSION = "knowledge-quality.v1"`
- Produces: `QUALITY_REPORT_SCHEMA_VERSION = "knowledge-quality-report.v1"`
- Produces: `QUALITY_POLICY_SCHEMA_VERSION = "knowledge-quality-policy.v1"`
- Produces: `PUBLICATION_PREVIEW_SCHEMA_VERSION = "knowledge-publication-preview.v1"`
- Produces: `QUARANTINE_PREVIEW_SCHEMA_VERSION = "knowledge-quarantine-preview.v1"`
- Produces: `ObservedQualitySignal`
- Produces: `QualityPolicyRule`
- Produces: `QualityPolicy`
- Produces: `QualityDecision`
- Produces: `QualityReport`
- Produces: `PublicationPreview`
- Produces: `QuarantinePreview`

- [ ] **Step 1: Write failing model and schema tests**

```python
# tests/test_quality_models.py
from agent_knowledge_hub.quality_models import (
    ObservedQualitySignal,
    QualityDecision,
)


def test_signal_id_is_deterministic_and_excludes_message_copy():
    first = ObservedQualitySignal.create(
        reason_code="chunk.evidence.reference_missing",
        scope="chunk",
        object_id="chunk_1",
        detector="chunk-integrity",
        detector_version="1",
        metric_name="missing_evidence_count",
        actual_value=1,
        threshold=0,
        confidence=1.0,
        severity="error",
        document_version_id="docver_1",
        chunk_id="chunk_1",
        evidence_ids=("span_missing",),
        message="first wording",
    )
    second = ObservedQualitySignal.create(
        reason_code="chunk.evidence.reference_missing",
        scope="chunk",
        object_id="chunk_1",
        detector="chunk-integrity",
        detector_version="1",
        metric_name="missing_evidence_count",
        actual_value=1,
        threshold=0,
        confidence=1.0,
        severity="error",
        document_version_id="docver_1",
        chunk_id="chunk_1",
        evidence_ids=("span_missing",),
        message="translated wording",
    )

    assert first.signal_id == second.signal_id
    assert first.to_dict()["message"] == "first wording"


def test_observe_decision_keeps_recommended_and_effective_actions_separate():
    decision = QualityDecision.create(
        signal_ids=("signal_1",),
        policy_id="phase1-observe-default",
        policy_version="1",
        mode="observe",
        recommended_action="quarantine",
        effective_action="allow",
        scope="chunk",
        object_id="chunk_1",
        reason_codes=("chunk.evidence.reference_missing",),
        artifact_fingerprint="artifact_1",
    )

    assert decision.recommended_action == "quarantine"
    assert decision.effective_action == "allow"
    assert decision.decision_id.startswith("decision_")
```

Add schema assertions:

```python
# append to tests/test_schema_contracts.py
from agent_knowledge_hub.quality_models import (
    KNOWLEDGE_QUALITY_SCHEMA_VERSION,
    PUBLICATION_PREVIEW_SCHEMA_VERSION,
    QUALITY_POLICY_SCHEMA_VERSION,
    QUALITY_REPORT_SCHEMA_VERSION,
    QUARANTINE_PREVIEW_SCHEMA_VERSION,
)

QUALITY_SCHEMA_DIR = REPO_ROOT / "schemas" / KNOWLEDGE_QUALITY_SCHEMA_VERSION


def test_knowledge_quality_schema_files_and_versions():
    expected = {
        "quality-policy.schema.json": QUALITY_POLICY_SCHEMA_VERSION,
        "quality-report.schema.json": QUALITY_REPORT_SCHEMA_VERSION,
        "publication-preview.schema.json": PUBLICATION_PREVIEW_SCHEMA_VERSION,
        "quarantine-preview.schema.json": QUARANTINE_PREVIEW_SCHEMA_VERSION,
    }
    assert (QUALITY_SCHEMA_DIR / "README.md").is_file()
    for name, version in expected.items():
        payload = json.loads((QUALITY_SCHEMA_DIR / name).read_text(encoding="utf-8"))
        assert payload["properties"]["schema_version"]["const"] == version
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_quality_models.py tests/test_schema_contracts.py -q
```

Expected: collection fails because `agent_knowledge_hub.quality_models` does not exist.

- [ ] **Step 3: Implement immutable model types and stable factories**

```python
# src/agent_knowledge_hub/quality_models.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agent_knowledge_hub.utils import stable_id

KNOWLEDGE_QUALITY_SCHEMA_VERSION = "knowledge-quality.v1"
QUALITY_REPORT_SCHEMA_VERSION = "knowledge-quality-report.v1"
QUALITY_POLICY_SCHEMA_VERSION = "knowledge-quality-policy.v1"
PUBLICATION_PREVIEW_SCHEMA_VERSION = "knowledge-publication-preview.v1"
QUARANTINE_PREVIEW_SCHEMA_VERSION = "knowledge-quarantine-preview.v1"

QUALITY_SCOPES = frozenset({"document", "page", "block", "chunk", "release"})
QUALITY_SEVERITIES = frozenset({"info", "warning", "error", "fatal"})
QUALITY_ACTIONS = frozenset(
    {"allow", "warn", "quarantine", "block_document", "block_release"}
)
QUALITY_MODES = frozenset({"observe", "candidate_enforce", "production_enforce"})

JsonScalar = str | int | float | bool | None


@dataclass(frozen=True)
class ObservedQualitySignal:
    signal_id: str
    reason_code: str
    scope: str
    object_id: str
    detector: str
    detector_version: str
    metric_name: str
    actual_value: JsonScalar
    threshold: JsonScalar
    confidence: float
    severity: str
    document_version_id: str
    page: int | None = None
    block_id: str | None = None
    chunk_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    message: str = ""

    @classmethod
    def create(cls, **values: Any) -> "ObservedQualitySignal":
        payload = dict(values)
        evidence_ids = tuple(
            sorted(str(item) for item in payload.pop("evidence_ids", ()))
        )
        signal_id = stable_id(
            "signal",
            payload["reason_code"],
            payload["scope"],
            payload["object_id"],
            payload["detector"],
            payload["detector_version"],
            payload["metric_name"],
            payload.get("actual_value"),
            payload.get("threshold"),
            payload["document_version_id"],
            payload.get("page"),
            payload.get("block_id"),
            payload.get("chunk_id"),
            *evidence_ids,
        )
        return cls(signal_id=signal_id, evidence_ids=evidence_ids, **payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityPolicyRule:
    reason_code: str
    severity: str
    recommended_action: str


@dataclass(frozen=True)
class QualityPolicy:
    schema_version: str
    policy_id: str
    policy_version: str
    mode: str
    rules: tuple[QualityPolicyRule, ...]
    policy_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityDecision:
    decision_id: str
    signal_ids: tuple[str, ...]
    policy_id: str
    policy_version: str
    mode: str
    recommended_action: str
    effective_action: str
    scope: str
    object_id: str
    reason_codes: tuple[str, ...]
    artifact_fingerprint: str

    @classmethod
    def create(cls, **values: Any) -> "QualityDecision":
        payload = dict(values)
        signal_ids = tuple(sorted(payload.pop("signal_ids")))
        reason_codes = tuple(sorted(payload.pop("reason_codes")))
        decision_id = stable_id(
            "decision",
            payload["policy_id"],
            payload["policy_version"],
            payload["mode"],
            payload["scope"],
            payload["object_id"],
            payload["recommended_action"],
            payload["effective_action"],
            payload["artifact_fingerprint"],
            *signal_ids,
            *reason_codes,
        )
        return cls(
            decision_id=decision_id,
            signal_ids=signal_ids,
            reason_codes=reason_codes,
            **payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

Continue in the same file with report/preview containers:

```python
@dataclass(frozen=True)
class QualityReport:
    schema_version: str
    policy_id: str
    policy_version: str
    policy_hash: str
    mode: str
    artifact_fingerprint: str
    determinism_fingerprint: str
    document_version_ids: tuple[str, ...]
    signals: tuple[ObservedQualitySignal, ...]
    decisions: tuple[QualityDecision, ...]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "signals": [item.to_dict() for item in self.signals],
            "decisions": [item.to_dict() for item in self.decisions],
        }


@dataclass(frozen=True)
class PublicationPreview:
    schema_version: str
    policy_id: str
    policy_version: str
    mode: str
    all_document_version_ids: tuple[str, ...]
    all_chunk_ids: tuple[str, ...]
    would_exclude_document_version_ids: tuple[str, ...]
    would_exclude_chunk_ids: tuple[str, ...]
    decision_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuarantinePreview:
    schema_version: str
    policy_id: str
    policy_version: str
    mode: str
    items: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] **Step 4: Add strict JSON schemas**

All four schemas use JSON Schema 2020-12, `additionalProperties: false`, and require every dataclass field.

The policy schema requires:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://ai-knowledge-foundation.local/schemas/knowledge-quality.v1/quality-policy.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "policy_id", "policy_version", "mode", "rules", "policy_hash"],
  "properties": {
    "schema_version": {"const": "knowledge-quality-policy.v1"},
    "policy_id": {"type": "string", "minLength": 1},
    "policy_version": {"type": "string", "minLength": 1},
    "mode": {"const": "observe"},
    "rules": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["reason_code", "severity", "recommended_action"],
        "properties": {
          "reason_code": {"type": "string", "minLength": 1},
          "severity": {"enum": ["info", "warning", "error", "fatal"]},
          "recommended_action": {
            "enum": ["allow", "warn", "quarantine", "block_document", "block_release"]
          }
        }
      }
    },
    "policy_hash": {"type": "string", "minLength": 64, "maxLength": 64}
  }
}
```

In `quality-report.schema.json`, define reusable `$defs.signal` and `$defs.decision` matching the model fields exactly. Require `signals` and `decisions` arrays and restrict `mode` to `observe`.

In both preview schemas, require `mode="observe"` and sorted string arrays. `publication-preview` includes all/would-exclude ID arrays; `quarantine-preview.items` requires `scope`, `object_id`, `decision_id`, `reason_codes`, and `recommended_action`.

- [ ] **Step 5: Run model/schema tests**

Run:

```powershell
python -m pytest tests/test_quality_models.py tests/test_schema_contracts.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_knowledge_hub/quality_models.py schemas/knowledge-quality.v1 tests/test_quality_models.py tests/test_schema_contracts.py
git commit -m "feat: define phase one quality contracts"
```

---

### Task 2: Reason Registry与Observe Policy Engine

**Files:**

- Create: `src/agent_knowledge_hub/quality_registry.py`
- Create: `src/agent_knowledge_hub/quality_policy.py`
- Create: `tests/test_quality_policy.py`

**Interfaces:**

- Consumes: `ObservedQualitySignal`, `QualityPolicyRule`, `QualityPolicy`, `QualityDecision`
- Produces: `ReasonCodeDefinition`
- Produces: `REASON_CODE_REGISTRY`
- Produces: `build_default_observe_policy() -> QualityPolicy`
- Produces: `load_quality_policy(path: Path | None) -> QualityPolicy`
- Produces: `apply_quality_policy(signals, policy, artifact_fingerprint) -> tuple[QualityDecision, ...]`

- [ ] **Step 1: Write failing registry and policy tests**

```python
# tests/test_quality_policy.py
import json
from pathlib import Path

import pytest

from agent_knowledge_hub.quality_models import ObservedQualitySignal
from agent_knowledge_hub.quality_policy import (
    apply_quality_policy,
    build_default_observe_policy,
    load_quality_policy,
)
from agent_knowledge_hub.quality_registry import REASON_CODE_REGISTRY


def _signal(reason_code: str, *, severity: str = "error") -> ObservedQualitySignal:
    return ObservedQualitySignal.create(
        reason_code=reason_code,
        scope=REASON_CODE_REGISTRY[reason_code].scope,
        object_id="chunk_1",
        detector="test",
        detector_version="1",
        metric_name="count",
        actual_value=1,
        threshold=0,
        confidence=1.0,
        severity=severity,
        document_version_id="docver_1",
        chunk_id="chunk_1",
        message="fixture",
    )


def test_default_policy_recommends_quarantine_but_observe_effectively_allows():
    policy = build_default_observe_policy()
    decisions = apply_quality_policy(
        (_signal("chunk.evidence.reference_missing"),),
        policy,
        artifact_fingerprint="artifact_1",
    )

    assert decisions[0].recommended_action == "quarantine"
    assert decisions[0].effective_action == "allow"


def test_soft_signal_remains_warning_in_observe():
    policy = build_default_observe_policy()
    decisions = apply_quality_policy(
        (_signal("chunk.content.too_short", severity="warning"),),
        policy,
        artifact_fingerprint="artifact_1",
    )

    assert decisions[0].recommended_action == "warn"
    assert decisions[0].effective_action == "warn"


def test_unknown_reason_code_is_rejected():
    policy = build_default_observe_policy()
    unknown = ObservedQualitySignal.create(
        reason_code="chunk.unknown.rule",
        scope="chunk",
        object_id="chunk_1",
        detector="test",
        detector_version="1",
        metric_name="count",
        actual_value=1,
        threshold=0,
        confidence=1.0,
        severity="error",
        document_version_id="docver_1",
        chunk_id="chunk_1",
    )

    with pytest.raises(ValueError, match="unknown_reason_code:chunk.unknown.rule"):
        apply_quality_policy((unknown,), policy, artifact_fingerprint="artifact_1")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_quality_policy.py -q
```

Expected: collection fails because registry and policy modules do not exist.

- [ ] **Step 3: Implement the reason registry**

```python
# src/agent_knowledge_hub/quality_registry.py
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
    "document.integrity.chunks_missing": ReasonCodeDefinition(
        "document", "fatal", "block_document", True
    ),
    "document.integrity.no_chunks": ReasonCodeDefinition(
        "document", "fatal", "block_document", True
    ),
    "document.integrity.processing_record_missing": ReasonCodeDefinition(
        "document", "error", "block_document", True
    ),
    "document.integrity.quality_record_missing": ReasonCodeDefinition(
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
```

- [ ] **Step 4: Implement deterministic policy loading and decisions**

```python
# src/agent_knowledge_hub/quality_policy.py
from __future__ import annotations

import json
from pathlib import Path

from agent_knowledge_hub.quality_models import (
    QUALITY_ACTIONS,
    QUALITY_MODES,
    QUALITY_POLICY_SCHEMA_VERSION,
    QualityDecision,
    QualityPolicy,
    QualityPolicyRule,
    ObservedQualitySignal,
)
from agent_knowledge_hub.quality_registry import REASON_CODE_REGISTRY
from agent_knowledge_hub.utils import sha256_text


def _policy_hash(payload: dict[str, object]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(normalized)


def build_default_observe_policy() -> QualityPolicy:
    rules = tuple(
        QualityPolicyRule(
            reason_code=reason_code,
            severity=definition.severity,
            recommended_action=definition.recommended_action,
        )
        for reason_code, definition in sorted(REASON_CODE_REGISTRY.items())
    )
    identity = {
        "schema_version": QUALITY_POLICY_SCHEMA_VERSION,
        "policy_id": "phase1-observe-default",
        "policy_version": "1",
        "mode": "observe",
    }
    hash_payload = {
        **identity,
        "rules": [
            {
                "reason_code": item.reason_code,
                "severity": item.severity,
                "recommended_action": item.recommended_action,
            }
            for item in rules
        ],
    }
    return QualityPolicy(
        **identity,
        rules=rules,
        policy_hash=_policy_hash(hash_payload),
    )


def load_quality_policy(path: Path | None) -> QualityPolicy:
    if path is None:
        return build_default_observe_policy()
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if payload.get("schema_version") != QUALITY_POLICY_SCHEMA_VERSION:
        raise ValueError("unsupported_quality_policy_schema")
    if payload.get("mode") != "observe":
        raise ValueError("phase1_pr1_requires_observe_mode")
    rules = tuple(QualityPolicyRule(**item) for item in payload.get("rules") or [])
    seen: set[str] = set()
    for rule in rules:
        if rule.reason_code not in REASON_CODE_REGISTRY:
            raise ValueError(f"unknown_reason_code:{rule.reason_code}")
        if rule.reason_code in seen:
            raise ValueError(f"duplicate_policy_rule:{rule.reason_code}")
        if rule.severity != REASON_CODE_REGISTRY[rule.reason_code].severity:
            raise ValueError(f"policy_severity_mismatch:{rule.reason_code}")
        if rule.recommended_action not in QUALITY_ACTIONS:
            raise ValueError(f"unsupported_quality_action:{rule.recommended_action}")
        seen.add(rule.reason_code)
    base = {key: payload[key] for key in ("schema_version", "policy_id", "policy_version", "mode")}
    normalized = {**base, "rules": [item.__dict__ for item in rules]}
    expected_hash = _policy_hash(normalized)
    if payload.get("policy_hash") != expected_hash:
        raise ValueError("quality_policy_hash_mismatch")
    return QualityPolicy(**base, rules=rules, policy_hash=expected_hash)


def apply_quality_policy(
    signals: tuple[ObservedQualitySignal, ...],
    policy: QualityPolicy,
    *,
    artifact_fingerprint: str,
) -> tuple[QualityDecision, ...]:
    if policy.mode not in QUALITY_MODES:
        raise ValueError(f"unsupported_quality_mode:{policy.mode}")
    rules = {item.reason_code: item for item in policy.rules}
    decisions: list[QualityDecision] = []
    for signal in sorted(signals, key=lambda item: item.signal_id):
        if signal.reason_code not in REASON_CODE_REGISTRY:
            raise ValueError(f"unknown_reason_code:{signal.reason_code}")
        rule = rules.get(signal.reason_code)
        if rule is None:
            raise ValueError(f"missing_policy_rule:{signal.reason_code}")
        if rule.recommended_action not in QUALITY_ACTIONS:
            raise ValueError(f"unsupported_quality_action:{rule.recommended_action}")
        effective = "warn" if rule.recommended_action == "warn" else "allow"
        decisions.append(
            QualityDecision.create(
                signal_ids=(signal.signal_id,),
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                mode=policy.mode,
                recommended_action=rule.recommended_action,
                effective_action=effective,
                scope=signal.scope,
                object_id=signal.object_id,
                reason_codes=(signal.reason_code,),
                artifact_fingerprint=artifact_fingerprint,
            )
        )
    return tuple(sorted(decisions, key=lambda item: item.decision_id))
```

- [ ] **Step 5: Run policy tests**

Run:

```powershell
python -m pytest tests/test_quality_policy.py tests/test_quality_models.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_knowledge_hub/quality_registry.py src/agent_knowledge_hub/quality_policy.py tests/test_quality_policy.py
git commit -m "feat: add observe quality policy engine"
```

---

### Task 3: 四层确定性Quality Evaluators

**Files:**

- Create: `src/agent_knowledge_hub/quality_evaluators.py`
- Create: `tests/test_quality_evaluators.py`

**Interfaces:**

- Consumes: one processed document-version directory.
- Produces: `DocumentArtifacts`
- Produces: `evaluate_document_version(version_dir: Path) -> tuple[ObservedQualitySignal, ...]`
- Produces: `_evaluate_document`, `_evaluate_pages`, `_evaluate_blocks`, `_evaluate_chunks`
- Produces: `artifact_fingerprint(artifacts: DocumentArtifacts) -> str`

- [ ] **Step 1: Write failing document/chunk integrity tests**

```python
# tests/test_quality_evaluators.py
import json
from pathlib import Path

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.quality_evaluators import evaluate_document_version
from agent_knowledge_hub.utils import write_json


def _ingest(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "healthy.md"
    source.write_text("# API\n\nMsgSend sends a message.", encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title="Healthy API",
        document_version="v1",
    )


def _reason_codes(version_dir: Path) -> set[str]:
    return {item.reason_code for item in evaluate_document_version(version_dir)}


def test_healthy_document_has_no_hard_integrity_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    signals = evaluate_document_version(result.output_dir)

    assert not {
        item.reason_code
        for item in signals
        if item.severity in {"error", "fatal"}
    }


def test_missing_chunks_is_document_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    result.chunks_jsonl_path.unlink()

    assert "document.integrity.chunks_missing" in _reason_codes(result.output_dir)


def test_unknown_chunk_evidence_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    rows = [
        json.loads(line)
        for line in result.chunks_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["evidence_ids"] = ["span_missing"]
    result.chunks_jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    assert "chunk.evidence.reference_missing" in _reason_codes(result.output_dir)
```

- [ ] **Step 2: Write failing page/block tests**

```python
def test_block_page_outside_declared_count_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["parse_report"]["page_count"] = 1
    payload["blocks"][0]["page_start"] = 2
    payload["blocks"][0]["page_end"] = 2
    write_json(result.document_json_path, payload)

    assert "page.integrity.reference_out_of_range" in _reason_codes(result.output_dir)


def test_empty_block_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["blocks"][0]["text"] = ""
    write_json(result.document_json_path, payload)

    assert "block.integrity.empty" in _reason_codes(result.output_dir)


def test_evidence_hash_mismatch_is_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    payload["evidence_spans"][0]["text_hash"] = "0" * 64
    write_json(result.document_json_path, payload)

    assert "block.evidence.hash_mismatch" in _reason_codes(result.output_dir)


def test_quality_sidecar_version_mismatch_is_document_hard_signal(tmp_path: Path):
    result = _ingest(tmp_path)
    payload = json.loads(result.quality_record_path.read_text(encoding="utf-8"))
    payload["document_version_id"] = "docver_other"
    write_json(result.quality_record_path, payload)

    assert (
        "document.integrity.document_version_mismatch"
        in _reason_codes(result.output_dir)
    )
```

- [ ] **Step 3: Run evaluator tests and verify RED**

Run:

```powershell
python -m pytest tests/test_quality_evaluators.py -q
```

Expected: collection fails because `quality_evaluators` does not exist.

- [ ] **Step 4: Implement safe artifact loading**

```python
# src/agent_knowledge_hub/quality_evaluators.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.quality_models import ObservedQualitySignal
from agent_knowledge_hub.quality_registry import REASON_CODE_REGISTRY
from agent_knowledge_hub.utils import file_sha256, sha256_text, stable_id

EVALUATOR_VERSION = "phase1-observe-v1"
VALID_BLOCK_TYPES = frozenset({"heading", "paragraph", "table", "code"})
SOFT_MIN_DOCUMENT_CHARS = 40
SOFT_MIN_PAGE_CHARS = 10
SOFT_MAX_BLOCK_CHARS = 20_000
SOFT_MIN_CHUNK_CHARS = 10
SOFT_MAX_CHUNK_CHARS = 8_000
SOFT_WARNING_COUNT = 10


@dataclass(frozen=True)
class DocumentArtifacts:
    version_dir: Path
    canonical_path: Path
    chunks_path: Path
    processing_record_path: Path
    quality_record_path: Path
    canonical: dict[str, Any] | None
    chunks: tuple[dict[str, Any], ...]
    processing_record: dict[str, Any] | None
    quality_record: dict[str, Any] | None
    document_version_id: str
    load_errors: tuple[str, ...]


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return tuple(rows)


def load_document_artifacts(version_dir: Path) -> DocumentArtifacts:
    root = version_dir.resolve()
    canonical_path = root / "canonical-document.json"
    chunks_path = root / "chunks.jsonl"
    processing_path = root / "processing-record.json"
    quality_path = root / "quality-record.json"
    canonical = _load_json(canonical_path)
    processing_record = _load_json(processing_path)
    quality_record = _load_json(quality_path)
    errors: list[str] = []
    if canonical_path.exists() and canonical is None:
        errors.append("canonical_invalid_json")
    try:
        chunks = _load_jsonl(chunks_path)
    except (OSError, json.JSONDecodeError):
        chunks = ()
        errors.append("chunks_invalid_json")
    version_id = str(
        ((canonical or {}).get("document_version") or {}).get("document_version_id")
        or root.name
    )
    return DocumentArtifacts(
        version_dir=root,
        canonical_path=canonical_path,
        chunks_path=chunks_path,
        processing_record_path=processing_path,
        quality_record_path=quality_path,
        canonical=canonical,
        chunks=chunks,
        processing_record=processing_record,
        quality_record=quality_record,
        document_version_id=version_id,
        load_errors=tuple(sorted(errors)),
    )


def artifact_fingerprint(artifacts: DocumentArtifacts) -> str:
    parts = [artifacts.document_version_id]
    for path in (
        artifacts.canonical_path,
        artifacts.chunks_path,
        artifacts.processing_record_path,
        artifacts.quality_record_path,
    ):
        parts.append(file_sha256(path) if path.exists() else "missing")
    return stable_id("artifact", *parts)
```

- [ ] **Step 5: Implement signal factory and four evaluators**

Use one factory so every reason code gets registry-controlled scope and severity:

```python
def _signal(
    reason_code: str,
    *,
    artifacts: DocumentArtifacts,
    object_id: str,
    detector: str,
    metric_name: str,
    actual_value: str | int | float | bool | None,
    threshold: str | int | float | bool | None,
    page: int | None = None,
    block_id: str | None = None,
    chunk_id: str | None = None,
    evidence_ids: tuple[str, ...] = (),
    message: str = "",
) -> ObservedQualitySignal:
    definition = REASON_CODE_REGISTRY[reason_code]
    return ObservedQualitySignal.create(
        reason_code=reason_code,
        scope=definition.scope,
        object_id=object_id,
        detector=detector,
        detector_version=EVALUATOR_VERSION,
        metric_name=metric_name,
        actual_value=actual_value,
        threshold=threshold,
        confidence=1.0 if definition.hard else 0.75,
        severity=definition.severity,
        document_version_id=artifacts.document_version_id,
        page=page,
        block_id=block_id,
        chunk_id=chunk_id,
        evidence_ids=evidence_ids,
        message=message,
    )
```

Document evaluator requirements:

```python
def _evaluate_document(artifacts: DocumentArtifacts) -> list[ObservedQualitySignal]:
    signals: list[ObservedQualitySignal] = []
    version_id = artifacts.document_version_id
    if not artifacts.canonical_path.exists() or artifacts.canonical is None:
        signals.append(_signal(
            "document.integrity.canonical_missing",
            artifacts=artifacts,
            object_id=version_id,
            detector="document-integrity",
            metric_name="canonical_available",
            actual_value=False,
            threshold=True,
        ))
        return signals
    if not artifacts.chunks_path.exists():
        signals.append(_signal(
            "document.integrity.chunks_missing",
            artifacts=artifacts,
            object_id=version_id,
            detector="document-integrity",
            metric_name="chunks_available",
            actual_value=False,
            threshold=True,
        ))
    elif not artifacts.chunks:
        signals.append(_signal(
            "document.integrity.no_chunks",
            artifacts=artifacts,
            object_id=version_id,
            detector="document-integrity",
            metric_name="chunk_count",
            actual_value=0,
            threshold=1,
        ))
    for path, code in (
        (artifacts.processing_record_path, "document.integrity.processing_record_missing"),
        (artifacts.quality_record_path, "document.integrity.quality_record_missing"),
    ):
        if not path.exists():
            signals.append(_signal(
                code,
                artifacts=artifacts,
                object_id=version_id,
                detector="document-integrity",
                metric_name="sidecar_available",
                actual_value=False,
                threshold=True,
            ))
    for record_name, record in (
        ("processing_record", artifacts.processing_record),
        ("quality_record", artifacts.quality_record),
    ):
        if record is not None:
            actual_version = str(record.get("document_version_id") or "")
            if actual_version != version_id:
                signals.append(_signal(
                    "document.integrity.document_version_mismatch",
                    artifacts=artifacts,
                    object_id=version_id,
                    detector="document-integrity",
                    metric_name=f"{record_name}_document_version_id",
                    actual_value=actual_version,
                    threshold=version_id,
                ))
    blocks = artifacts.canonical.get("blocks") or []
    char_count = sum(len(str(item.get("text") or "")) for item in blocks)
    if char_count < SOFT_MIN_DOCUMENT_CHARS:
        signals.append(_signal(
            "document.content.text_too_short",
            artifacts=artifacts,
            object_id=version_id,
            detector="document-content",
            metric_name="text_character_count",
            actual_value=char_count,
            threshold=SOFT_MIN_DOCUMENT_CHARS,
        ))
    return signals
```

Block/page/chunk evaluators must implement the exact reason codes asserted by tests:

- Build `evidence_by_block` and `evidence_by_id`.
- Attach the block's evidence ID to every block-level signal.
- Attach all evidence IDs located on the page to every page-level hard signal.
- Verify each evidence `text_hash == sha256_text(evidence.text)`.
- Verify block type and document version.
- Verify page ranges are positive, ordered, and no greater than `parse_report.page_count` when page count exists.
- Emit `page.integrity.source_location_missing` only when `page_count` is known and a non-empty block has neither a valid page range nor a resolvable evidence span; do not apply it to Markdown/text documents with `page_count=None`.
- Emit one page out-of-range signal per unique page/object, not one duplicate per detector pass.
- Verify chunk text, document version, evidence presence and evidence references.
- Emit soft too-short/too-long signals using module constants.
- Detect exact duplicate block/chunk text by normalized text hash; emit duplicate signals only for the second and later object IDs in sorted order.

Public entry:

```python
def evaluate_document_version(
    version_dir: Path,
) -> tuple[ObservedQualitySignal, ...]:
    artifacts = load_document_artifacts(version_dir)
    signals = [
        *_evaluate_document(artifacts),
        *_evaluate_pages(artifacts),
        *_evaluate_blocks(artifacts),
        *_evaluate_chunks(artifacts),
    ]
    return tuple(sorted(signals, key=lambda item: item.signal_id))
```

- [ ] **Step 6: Add determinism and supplier-neutral tests**

```python
def test_repeated_evaluation_is_identical(tmp_path: Path):
    result = _ingest(tmp_path)

    first = evaluate_document_version(result.output_dir)
    second = evaluate_document_version(result.output_dir)

    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]


def test_same_defect_has_same_reason_for_different_suppliers(tmp_path: Path):
    first = _ingest(tmp_path / "qnx")
    second = _ingest(tmp_path / "qualcomm")
    for result, supplier in ((first, "QNX"), (second, "Qualcomm")):
        payload = json.loads(result.document_json_path.read_text(encoding="utf-8"))
        payload["document"]["supplier"] = supplier
        payload["evidence_spans"][0]["text_hash"] = "0" * 64
        write_json(result.document_json_path, payload)

    first_codes = _reason_codes(first.output_dir)
    second_codes = _reason_codes(second.output_dir)

    assert "block.evidence.hash_mismatch" in first_codes
    assert first_codes == second_codes
```

- [ ] **Step 7: Run evaluator tests**

Run:

```powershell
python -m pytest tests/test_quality_evaluators.py tests/test_quality_policy.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add src/agent_knowledge_hub/quality_evaluators.py tests/test_quality_evaluators.py
git commit -m "feat: evaluate four-layer knowledge quality"
```

---

### Task 4: Observe Orchestrator与报告Bundle

**Files:**

- Create: `src/agent_knowledge_hub/quality_observe.py`
- Create: `tests/test_quality_observe.py`

**Interfaces:**

- Consumes: processed root and optional policy path.
- Produces: `QualityObservationResult`
- Produces: `evaluate_processed_dir_observe(processed_dir, policy_path=None) -> QualityObservationResult`
- Produces: `write_quality_observation_bundle(output_dir, result) -> dict[str, Path]`
- Bundle files: `quality-report.json`, `quality-report.md`, `publication-preview.json`, `quarantine-preview.json`

- [ ] **Step 1: Write failing orchestration tests**

```python
# tests/test_quality_observe.py
import json
from pathlib import Path

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.quality_observe import (
    evaluate_processed_dir_observe,
    write_quality_observation_bundle,
)


def _ingest(tmp_path: Path, name: str, text: str):
    source = tmp_path / f"{name}.md"
    source.write_text(text, encoding="utf-8")
    return ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title=name,
        document_version="v1",
    )


def test_observe_keeps_all_chunks_but_records_would_exclude(tmp_path: Path):
    healthy = _ingest(tmp_path, "healthy", "# Healthy\n\nEnough healthy content.")
    broken = _ingest(tmp_path, "broken", "# Broken\n\nBroken evidence content.")
    rows = [
        json.loads(line)
        for line in broken.chunks_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["evidence_ids"] = ["span_missing"]
    broken.chunks_jsonl_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = evaluate_processed_dir_observe(tmp_path / "processed")

    all_chunk_ids = {
        json.loads(line)["chunk_id"]
        for path in (healthy.chunks_jsonl_path, broken.chunks_jsonl_path)
        for line in path.read_text(encoding="utf-8").splitlines()
    }
    assert set(result.publication_preview.all_chunk_ids) == all_chunk_ids
    assert set(result.publication_preview.would_exclude_chunk_ids)
    assert all(
        decision.effective_action in {"allow", "warn"}
        for decision in result.report.decisions
    )


def test_observe_result_is_deterministic(tmp_path: Path):
    _ingest(tmp_path, "healthy", "# Healthy\n\nEnough healthy content.")

    first = evaluate_processed_dir_observe(tmp_path / "processed")
    second = evaluate_processed_dir_observe(tmp_path / "processed")

    assert first.report.to_dict() == second.report.to_dict()
    assert first.publication_preview.to_dict() == second.publication_preview.to_dict()
    assert first.quarantine_preview.to_dict() == second.quarantine_preview.to_dict()


def test_block_quarantine_preview_propagates_to_referencing_chunk(tmp_path: Path):
    result = _ingest(tmp_path, "broken", "# Broken\n\nEvidence content.")
    canonical = json.loads(result.document_json_path.read_text(encoding="utf-8"))
    canonical["evidence_spans"][0]["text_hash"] = "0" * 64
    result.document_json_path.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    chunk_id = json.loads(
        result.chunks_jsonl_path.read_text(encoding="utf-8").splitlines()[0]
    )["chunk_id"]

    observation = evaluate_processed_dir_observe(tmp_path / "processed")

    assert chunk_id in observation.publication_preview.would_exclude_chunk_ids
    assert any(
        item["scope"] == "chunk" and item["object_id"] == chunk_id
        for item in observation.quarantine_preview.items
    )
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_quality_observe.py -q
```

Expected: collection fails because `quality_observe` does not exist.

- [ ] **Step 3: Implement deterministic processed-tree orchestration**

```python
# src/agent_knowledge_hub/quality_observe.py
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.quality_evaluators import (
    artifact_fingerprint,
    evaluate_document_version,
    load_document_artifacts,
)
from agent_knowledge_hub.quality_models import (
    PUBLICATION_PREVIEW_SCHEMA_VERSION,
    QUALITY_REPORT_SCHEMA_VERSION,
    QUARANTINE_PREVIEW_SCHEMA_VERSION,
    ObservedQualitySignal,
    PublicationPreview,
    QualityReport,
    QuarantinePreview,
)
from agent_knowledge_hub.quality_policy import apply_quality_policy, load_quality_policy
from agent_knowledge_hub.quality_registry import REASON_CODE_REGISTRY
from agent_knowledge_hub.utils import file_sha256, sha256_text, write_json


@dataclass(frozen=True)
class QualityObservationResult:
    processed_dir: Path
    report: QualityReport
    publication_preview: PublicationPreview
    quarantine_preview: QuarantinePreview
    markdown: str


def _fingerprint_payload(payload: object) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(normalized)


def _evaluate_ingest_failures(root: Path) -> tuple[ObservedQualitySignal, ...]:
    summary_path = root / "ingest-summary.json"
    if not summary_path.exists():
        return ()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    signals: list[ObservedQualitySignal] = []
    for index, failed in enumerate(payload.get("failed") or []):
        reason = str(failed.get("reason") or "")
        lowered = reason.lower()
        reason_code = (
            "document.parse.unsupported"
            if "unsupported document format" in lowered
            else "document.parse.failed"
        )
        object_id = str(
            failed.get("sample_id")
            or failed.get("file_path")
            or f"failed-input-{index}"
        )
        definition = REASON_CODE_REGISTRY[reason_code]
        signals.append(
            ObservedQualitySignal.create(
                reason_code=reason_code,
                scope=definition.scope,
                object_id=object_id,
                detector="ingest-failure",
                detector_version="phase1-observe-v1",
                metric_name="ingest_succeeded",
                actual_value=False,
                threshold=True,
                confidence=1.0,
                severity=definition.severity,
                document_version_id="",
                message=reason,
            )
        )
    return tuple(sorted(signals, key=lambda item: item.signal_id))
```

Evaluation algorithm:

```python
def evaluate_processed_dir_observe(
    processed_dir: Path | str,
    policy_path: Path | None = None,
) -> QualityObservationResult:
    root = Path(processed_dir).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {root}")
    policy = load_quality_policy(policy_path)
    version_dirs = sorted(
        {path.parent for path in root.rglob("canonical-document.json")}
        | {path.parent for path in root.rglob("chunks.jsonl")},
        key=lambda path: path.as_posix(),
    )
    signals = []
    document_ids: list[str] = []
    all_chunk_ids: list[str] = []
    artifact_parts: list[str] = []
    loaded_artifacts = []
    ingest_summary_path = root / "ingest-summary.json"
    if ingest_summary_path.exists():
        artifact_parts.append(file_sha256(ingest_summary_path))
    signals.extend(_evaluate_ingest_failures(root))
    for version_dir in version_dirs:
        artifacts = load_document_artifacts(version_dir)
        loaded_artifacts.append(artifacts)
        document_ids.append(artifacts.document_version_id)
        artifact_parts.append(artifact_fingerprint(artifacts))
        all_chunk_ids.extend(
            str(item.get("chunk_id"))
            for item in artifacts.chunks
            if item.get("chunk_id")
        )
        signals.extend(evaluate_document_version(version_dir))
    if not version_dirs:
        definition = REASON_CODE_REGISTRY["release.integrity.no_documents"]
        signals.append(
            ObservedQualitySignal.create(
                reason_code="release.integrity.no_documents",
                scope=definition.scope,
                object_id="processed-tree",
                detector="release-integrity",
                detector_version="phase1-observe-v1",
                metric_name="document_count",
                actual_value=0,
                threshold=1,
                confidence=1.0,
                severity=definition.severity,
                document_version_id="",
                message="Processed tree contains no document versions.",
            )
        )
    artifact_fp = _fingerprint_payload(sorted(artifact_parts))
    ordered_signals = tuple(sorted(signals, key=lambda item: item.signal_id))
    decisions = apply_quality_policy(
        ordered_signals,
        policy,
        artifact_fingerprint=artifact_fp,
    )
    would_exclude_docs = {
        decision.object_id
        for decision in decisions
        if decision.recommended_action == "block_document"
    }
    direct_exclude_chunks = {
        decision.object_id
        for decision in decisions
        if decision.scope == "chunk"
        and decision.recommended_action in {"quarantine", "block_document", "block_release"}
    }
    signal_by_id = {item.signal_id: item for item in ordered_signals}
    quarantined_evidence_ids: set[str] = set()
    source_decisions_by_evidence: dict[str, set[str]] = {}
    for decision in decisions:
        if decision.recommended_action not in {
            "quarantine", "block_document", "block_release"
        }:
            continue
        for signal_id in decision.signal_ids:
            signal = signal_by_id[signal_id]
            for evidence_id in signal.evidence_ids:
                quarantined_evidence_ids.add(evidence_id)
                source_decisions_by_evidence.setdefault(evidence_id, set()).add(
                    decision.decision_id
                )
    propagated_chunk_decisions: dict[str, set[str]] = {}
    would_exclude_chunks = set(direct_exclude_chunks)
    for artifacts in loaded_artifacts:
        for chunk in artifacts.chunks:
            chunk_id = str(chunk.get("chunk_id") or "")
            evidence_ids = {
                str(item) for item in chunk.get("evidence_ids") or []
            }
            if artifacts.document_version_id in would_exclude_docs:
                would_exclude_chunks.add(chunk_id)
                propagated_chunk_decisions.setdefault(chunk_id, set()).update(
                    decision.decision_id
                    for decision in decisions
                    if decision.scope == "document"
                    and decision.object_id == artifacts.document_version_id
                    and decision.recommended_action == "block_document"
                )
            for evidence_id in evidence_ids & quarantined_evidence_ids:
                would_exclude_chunks.add(chunk_id)
                propagated_chunk_decisions.setdefault(chunk_id, set()).update(
                    source_decisions_by_evidence[evidence_id]
                )
    direct_quarantine_items = [
        {
            "scope": decision.scope,
            "object_id": decision.object_id,
            "decision_id": decision.decision_id,
            "reason_codes": list(decision.reason_codes),
            "recommended_action": decision.recommended_action,
        }
        for decision in decisions
        if decision.recommended_action in {"quarantine", "block_document", "block_release"}
    ]
    decision_by_id = {item.decision_id: item for item in decisions}
    propagated_quarantine_items = [
        {
            "scope": "chunk",
            "object_id": chunk_id,
            "decision_id": decision_id,
            "reason_codes": list(decision_by_id[decision_id].reason_codes),
            "recommended_action": "quarantine",
        }
        for chunk_id, decision_ids in sorted(propagated_chunk_decisions.items())
        for decision_id in sorted(decision_ids)
    ]
    quarantine_items = tuple(
        sorted(
            [*direct_quarantine_items, *propagated_quarantine_items],
            key=lambda item: (item["scope"], item["object_id"], item["decision_id"]),
        )
    )
    summary_counter = Counter(decision.recommended_action for decision in decisions)
    summary_counter["signal_count"] = len(ordered_signals)
    summary_counter["decision_count"] = len(decisions)
    pre_report = {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_hash": policy.policy_hash,
        "mode": policy.mode,
        "artifact_fingerprint": artifact_fp,
        "document_version_ids": sorted(document_ids),
        "signals": [item.to_dict() for item in ordered_signals],
        "decisions": [item.to_dict() for item in decisions],
        "summary": dict(sorted(summary_counter.items())),
    }
    report = QualityReport(
        schema_version=QUALITY_REPORT_SCHEMA_VERSION,
        determinism_fingerprint=_fingerprint_payload(pre_report),
        document_version_ids=tuple(sorted(document_ids)),
        signals=ordered_signals,
        decisions=decisions,
        summary=dict(sorted(summary_counter.items())),
        **{key: pre_report[key] for key in (
            "policy_id", "policy_version", "policy_hash", "mode", "artifact_fingerprint"
        )},
    )
    publication = PublicationPreview(
        schema_version=PUBLICATION_PREVIEW_SCHEMA_VERSION,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        mode="observe",
        all_document_version_ids=tuple(sorted(document_ids)),
        all_chunk_ids=tuple(sorted(all_chunk_ids)),
        would_exclude_document_version_ids=tuple(sorted(would_exclude_docs)),
        would_exclude_chunk_ids=tuple(sorted(would_exclude_chunks)),
        decision_ids=tuple(sorted(item.decision_id for item in decisions)),
    )
    quarantine = QuarantinePreview(
        schema_version=QUARANTINE_PREVIEW_SCHEMA_VERSION,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        mode="observe",
        items=quarantine_items,
    )
    return QualityObservationResult(
        processed_dir=root,
        report=report,
        publication_preview=publication,
        quarantine_preview=quarantine,
        markdown=_render_observe_markdown(report, publication, quarantine),
    )
```

- [ ] **Step 4: Implement bundle writing**

```python
def write_quality_observation_bundle(
    output_dir: Path | str,
    result: QualityObservationResult,
) -> dict[str, Path]:
    root = Path(output_dir).resolve()
    paths = {
        "report_json": root / "quality-report.json",
        "report_markdown": root / "quality-report.md",
        "publication_preview": root / "publication-preview.json",
        "quarantine_preview": root / "quarantine-preview.json",
    }
    write_json(paths["report_json"], result.report.to_dict())
    write_json(paths["publication_preview"], result.publication_preview.to_dict())
    write_json(paths["quarantine_preview"], result.quarantine_preview.to_dict())
    paths["report_markdown"].parent.mkdir(parents=True, exist_ok=True)
    paths["report_markdown"].write_text(result.markdown, encoding="utf-8")
    return paths
```

Markdown contains:

- policy ID/version/mode.
- document/signal/decision counts.
- recommended action counts.
- would-exclude document/chunk counts.
- one sorted line per decision with scope, object ID, reason codes and recommended/effective action.

- [ ] **Step 5: Add malformed and empty-tree tests**

```python
def test_empty_processed_tree_records_would_block_release(tmp_path: Path):
    result = evaluate_processed_dir_observe(tmp_path)

    assert result.report.summary["signal_count"] == 1
    assert result.report.decisions[0].recommended_action == "block_release"
    assert result.report.decisions[0].effective_action == "allow"
    assert result.publication_preview.all_chunk_ids == ()


def test_ingest_failure_becomes_document_would_block(tmp_path: Path):
    (tmp_path / "ingest-summary.json").write_text(
        json.dumps({
            "failed": [{
                "sample_id": "bad-pdf",
                "file_path": "bad.pdf",
                "reason": "OCR parse failed",
            }]
        }),
        encoding="utf-8",
    )

    result = evaluate_processed_dir_observe(tmp_path)

    assert {
        decision.reason_codes[0] for decision in result.report.decisions
    } == {"document.parse.failed", "release.integrity.no_documents"}
    assert {
        decision.recommended_action for decision in result.report.decisions
    } == {"block_document", "block_release"}
    assert all(
        decision.effective_action == "allow"
        for decision in result.report.decisions
    )


def test_bundle_contains_all_four_files(tmp_path: Path):
    _ingest(tmp_path, "healthy", "# Healthy\n\nEnough healthy content.")
    result = evaluate_processed_dir_observe(tmp_path / "processed")

    paths = write_quality_observation_bundle(tmp_path / "report", result)

    assert set(paths) == {
        "report_json",
        "report_markdown",
        "publication_preview",
        "quarantine_preview",
    }
    assert all(path.is_file() for path in paths.values())
```

- [ ] **Step 6: Run orchestration tests**

Run:

```powershell
python -m pytest tests/test_quality_observe.py tests/test_quality_evaluators.py tests/test_quality_policy.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/agent_knowledge_hub/quality_observe.py tests/test_quality_observe.py
git commit -m "feat: generate observe quality reports"
```

---

### Task 5: Evaluate Quality CLI

**Files:**

- Modify: `src/agent_knowledge_hub/cli.py`
- Create: `tests/test_quality_observe_cli.py`
- Modify: `docs/知识库前处理与检索说明.md`

**Interfaces:**

- CLI: `evaluate-quality --processed-dir PATH --output-dir PATH [--policy-path PATH]`
- Exit 0: report successfully generated, including hard recommended actions because mode is observe.
- Exit 2: missing path or invalid policy through existing CLI error handling.

- [ ] **Step 1: Write failing CLI tests**

```python
# tests/test_quality_observe_cli.py
import json
from pathlib import Path

from agent_knowledge_hub.cli import main
from agent_knowledge_hub.pipeline import ingest_file


def test_evaluate_quality_cli_writes_observe_bundle(tmp_path: Path, capsys):
    source = tmp_path / "healthy.md"
    source.write_text("# Healthy\n\nEnough healthy content.", encoding="utf-8")
    ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title="Healthy",
        document_version="v1",
    )

    exit_code = main([
        "evaluate-quality",
        "--processed-dir", str(tmp_path / "processed"),
        "--output-dir", str(tmp_path / "quality"),
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "observe"
    assert payload["report_json"].endswith("quality-report.json")
    assert (tmp_path / "quality" / "publication-preview.json").is_file()


def test_evaluate_quality_cli_rejects_missing_processed_dir(tmp_path: Path, capsys):
    exit_code = main([
        "evaluate-quality",
        "--processed-dir", str(tmp_path / "missing"),
        "--output-dir", str(tmp_path / "quality"),
    ])

    assert exit_code == 2
    assert "Processed directory does not exist" in capsys.readouterr().err
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```powershell
python -m pytest tests/test_quality_observe_cli.py -q
```

Expected: argparse exits because `evaluate-quality` is not a registered command.

- [ ] **Step 3: Add CLI dispatch and parser**

Add imports:

```python
from agent_knowledge_hub.quality_observe import (
    evaluate_processed_dir_observe,
    write_quality_observation_bundle,
)
```

Dispatch before legacy parse-quality-summary:

```python
elif args.command == "evaluate-quality":
    result = evaluate_processed_dir_observe(
        args.processed_dir,
        policy_path=args.policy_path,
    )
    paths = write_quality_observation_bundle(args.output_dir, result)
    payload = {
        "schema_version": result.report.schema_version,
        "policy_id": result.report.policy_id,
        "policy_version": result.report.policy_version,
        "mode": result.report.mode,
        "determinism_fingerprint": result.report.determinism_fingerprint,
        **{key: str(value) for key, value in paths.items()},
    }
```

Parser:

```python
quality_observe_parser = subparsers.add_parser(
    "evaluate-quality",
    help="Evaluate processed artifacts in observe mode without changing publication.",
)
quality_observe_parser.add_argument("--processed-dir", required=True, type=Path)
quality_observe_parser.add_argument("--output-dir", required=True, type=Path)
quality_observe_parser.add_argument("--policy-path", type=Path)
```

- [ ] **Step 4: Document exact usage and non-enforcement**

Add:

```powershell
python -m agent_knowledge_hub.cli evaluate-quality `
  --processed-dir ".\data\processed" `
  --output-dir ".\data\quality-observe"
```

Document these guarantees:

- Command never changes release, indexes, active pointer or retrieval.
- `would_exclude_*` is diagnostic only.
- Existing `parse-quality-summary` remains available during migration.
- Candidate enforcement is a later PR.

- [ ] **Step 5: Run CLI and legacy quality tests**

Run:

```powershell
python -m pytest tests/test_quality_observe_cli.py tests/test_parse_quality_summary.py tests/test_quality_observe.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/agent_knowledge_hub/cli.py tests/test_quality_observe_cli.py docs/知识库前处理与检索说明.md
git commit -m "feat: expose observe quality evaluation CLI"
```

---

### Task 6: Golden Cases与PR 1验收回归

**Files:**

- Create: `tests/fixtures/quality/cases.json`
- Modify: `tests/test_quality_observe.py`
- Modify: `tests/test_quality_evaluators.py`

**Interfaces:**

- Fixture fields: `case_id`, `supplier`, `defect`, `expected_reason_codes`, `expected_hard_count`.
- Cases: healthy normal PDF-shaped artifact, QNX bad evidence, Qualcomm out-of-range page, supplier-neutral duplicate.

- [ ] **Step 1: Add Golden case definitions**

```json
[
  {
    "case_id": "healthy-normal",
    "supplier": "internal",
    "defect": "none",
    "expected_reason_codes": [],
    "expected_hard_count": 0
  },
  {
    "case_id": "qnx-missing-evidence",
    "supplier": "QNX",
    "defect": "missing_chunk_evidence",
    "expected_reason_codes": ["chunk.evidence.reference_missing"],
    "expected_hard_count": 1
  },
  {
    "case_id": "qualcomm-page-out-of-range",
    "supplier": "Qualcomm",
    "defect": "page_out_of_range",
    "expected_reason_codes": [
      "page.integrity.reference_out_of_range",
      "block.integrity.page_range_invalid"
    ],
    "expected_hard_count": 2
  },
  {
    "case_id": "supplier-neutral-duplicate",
    "supplier": "Other",
    "defect": "duplicate_chunk",
    "expected_reason_codes": ["chunk.content.duplicate"],
    "expected_hard_count": 0
  }
]
```

- [ ] **Step 2: Write fixture-driven failing test**

Add a helper that:

- Uses `ingest_file()` to create a valid processed version.
- Changes only the defect named by the case.
- Never branches on supplier to choose detector behavior.
- Evaluates the version directory.

```python
def test_golden_cases_match_expected_signals(tmp_path: Path):
    cases = json.loads(
        (Path(__file__).parent / "fixtures" / "quality" / "cases.json").read_text(
            encoding="utf-8"
        )
    )
    for case in cases:
        version_dir = _build_case(tmp_path / case["case_id"], case)
        signals = evaluate_document_version(version_dir)
        actual_codes = sorted({item.reason_code for item in signals})
        hard_count = sum(
            1 for item in signals if item.severity in {"error", "fatal"}
        )
        for expected in case["expected_reason_codes"]:
            assert expected in actual_codes, case["case_id"]
        assert hard_count == case["expected_hard_count"], case["case_id"]
```

- [ ] **Step 3: Run test and verify RED**

Run:

```powershell
python -m pytest tests/test_quality_evaluators.py::test_golden_cases_match_expected_signals -q
```

Expected: FAIL until duplicate soft signal and fixture mutations are fully implemented.

- [ ] **Step 4: Complete only the missing evaluator behavior**

Implement missing exact-duplicate detection with deterministic first-object retention:

```python
def _duplicate_object_ids(
    objects: list[tuple[str, str]],
) -> set[str]:
    first_by_hash: dict[str, str] = {}
    duplicates: set[str] = set()
    for object_id, text in sorted(objects):
        normalized = " ".join(text.split())
        digest = sha256_text(normalized)
        if digest in first_by_hash:
            duplicates.add(object_id)
        else:
            first_by_hash[digest] = object_id
    return duplicates
```

Use this helper for block and chunk duplicate soft signals.

- [ ] **Step 5: Run complete PR 1 focused suite**

Run:

```powershell
python -m pytest tests/test_quality_models.py tests/test_quality_policy.py tests/test_quality_evaluators.py tests/test_quality_observe.py tests/test_quality_observe_cli.py tests/test_schema_contracts.py tests/test_parse_quality_summary.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Run full repository verification**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass with no new warnings.

Run:

```powershell
python -m compileall -q src/agent_knowledge_hub
git diff --check origin/main..HEAD
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit**

```powershell
git add tests/fixtures/quality/cases.json tests/test_quality_evaluators.py tests/test_quality_observe.py
git commit -m "test: add phase one observe golden cases"
```

## PR 1 Completion Gate

PR 1 Observe 只有在以下条件全部满足后才完成：

- Signal、policy、decision、report 和 preview 契约有严格 schema。
- 默认 policy 只允许 observe mode。
- 所有 reason code 均已注册。
- 未知 reason code 和缺失 policy rule 稳定失败。
- 四层 evaluator 只读处理 Phase 0 artifacts。
- 相同 artifacts 与 policy 产生完全相同结果。
- 硬完整性缺陷产生 recommended quarantine/block。
- Observe effective action 不实际隔离或阻断。
- Publication preview 仍包含全部 chunk。
- Quality report 明确列出 would-exclude 对象。
- QNX 和 Qualcomm fixture 使用相同通用 detector。
- `evaluate-quality` CLI 不修改 release、索引或 retrieval。
- 现有 `parse-quality-summary` 和全量测试保持通过。

## Deferred to Later PRs

以下内容不得在执行本计划时顺带实现：

- `knowledge-release.v2`
- publication set 强制过滤
- quarantine manifest 强制执行
- FTS/vector index 过滤
- active v2 校验
- retrieval gate bypass 删除
- retrieval 全量 fallback 删除
- 邻接合并隔离边界
- production rollback
