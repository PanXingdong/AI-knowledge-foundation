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


def test_checker_flags_half_title_fragment_ratio():
    checker = _load_checker_module()
    records = [
        {
            "case_id": "A3",
            "parsed": {
                "evidence_items": [
                    {"summary": "Window types"},
                    {"summary": "This function creates a window object and returns a handle."},
                ]
            },
        }
    ]

    violations = checker.check_records(records)

    assert any(item["code"] == "title_fragment_evidence" for item in violations)


def test_checker_does_not_treat_short_sentence_as_title_fragment():
    checker = _load_checker_module()

    assert checker._looks_like_title_fragment("Screen completes composition.") is False


def test_checker_ignores_common_c_types_and_supports_wildcard_families():
    checker = _load_checker_module()
    record = {
        "case_id": "B4",
        "detail_card": "CACHE_FLUSH() and uint32_t are mentioned.",
        "evidence": "证据 1: QNX Guide\n原文: CACHE_* macros control cache behavior.",
        "parsed": {
            "answer_type": "api_usage",
            "details": [
                {"name": "CACHE_FLUSH()"},
                {"name": "uint32_t"},
            ],
            "evidence_items": [
                {"summary": "CACHE_* macros control cache behavior."}
            ],
        },
        "selected_chunks": [
            {"text": "CACHE_* macros control cache behavior."}
        ],
    }

    violations = checker.check_records([record])

    assert violations == []


def test_checker_main_handles_missing_file(capsys):
    checker = _load_checker_module()

    exit_code = checker.main(["missing-regression-file.json"])
    output = capsys.readouterr().out

    assert exit_code == 2
    assert '"passed": false' in output
    assert "missing-regression-file.json" in output
