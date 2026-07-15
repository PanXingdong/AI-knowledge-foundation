from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


TRACEABILITY_FAILURE_PATTERNS = (
    "trace failed",
    "Evidence not found",
    "无 evidence_refs",
    "span_xxx",
)


def check_records(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for record in records:
        case_id = str(record.get("case_id") or "unknown")
        combined_text = "\n".join(
            str(record.get(key) or "")
            for key in ("summary_card", "detail_card", "evidence")
        )
        if any(pattern in combined_text for pattern in TRACEABILITY_FAILURE_PATTERNS):
            violations.append(_violation(case_id, "traceability_failure", "evidence trace output contains a known failure marker"))
        if _has_double_numbered_step(combined_text):
            violations.append(_violation(case_id, "double_numbered_step", "solution steps contain model-generated numbering"))
        if _title_fragment_ratio(record) >= 0.5:
            violations.append(_violation(case_id, "title_fragment_evidence", "most evidence summaries look like title fragments"))
        if (record.get("parsed") or {}).get("answer_type") == "api_usage":
            for api in _core_api_terms_from_record(record):
                if _context_mentions_api(record, api) and not _evidence_mentions_api(record, api):
                    violations.append(_violation(case_id, "missing_core_api_evidence", f"answer mentions {api} but displayed evidence does not"))
    return violations


def _violation(case_id: str, code: str, message: str) -> dict[str, str]:
    return {"case_id": case_id, "code": code, "message": message}


def _has_double_numbered_step(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*\d+\.\s+(?:步骤\s*)?\d+\s*[.)、:：]", text))


def _title_fragment_ratio(record: dict[str, Any]) -> float:
    items = (record.get("parsed") or {}).get("evidence_items") or []
    if not items:
        return 0.0
    fragment_count = sum(
        1
        for item in items
        if _looks_like_title_fragment(str(item.get("summary") or item.get("why_relevant") or ""))
    )
    return fragment_count / len(items)


def _looks_like_title_fragment(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return True
    if re.search(r"[。.!?;；]", normalized):
        return False
    if len(normalized) > 48:
        return False
    if re.fullmatch(r"[A-Z0-9_./() -]{1,48}", normalized):
        return True
    if re.search(r"[\u4e00-\u9fff]", normalized):
        return len(normalized) <= 12
    return len(normalized.split()) <= 4


def _core_api_terms_from_record(record: dict[str, Any]) -> list[str]:
    parsed = record.get("parsed") or {}
    parts = []
    for item in parsed.get("details") or []:
        parts.append(str(item.get("name") or ""))
    return _core_api_terms(" ".join(parts))


def _core_api_terms(text: str) -> list[str]:
    terms = []
    terms.extend(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\s*(?=\()", text))
    terms.extend(re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", text))
    ignored = {
        item.lower()
        for item in (
            "bool", "char", "const", "demo", "false", "int", "main", "null",
            "return", "sizeof", "struct", "true", "uint32_t", "uint64_t", "void",
            "clock_gettime",
        )
    }
    return [
        term
        for term in dict.fromkeys(term.strip() for term in terms)
        if term and term.lower() not in ignored
    ][:20]


def _evidence_mentions_api(record: dict[str, Any], api: str) -> bool:
    parsed_items = (record.get("parsed") or {}).get("evidence_items") or []
    evidence_text = str(record.get("evidence") or "")
    haystack_parts = [evidence_text]
    for item in parsed_items:
        haystack_parts.extend(
            str(item.get(key) or "")
            for key in ("name", "source", "location", "why_relevant", "summary", "document_title")
        )
    haystack = "\n".join(haystack_parts).lower()
    if _wildcard_family_mentions(api, haystack):
        return True
    return api.lower() in haystack


def _wildcard_family_mentions(api: str, haystack: str) -> bool:
    if "_" not in api:
        return False
    family = api.split("_", 1)[0].lower()
    return f"{family}_*" in haystack


def _context_mentions_api(record: dict[str, Any], api: str) -> bool:
    chunks = record.get("selected_chunks") or []
    haystack_parts = []
    for chunk in chunks:
        haystack_parts.extend(
            [
                str(chunk.get("document_title") or ""),
                " ".join(str(item) for item in (chunk.get("section_titles") or [])),
                str(chunk.get("text") or ""),
            ]
        )
    return api.lower() in "\n".join(haystack_parts).lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check large-question regression output for known evidence quality failures.")
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args(argv)
    try:
        records = json.loads(args.json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    violations = check_records(records)
    if violations:
        print(json.dumps({"passed": False, "violations": violations}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"passed": True, "violations": []}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
