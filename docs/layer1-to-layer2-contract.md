# Layer1 To Layer2 Contract

This document freezes the boundary between the document parsing layer and the retrieval / Context Pack layer.

Layer 1 owns document ingestion, parsing, canonical modeling, evidence spans, chunk generation, and parse quality reports.

Layer 2 owns retrieval, indexing, Context Pack assembly, evidence trace, and bot / agent consumption.

The contract is file-based in Phase 1:

```text
processed/
  <document_slug>/
    <document_version_id>/
      canonical-document.json
      chunks.jsonl
```

Layer 2 must be able to consume that directory without reading the original PDF, DOCX, HTML, or Markdown source file.

## Contract Status

Current status:

```text
implemented in code: yes
formally frozen: yes, as layer1.processed.v1
schema version field: required in canonical-document.json
```

Layer 2 rejects processed documents that omit `schema_version` or use an unsupported schema version.

## Golden Samples

To unblock Layer 2, we can manually create processed outputs that follow this contract.

Recommended split:

```text
samples/golden/
  public, synthetic, or desensitized contract samples

data/local/
  real internal processed outputs, ignored by git
```

Rules:

- Do not commit real supplier or internal confidential documents.
- Public golden samples must preserve structure but use synthetic or rewritten content.
- Golden samples must include both `canonical-document.json` and `chunks.jsonl`.
- A golden sample is valid only if `/api/context-pack`, `/api/search`, and `/api/evidence/{evidence_id}` can consume it.

Current public golden sample:

```text
samples/golden/demo-spec/docver_demo_v1/
```

Validate it with:

```powershell
python -m agent_knowledge_hub.cli validate-processed `
  --processed-dir ".\samples\golden" `
  --require-valid
```

## Required Files

Each processed document version must contain:

| File | Required | Producer | Consumer |
|---|---:|---|---|
| `canonical-document.json` | yes | Layer 1 | retrieval, trace, quality |
| `chunks.jsonl` | yes | Layer 1 | retrieval, FTS, vector index |

Layer 2 ignores any extra files in the same directory.

Versioned JSON Schema files are kept under:

```text
schemas/layer1.processed.v1/
  canonical-document.schema.json
  chunk.schema.json
```

## canonical-document.json

Top-level object:

```json
{
  "schema_version": "layer1.processed.v1",
  "document": {},
  "document_version": {},
  "sections": [],
  "blocks": [],
  "evidence_spans": [],
  "parse_report": {}
}
```

### schema_version

Contract version for this processed document shape.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `schema_version` | string | yes | Must be `layer1.processed.v1` |

### document

Logical document metadata.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `document_id` | string | yes | Stable logical id for the document |
| `title` | string | yes | Human-readable title |
| `source_type` | string | yes | Example: `supplier_spec`, `internal_spec`, `api_reference`, `test_spec` |
| `owner` | string | yes | Checker or owning person/team |
| `project` | string | yes | Use `unknown` only when genuinely unknown |
| `supplier` | string | yes | Example: `Qualcomm`, `Bosch`, `internal`, `unknown` |
| `created_at` | string | yes | ISO timestamp |

### document_version

Versioned file metadata. Version is mandatory because QNX, BSP, supplier, and internal specs can differ by version.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `document_version_id` | string | yes | Stable id for this exact version |
| `document_id` | string | yes | Must match `document.document_id` |
| `version` | string | yes | Example: `SDP 7.1`, `v1.3`, `2025-05 baseline` |
| `file_path` | string | yes | Original local path or source locator |
| `file_hash` | string | yes | SHA-256 of the source file when available |
| `created_at` | string | yes | ISO timestamp |

### sections

Document structure.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `section_id` | string | yes | Stable section id |
| `document_version_id` | string | yes | Must match this version |
| `section_path` | string[] | yes | Hierarchical path, e.g. `["1", "2"]` |
| `title` | string | yes | Section title |
| `page_start` | integer/null | yes | Null allowed for non-paginated sources |
| `page_end` | integer/null | yes | Null allowed for non-paginated sources |

### blocks

Ordered parsed blocks.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `block_id` | string | yes | Stable block id |
| `document_version_id` | string | yes | Must match this version |
| `block_type` | string | yes | `heading`, `paragraph`, `table`, `list`, `code`, `figure_caption`, `unknown` |
| `text` | string | yes | Normalized text for this block |
| `page_start` | integer/null | yes | Source page start |
| `page_end` | integer/null | yes | Source page end |
| `section_path` | string[] | yes | Must point to a known section path |
| `order` | integer | yes | 1-based source order |
| `metadata` | object | yes | Empty object allowed |

OCR and image-derived text may use optional block metadata:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `content_kind` | string | no | Use `ocr_text` for text recognized from an image or scanned page |
| `ocr` | boolean | no | `true` when the block text came from OCR |
| `ocr_engine` | string | no | Example: `rapidocr` |
| `ocr_lines` | object[] | no | OCR line objects with `text`, optional `confidence`, and optional `bbox` |
| `confidence` | number | no | Average OCR confidence for the block when available |
| `bbox` | number[] | no | Union bbox for this block in the unit named by `bbox_unit` |
| `bbox_unit` | string | no | Example: `pdf_points` for rendered PDF pages, `pixels` for image files |
| `media_ref` | string | no | Relative media asset path, e.g. `media/device-error.png` |
| `page_image_ref` | string | no | Page or image reference for visual trace-back |
| `media_type` | string | no | MIME type for the referenced media |

### evidence_spans

Traceable source evidence. Layer 2 uses this for `/api/evidence/{evidence_id}`.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `evidence_id` | string | yes | Stable span id |
| `document_version_id` | string | yes | Must match this version |
| `page` | integer/null | yes | Page where evidence starts |
| `section_path` | string[] | yes | Section path |
| `block_id` | string | yes | Must point to a known block |
| `bbox` | number[]/null | yes | `[x0, y0, x1, y1]` when available |
| `text` | string | yes | Evidence text |
| `text_hash` | string | yes | SHA-256 of `text` |
| `metadata` | object | no | Optional OCR/media trace metadata copied from the source block |

For OCR evidence, `bbox` should be the union of OCR line boxes when available. `metadata.page_image_ref` or `metadata.media_ref` tells consumers which page image or image asset the bbox belongs to. Existing text-only evidence can keep `bbox: null` and omit `metadata`.

### parse_report

Parser and quality metadata.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `parser_name` | string | yes | Parser identity |
| `source_format` | string | yes | `pdf`, `docx`, `markdown`, `html`, `txt`, etc. |
| `page_count` | integer/null | yes | Null allowed when not applicable |
| `section_count` | integer | yes | Count of sections |
| `block_count` | integer | yes | Count of blocks |
| `table_count` | integer | yes | Count of table blocks |
| `has_page_numbers` | boolean | yes | Whether page numbers are available |
| `warnings` | string[] | yes | Empty array allowed |
| `quality_report` | object | yes | See below |

Minimum `quality_report`:

```json
{
  "status": "ok",
  "score": 95.0,
  "fallback_used": false,
  "fallback_parser": null,
  "reason_codes": []
}
```

Supported quality statuses:

- `ok`
- `recovered_by_fallback`
- `low_quality`
- `unsupported`
- `ocr_unavailable`
- `failed`

Layer 2 allows Context Pack retrieval by default only when:

```text
quality_report.status in {ok, recovered_by_fallback}
and quality_report.score >= 40 when score exists
and chunks.jsonl exists
```

Blocked documents can still be traced and reported, but selected chunks must carry quality warnings and gate reasons.

## chunks.jsonl

Each line is one retrieval chunk JSON object.

Required fields:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `chunk_id` | string | yes | Stable chunk id |
| `document_version_id` | string | yes | Must match `canonical-document.json` |
| `section_path` | string[] | yes | Section path for the chunk |
| `page_start` | integer/null | yes | Source page start |
| `page_end` | integer/null | yes | Source page end |
| `text` | string | yes | Retrieval text |
| `evidence_ids` | string[] | yes | Must point to `evidence_spans` |
| `embedding_id` | string/null | yes | Null allowed in Phase 1 |
| `metadata` | object | yes | See below |

Minimum chunk metadata:

```json
{
  "document_id": "doc_xxx",
  "document_title": "Startup SPEC",
  "source_type": "internal_spec"
}
```

OCR/image chunks may add optional metadata while preserving the same required fields:

```json
{
  "ocr": true,
  "content_kind": "ocr_text",
  "content_kinds": ["ocr_text"],
  "media_refs": ["media/device-error.png"],
  "page_image_refs": ["media/device-error.png"],
  "media_types": ["image/png"]
}
```

Layer 2 also reads project, supplier, and version from `canonical-document.json`, so they do not need to be duplicated in every chunk.

## Image And OCR Inputs

Layer 1 supports OCR text as a text-first extension to the existing contract:

- Scanned PDF pages can produce `paragraph` blocks with `content_kind: ocr_text` and bbox metadata.
- Standalone image files such as PNG, JPEG, TIFF, and WebP are treated as single-page documents. The original image is copied into the processed document version under `media/`, and chunks continue to index the recognized text.
- Context Pack v1 remains text-first. Layer 2 should use OCR text for retrieval and use `/api/evidence/{evidence_id}` to recover bbox and image/page references when visual trace-back is needed.
- This does not define multimodal image embeddings or visual search. Those should be versioned separately if added later.

## Minimal Valid Example

`canonical-document.json`:

```json
{
  "schema_version": "layer1.processed.v1",
  "document": {
    "document_id": "doc_demo",
    "title": "Demo SPEC",
    "source_type": "internal_spec",
    "owner": "checker",
    "project": "demo",
    "supplier": "internal",
    "created_at": "2026-06-10T00:00:00Z"
  },
  "document_version": {
    "document_version_id": "docver_demo_v1",
    "document_id": "doc_demo",
    "version": "v1",
    "file_path": "samples/golden/demo-spec.md",
    "file_hash": "sha256_demo",
    "created_at": "2026-06-10T00:00:00Z"
  },
  "sections": [
    {
      "section_id": "sec_demo_1",
      "document_version_id": "docver_demo_v1",
      "section_path": ["1"],
      "title": "Safety Constraint",
      "page_start": 1,
      "page_end": 1
    }
  ],
  "blocks": [
    {
      "block_id": "blk_demo_1",
      "document_version_id": "docver_demo_v1",
      "block_type": "paragraph",
      "text": "Important data outbound transfer requires safety assessment.",
      "page_start": 1,
      "page_end": 1,
      "section_path": ["1"],
      "order": 1,
      "metadata": {}
    }
  ],
  "evidence_spans": [
    {
      "evidence_id": "span_demo_1",
      "document_version_id": "docver_demo_v1",
      "page": 1,
      "section_path": ["1"],
      "block_id": "blk_demo_1",
      "bbox": null,
      "text": "Important data outbound transfer requires safety assessment.",
      "text_hash": "sha256_text_demo"
    }
  ],
  "parse_report": {
    "parser_name": "manual-golden-sample",
    "source_format": "manual",
    "page_count": 1,
    "section_count": 1,
    "block_count": 1,
    "table_count": 0,
    "has_page_numbers": true,
    "warnings": [],
    "quality_report": {
      "status": "ok",
      "score": 100.0,
      "fallback_used": false,
      "fallback_parser": null,
      "reason_codes": []
    }
  }
}
```

`chunks.jsonl`:

```jsonl
{"chunk_id":"chunk_demo_1","document_version_id":"docver_demo_v1","section_path":["1"],"page_start":1,"page_end":1,"text":"Important data outbound transfer requires safety assessment.","evidence_ids":["span_demo_1"],"embedding_id":null,"metadata":{"document_id":"doc_demo","document_title":"Demo SPEC","source_type":"internal_spec"}}
```

## Validation Checklist

A Layer 1 output is valid when:

- `canonical-document.json` exists.
- `canonical-document.json.schema_version` equals `layer1.processed.v1`.
- `chunks.jsonl` exists.
- every chunk `document_version_id` matches the canonical document version.
- every chunk `evidence_ids[]` exists in `evidence_spans`.
- every evidence span `block_id` exists in `blocks`.
- every block and evidence span has a `section_path`.
- `document_version.version` is not empty or `unknown` for real samples.
- `document.supplier`, `document.project`, and `document.source_type` are filled for filterable samples.
- `parse_report.quality_report.status` is present.
- `/api/context-pack` can retrieve at least one relevant chunk.
- `/api/evidence/{evidence_id}` can trace selected evidence.

Run the validator:

```powershell
python -m agent_knowledge_hub.cli validate-processed `
  --processed-dir ".\data\processed" `
  --require-valid
```

For reports:

```powershell
python -m agent_knowledge_hub.cli validate-processed `
  --processed-dir ".\data\processed" `
  --output-dir ".\data\processed-contract-validation"
```

## Current Gaps

The contract is usable now, but these improvements should be added before a stable external release:

- connect JSON Schema validation to the runtime `validate-processed` command when we decide to add a schema validation dependency
- expand public golden samples beyond the current synthetic demo
- add real internal samples under ignored `data/local/`
