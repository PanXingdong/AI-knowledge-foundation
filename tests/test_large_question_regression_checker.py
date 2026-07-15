import importlib.util
from pathlib import Path


def _load_checker_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_large_question_regression.py"
    spec = importlib.util.spec_from_file_location("check_large_question_regression", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_checker_flags_trace_failures_and_double_numbering():
    checker = _load_checker_module()
    records = [
        {
            "case_id": "A4",
            "detail_card": "实施步骤\n1. 1. 创建上下文",
            "evidence": "证据 1: span_xxx trace failed: Evidence not found: span_xxx",
            "parsed": {
                "evidence_items": [
                    {"summary": "Window types", "evidence_ids": ["span_xxx"]},
                ]
            },
        }
    ]

    violations = checker.check_records(records)

    assert any(item["code"] == "traceability_failure" for item in violations)
    assert any(item["code"] == "double_numbered_step" for item in violations)


def test_checker_flags_missing_core_api_evidence():
    checker = _load_checker_module()
    records = [
        {
            "case_id": "A5",
            "detail_card": "使用 screen_wait_vsync() 统计帧率。",
            "evidence": "证据 1: QNX Screen Guide / page 161\n原文: Screen completes composition.",
            "parsed": {
                "answer_type": "api_usage",
                "details": [
                    {"name": "screen_wait_vsync()"},
                ],
                "evidence_items": [
                    {
                        "location": "Asynchronous Notifications / page 161",
                        "summary": "Screen completes composition.",
                        "evidence_ids": ["span_post"],
                    }
                ]
            },
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["screen_wait_vsync()"],
                    "text": "screen_wait_vsync() blocks until vsync.",
                }
            ],
        }
    ]

    violations = checker.check_records(records)

    assert any(item["code"] == "missing_core_api_evidence" for item in violations)


def test_checker_accepts_core_api_evidence_and_body_text():
    checker = _load_checker_module()
    records = [
        {
            "case_id": "A5",
            "detail_card": "使用 screen_wait_vsync() 统计帧率。",
            "evidence": "证据 1: QNX Screen Guide / page 560\n原文: screen_wait_vsync() blocks until vsync.",
            "parsed": {
                "answer_type": "api_usage",
                "details": [
                    {"name": "screen_wait_vsync()"},
                ],
                "evidence_items": [
                    {
                        "location": "screen_wait_vsync() / page 560",
                        "summary": "screen_wait_vsync() blocks until vsync.",
                        "evidence_ids": ["span_wait"],
                    }
                ]
            },
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["screen_wait_vsync()"],
                    "text": "screen_wait_vsync() blocks until vsync.",
                }
            ],
        }
    ]

    assert checker.check_records(records) == []
