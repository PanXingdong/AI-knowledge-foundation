import json
from pathlib import Path

from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.retrieval import (
    _normalize_query_text,
    build_context_pack_for_processed_dir,
    trace_evidence_in_processed_dir,
)
from agent_knowledge_hub.vector_index import build_vector_index


def test_build_context_pack_retrieves_cross_document_constraints(tmp_path: Path):
    processed_root = tmp_path / "processed"

    architecture = tmp_path / "architecture.md"
    architecture.write_text(
        "\n".join(
            [
                "# 方案选型",
                "",
                "第一阶段正式方案采用第三种 runtime 模式。",
                "Skill/MCP 只适合短期 PoC。",
                "源码嵌入第一阶段不推荐。",
            ]
        ),
        encoding="utf-8",
    )
    safety = tmp_path / "safety.md"
    safety.write_text(
        "\n".join(
            [
                "# 安全治理",
                "",
                "默认不写主仓库。",
                "默认不开放无限网络。",
                "高风险动作必须审批。",
                "所有治理规则都必须进入运行前检查、运行中审计和运行后复盘，确保隔离策略不会被跳过。",
            ]
        ),
        encoding="utf-8",
    )
    rollback = tmp_path / "rollback.md"
    rollback.write_text(
        "\n".join(
            [
                "# 灰度与回滚",
                "",
                "第一步仅内部 tenant 开启。",
                "功能开关使用 ENABLE_CLAUDE_CODE_RUNTIME=false。",
                "router 停止分发到 claude_code。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=architecture,
        out_dir=processed_root,
        title="架构设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=safety,
        out_dir=processed_root,
        title="安全治理",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=rollback,
        out_dir=processed_root,
        title="灰度与回滚",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "如果第一阶段只给一个内部 tenant 灰度上线，"
            "为什么选第三种 runtime，默认必须有哪些审批和隔离规则，"
            "回滚怎么做？"
        ),
        top_k=4,
        per_document_limit=2,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert result.document_count == 3
    assert result.chunk_count == len(result.selected_chunks)
    assert "第三种 runtime 模式" in selected_text
    assert "默认不写主仓库" in selected_text
    assert "ENABLE_CLAUDE_CODE_RUNTIME=false" in selected_text
    assert "# Context Pack" in result.markdown
    assert "Query:" in result.markdown
    assert "Source: `安全治理`" in result.markdown


def test_context_pack_json_includes_v1_schema_and_applied_filters(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "bosch-diagnostic.md"
    source.write_text(
        "\n".join(
            [
                "# 诊断约束",
                "",
                "诊断模块修改时必须检查 DTC 状态同步。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="Bosch Diagnostic Constraint",
        source_type="supplier spec",
        owner="checker",
        project="cockpit",
        supplier="Bosch",
        document_version="v7.0",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="诊断模块修改需要注意什么？",
        top_k=3,
        per_document_limit=2,
        metadata_filters={
            "supplier": ["Bosch"],
            "project": ["cockpit"],
            "document_version": ["v7.0"],
            "source_type": ["supplier spec"],
        },
    )

    payload = result.to_json_dict()

    assert payload["schema_version"] == "context-pack.v1"
    assert payload["applied_filters"] == {
        "supplier": ["Bosch"],
        "project": ["cockpit"],
        "document_version": ["v7.0"],
        "source_type": ["supplier spec"],
    }
    item = payload["sections"][0]["items"][0]
    assert item["document_version"] == "v7.0"
    assert item["supplier"] == "Bosch"
    assert item["project"] == "cockpit"
    assert item["source_type"] == "supplier spec"
    assert item["chunk"]["document_version"] == "v7.0"
    assert item["chunk"]["supplier"] == "Bosch"
    assert item["chunk"]["project"] == "cockpit"


def test_context_pack_json_exposes_v1_contract_and_task_profile(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "governance.md"
    source.write_text(
        "\n".join(
            [
                "# 安全治理",
                "",
                "默认不写主仓库。",
                "默认高风险动作必须审批。",
                "默认不开放无限网络，禁止绕过审批策略。",
                "所有高风险执行都必须记录审计字段、执行人、运行参数和证据。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="安全治理",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="代码评审时默认治理规则是什么？",
        task_type="code_review",
        top_k=2,
        per_document_limit=1,
    )

    payload = result.to_json_dict()

    assert result.task_type == "code_review"
    assert payload["schema_version"] == "context-pack.v1"
    assert payload["task_type"] == "code_review"
    assert payload["task_profile"]["label"] == "Code Review"
    assert payload["contract"]["stable_fields"][0] == "schema_version"
    assert "sections" in payload["contract"]["stable_fields"]
    assert "task_item_type" in payload["contract"]["item_stable_fields"]
    assert payload["warnings"] == []
    assert payload["sections"][0]["title"] == "Review Safety Risks"
    assert payload["sections"][0]["items"][0]["task_item_type"] == "review_risk"
    assert "Task Type: `code_review`" in result.markdown


def test_build_context_pack_rejects_unknown_task_type(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "doc.md"
    source.write_text(
        "# 设计\n\n采用第三种 runtime 模式。",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    try:
        build_context_pack_for_processed_dir(
            processed_dir=processed_root,
            query="为什么采用第三种 runtime？",
            task_type="unknown_task",
        )
    except ValueError as exc:
        assert "Unsupported task_type" in str(exc)
    else:
        raise AssertionError("build_context_pack_for_processed_dir should reject unknown task_type")


def test_build_context_pack_normalizes_legacy_eval_task_type_aliases(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "api-and-test.md"
    source.write_text(
        "\n".join(
            [
                "# 接口与测试",
                "",
                "接口使用时必须检查错误码、超时和版本限制。",
                "测试设计必须覆盖接口失败、超时恢复和版本兼容。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="接口与测试",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    api_result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="查接口机制需要注意什么？",
        task_type="查接口/机制",
        top_k=1,
        per_document_limit=1,
    )
    test_result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="生成测试关注点",
        task_type="test_focus_generation",
        top_k=1,
        per_document_limit=1,
    )

    assert api_result.task_type == "api_usage"
    assert test_result.task_type == "test_design"


def test_build_context_pack_metadata_filters_limit_results_to_matching_documents(tmp_path: Path):
    processed_root = tmp_path / "processed"

    bosch = tmp_path / "bosch.md"
    bosch.write_text(
        "# 诊断\n\n诊断模块修改时必须检查 DTC 状态同步。",
        encoding="utf-8",
    )
    qualcomm = tmp_path / "qualcomm.md"
    qualcomm.write_text(
        "# 诊断\n\n诊断模块修改时必须检查 BSP 电源状态同步。",
        encoding="utf-8",
    )

    ingest_file(
        file_path=bosch,
        out_dir=processed_root,
        title="Bosch Diagnostic Constraint",
        source_type="supplier spec",
        owner="checker",
        project="cockpit",
        supplier="Bosch",
        document_version="v7.0",
    )
    ingest_file(
        file_path=qualcomm,
        out_dir=processed_root,
        title="Qualcomm Diagnostic Constraint",
        source_type="supplier spec",
        owner="checker",
        project="cockpit",
        supplier="Qualcomm",
        document_version="v8.0",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="诊断模块修改需要注意什么？",
        top_k=4,
        per_document_limit=2,
        metadata_filters={"supplier": ["Bosch"], "document_version": ["v7.0"]},
    )

    assert result.selected_chunks
    assert {chunk.document_title for chunk in result.selected_chunks} == {"Bosch Diagnostic Constraint"}
    assert {chunk.supplier for chunk in result.selected_chunks} == {"Bosch"}
    assert {chunk.document_version for chunk in result.selected_chunks} == {"v7.0"}


def test_build_context_pack_prefers_compact_exact_term_chunk_for_symbol_query(tmp_path: Path):
    processed_root = tmp_path / "processed"

    short = tmp_path / "short-api.md"
    short.write_text(
        "\n".join(
            [
                "# API",
                "",
                "runtime_requires_approval 表示任务等待人工审批。",
                "调用方收到该事件后必须暂停执行并等待审批结果。",
                "该事件只在高风险操作下出现。",
                "返回后继续执行或终止执行。",
            ]
        ),
        encoding="utf-8",
    )
    long = tmp_path / "long-runbook.md"
    long.write_text(
        "# Runbook\n\n"
        "本节描述很多通用背景。runtime_requires_approval 表示任务等待人工审批。\n"
        + "额外背景说明。" * 120
        + "\n调用方收到该事件后必须暂停执行并等待审批结果。\n",
        encoding="utf-8",
    )

    ingest_file(
        file_path=short,
        out_dir=processed_root,
        title="Z Short API",
        source_type="internal api",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=long,
        out_dir=processed_root,
        title="A Long Runbook",
        source_type="internal guide",
        owner="checker",
        document_version="v1",
        max_chunk_chars=2200,
        overlap_chars=0,
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="runtime_requires_approval",
        top_k=2,
        per_document_limit=2,
    )

    assert result.selected_chunks
    assert result.selected_chunks[0].document_title == "Z Short API"
    assert result.selected_chunks[0].score > result.selected_chunks[1].score


def test_build_context_pack_uses_fts_index_for_prefix_symbol_query(tmp_path: Path):
    processed_root = tmp_path / "processed"
    index_path = tmp_path / "fts" / "chunks.db"

    api = tmp_path / "api.md"
    api.write_text(
        "# API\n\nruntime_requires_approval 事件用于审批。\n",
        encoding="utf-8",
    )
    unrelated = tmp_path / "notes.md"
    unrelated.write_text(
        "# Notes\n\n运行时相关的通用 requirement 汇总。\n",
        encoding="utf-8",
    )

    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="API",
        source_type="internal api",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=unrelated,
        out_dir=processed_root,
        title="A Notes",
        source_type="internal guide",
        owner="checker",
        document_version="v1",
    )

    build_fts_index(
        processed_dir=processed_root,
        index_path=index_path,
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="runtime_requir",
        top_k=1,
        per_document_limit=1,
        fts_index_path=index_path,
    )

    assert result.selected_chunks
    assert result.selected_chunks[0].document_title == "API"
    assert "runtime_requires_approval" in result.selected_chunks[0].text
    assert "fts" in result.selected_chunks[0].retrieval_signals


def test_build_context_pack_prefers_chunks_covering_core_technical_terms(tmp_path: Path):
    processed_root = tmp_path / "processed"

    mutex = tmp_path / "mutex.md"
    mutex.write_text(
        "\n".join(
            [
                "# pthread mutex priority inheritance",
                "",
                "pthread mutex priority inheritance and priority protection constraints must be checked.",
                "The mutex protocol affects synchronization behavior and caveats for real-time threads.",
            ]
        ),
        encoding="utf-8",
    )
    crypto = tmp_path / "crypto.md"
    crypto.write_text(
        "\n".join(
            [
                "# Cryptographic primitives",
                "",
                "Cryptographic primitives have constraints and caveats.",
                "Algorithm handling requires plugin binding and release.",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=crypto,
        out_dir=processed_root,
        title="A System Security Guide",
        source_type="supplier security guide",
        owner="checker",
        document_version="SDP 7.1",
    )
    ingest_file(
        file_path=mutex,
        out_dir=processed_root,
        title="Z C Library Reference",
        source_type="supplier api reference",
        owner="checker",
        document_version="SDP 7.1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "What QNX SDP 7.1 constraints or caveats should be considered "
            "when using pthread mutex priority inheritance or related synchronization APIs?"
        ),
        task_type="constraint_lookup",
        top_k=2,
        per_document_limit=1,
    )

    assert result.selected_chunks
    assert result.selected_chunks[0].document_title == "Z C Library Reference"
    assert "pthread mutex priority inheritance" in result.selected_chunks[0].text


def test_topic_seed_does_not_promote_off_topic_api_chunk_over_core_terms(tmp_path: Path):
    processed_root = tmp_path / "processed"

    mutex = tmp_path / "mutex.md"
    mutex.write_text(
        "\n".join(
            [
                "# Priority inheritance and mutexes",
                "",
                "pthread mutex priority inheritance affects thread synchronization.",
                "A mutex owner may inherit a higher-priority caller, and pthread_mutexattr_setprotocol controls the protocol.",
            ]
        ),
        encoding="utf-8",
    )
    algorithm = tmp_path / "algorithm.md"
    algorithm.write_text(
        "\n".join(
            [
                "# Requesting an algorithm API",
                "",
                "The qcrypto API lets a user request an algorithm from a plugin.",
                "This section has API constraints and caveats for plugin algorithm handling.",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=algorithm,
        out_dir=processed_root,
        title="A System Security Guide",
        source_type="supplier security guide",
        owner="checker",
        document_version="SDP 7.1",
    )
    ingest_file(
        file_path=mutex,
        out_dir=processed_root,
        title="Z System Architecture",
        source_type="architecture",
        owner="checker",
        document_version="SDP 7.1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "What QNX SDP 7.1 constraints or caveats should be considered "
            "when using pthread mutex priority inheritance or related synchronization APIs?"
        ),
        task_type="constraint_lookup",
        top_k=2,
        per_document_limit=1,
    )

    assert result.selected_chunks
    assert result.selected_chunks[0].document_title == "Z System Architecture"
    assert result.selected_chunks[0].section_titles == ["Priority inheritance and mutexes"]


def test_topic_seed_does_not_promote_compact_toc_chunk_over_body_evidence(tmp_path: Path):
    processed_root = tmp_path / "processed"

    toc = tmp_path / "toc.md"
    toc.write_text(
        "\n".join(
            [
                "# Electronic edition published: October 28, 2024",
                "",
                (
                    "Contents About This Guide........................................9 "
                    "Chapter 2: The QNX Neutrino Microkernel.........................27 "
                    "Thread scheduling...............................................38 "
                    "Synchronization services........................................47 "
                    "Mutexes: mutual exclusion locks.................................47 "
                    "Reader/writer locks.............................................53 "
                    "Priority inheritance and messages...............................79 "
                    "Message-passing API.............................................81 "
                    "Events..........................................................84 "
                    "Signals.........................................................86 "
                    "Contents"
                ),
            ]
        ),
        encoding="utf-8",
    )
    mutex = tmp_path / "mutex.md"
    mutex.write_text(
        "\n".join(
            [
                "# Priority inheritance and mutexes",
                "",
                "pthread mutex priority inheritance affects thread synchronization.",
                "pthread_mutexattr_setprotocol controls whether a mutex uses inheritance or protection.",
                "The implementation constraints and caveats must be checked for real-time threads.",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=toc,
        out_dir=processed_root,
        title="QNX Neutrino RTOS 7.1 System Architecture",
        source_type="architecture",
        owner="checker",
        document_version="SDP 7.1",
    )
    ingest_file(
        file_path=mutex,
        out_dir=processed_root,
        title="QNX Neutrino RTOS 7.1 C Library Reference",
        source_type="supplier api reference",
        owner="checker",
        document_version="SDP 7.1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "What QNX SDP 7.1 constraints or caveats should be considered "
            "when using pthread mutex priority inheritance or related synchronization APIs?"
        ),
        task_type="constraint_lookup",
        top_k=2,
        per_document_limit=1,
    )

    assert result.selected_chunks
    assert result.selected_chunks[0].document_title == "QNX Neutrino RTOS 7.1 C Library Reference"
    assert result.selected_chunks[0].section_titles == ["Priority inheritance and mutexes"]
    assert "Contents About This Guide" not in result.selected_chunks[0].text


def test_topic_seed_does_not_promote_compact_toc_continuation_chunk(tmp_path: Path):
    processed_root = tmp_path / "processed"

    toc = tmp_path / "toc-continuation.md"
    toc.write_text(
        "\n".join(
            [
                "# Electronic edition published: October 28, 2024",
                "",
                (
                    "Timers........................................................59 "
                    "Interrupt handling.............................................62 "
                    "Chapter 3: Interprocess Communication (IPC)....................69 "
                    "Priority inheritance and messages..............................79 "
                    "Message-passing API............................................81 "
                    "Events.........................................................84 "
                    "Signals........................................................86 "
                    "Chapter 4: The Instrumented Microkernel.......................105 "
                    "Chapter 5: Multicore Processing...............................113 "
                    "Bound multiprocessing (BMP)...................................119 Contents "
                    "Chapter 6: Process Manager....................................123 "
                    "Using libc APIs to calculate memory reservations...............142 "
                    "Chapter 7: Dynamic Linking....................................155 "
                    "Chapter 8: Resource Managers.................................163"
                ),
            ]
        ),
        encoding="utf-8",
    )
    mutex = tmp_path / "mutex.md"
    mutex.write_text(
        "\n".join(
            [
                "# Perform an operation on a synchronization object",
                "",
                "pthread mutex priority inheritance applies to synchronization APIs.",
                "Mutex caveats and error handling must be considered before implementation.",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=toc,
        out_dir=processed_root,
        title="QNX Neutrino RTOS 7.1 System Architecture",
        source_type="architecture",
        owner="checker",
        document_version="SDP 7.1",
    )
    ingest_file(
        file_path=mutex,
        out_dir=processed_root,
        title="QNX Neutrino RTOS 7.1 C Library Reference",
        source_type="supplier api reference",
        owner="checker",
        document_version="SDP 7.1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "What QNX SDP 7.1 constraints or caveats should be considered "
            "when using pthread mutex priority inheritance or related synchronization APIs?"
        ),
        task_type="constraint_lookup",
        top_k=2,
        per_document_limit=1,
    )

    assert result.selected_chunks
    assert result.selected_chunks[0].document_title == "QNX Neutrino RTOS 7.1 C Library Reference"
    assert result.selected_chunks[0].section_titles == [
        "Perform an operation on a synchronization object"
    ]
    assert "Chapter 3: Interprocess Communication" not in result.selected_chunks[0].text


def test_build_context_pack_uses_vector_index_for_semantic_like_query(tmp_path: Path):
    processed_root = tmp_path / "processed"
    index_path = tmp_path / "vector" / "chunks.vector.json"

    safety = tmp_path / "safety.md"
    safety.write_text(
        "# 出境限制\n\n车辆重要数据出境传输需要进行安全评估，并记录证据。\n",
        encoding="utf-8",
    )
    diagnostics = tmp_path / "diagnostics.md"
    diagnostics.write_text(
        "# 诊断\n\nDTC 状态同步需要覆盖上电、下电和异常恢复场景。\n",
        encoding="utf-8",
    )

    ingest_file(
        file_path=safety,
        out_dir=processed_root,
        title="Z 出境限制",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=diagnostics,
        out_dir=processed_root,
        title="A 诊断",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    build_vector_index(processed_dir=processed_root, index_path=index_path)

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="海外批准要求",
        top_k=1,
        per_document_limit=1,
        vector_index_path=index_path,
    )

    assert result.selected_chunks
    assert result.selected_chunks[0].document_title == "Z 出境限制"
    assert "安全评估" in result.selected_chunks[0].text
    assert "vector" in result.selected_chunks[0].retrieval_signals


def test_build_context_pack_honors_per_document_limit(tmp_path: Path):
    processed_root = tmp_path / "processed"
    long_doc = tmp_path / "long.md"
    long_doc.write_text(
        "\n".join(
            [
                "# 安全规则",
                "",
                "默认不写主仓库。",
                "",
                "## 审批",
                "",
                "高风险动作必须审批。",
                "",
                "## 网络",
                "",
                "默认不开放无限网络。",
            ]
        ),
        encoding="utf-8",
    )
    short_doc = tmp_path / "rollout.md"
    short_doc.write_text(
        "\n".join(
            [
                "# 回滚",
                "",
                "ENABLE_CLAUDE_CODE_RUNTIME=false。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=long_doc,
        out_dir=processed_root,
        title="安全规则",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
        max_chunk_chars=80,
    )
    ingest_file(
        file_path=short_doc,
        out_dir=processed_root,
        title="回滚",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="默认审批和回滚怎么做",
        top_k=3,
        per_document_limit=1,
    )

    titles = [chunk.document_title for chunk in result.selected_chunks]

    assert titles.count("安全规则") == 1
    assert titles.count("回滚") == 1
    assert "ENABLE_CLAUDE_CODE_RUNTIME=false" in result.markdown
    assert "高风险动作必须审批" in result.markdown


def test_build_context_pack_prioritizes_body_clauses_over_toc_and_appendix_noise(
    tmp_path: Path,
):
    processed_root = tmp_path / "processed"
    standard = tmp_path / "gbt.md"
    standard.write_text(
        "\n".join(
            [
                "# Page 2",
                "",
                "目次",
                "5个人信息保护要求",
                "6重要数据保护要求",
                "6.1 重要数据处理通用要求",
                "6.2 重要数据收集",
                "6.3 重要数据存储",
                "6.4 重要数据使用",
                "6.5 重要数据传输",
                "6.6 重要数据删除",
                "6.7 重要数据出境",
                "附录D 个人信息和重要数据处理试验方法",
                "",
                "# Page 7",
                "",
                "GB/T 44464—2024",
                "6.3重要数据存储",
                "车辆应采取安全访问技术、加密技术或其他安全技术保护存储在车内的重要数据，防止其被非授权访问和获取。",
                "6.4重要数据使用",
                "使用重要数据时，汽车数据处理者应采取访问控制措施，防止非授权访问存储的重要数据。",
                "6.5重要数据传输",
                "车辆应对向车外发送的重要数据实施保密性保护措施。",
                "6.6重要数据删除",
                "被删除的重要数据应不可检索且不可访问。",
                "6.7重要数据出境",
                "车辆不应直接向境外传输重要数据等数据。",
                "7审核评估及试验要求",
                "7.2应根据附录B对车辆进行个人信息匿名化处理试验，应根据附录D对车辆进行个人信息及重要数据处理试验，并满足各试验对应的要求。",
                "附录A",
                "（资料性）",
                "汽车数据分类分级示例",
                "A.1数据分类分级原则",
                "汽车数据处理者应根据影响对象和影响程度进行分类分级。",
                "",
                "# Page 8",
                "",
                "A.3.1.3影响程度",
                "汽车产品在研发设计和生产制造过程中产生和收集的数据分级方法见表A.1。",
                "",
                "# Page 13",
                "",
                "附录D（规范性）",
                "个人信息和重要数据处理试验方法",
                "D.1试验输入信息",
                "试验开始前，应提供试验车辆涉及的处理个人信息和重要数据的功能清单。",
                "D.4个人信息和重要数据存储试验方法",
                "按照个人信息和重要数据处理功能清单和存储地址清单，判定试验结果是否符合5.4.1和6.3的要求。",
                "D.6个人信息和重要数据传输试验方法",
                "触发车辆向外传输敏感个人信息、重要数据的功能，检查是否进行加密，判定试验结果是否符合5.5.1.1和6.5的要求。",
                "D.7个人信息和重要数据删除试验方法",
                "请求删除个人信息和重要数据，对删除的数据内容在车端进行检索，判定试验结果是否符合5.7.2和6.6的要求。",
                "D.8个人信息和重要数据出境试验方法",
                "解析通信报文数据，检查目的IP地址中是否包含境外IP地址，判定车辆是否满足5.8和6.7要求。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=standard,
        out_dir=processed_root,
        title="GBT 44464-2024 汽车数据通用要求",
        source_type="national standard pdf",
        owner="checker",
        document_version="v1",
        max_chunk_chars=900,
        overlap_chars=0,
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="重要数据存储、传输、删除和出境有什么要求？",
        top_k=3,
        per_document_limit=3,
    )

    assert result.selected_chunks
    first_chunk = result.selected_chunks[0]
    assert "6.3重要数据存储" in first_chunk.text
    assert "车辆应采取安全访问技术" in first_chunk.text
    assert "车辆不应直接向境外传输重要数据" in first_chunk.text
    assert "目次" not in first_chunk.text
    assert "Page 8" not in first_chunk.text
    assert "附录A" not in first_chunk.text
    assert "附录D（规范性）" not in first_chunk.text

    evidence_one = result.markdown.split("### Evidence 1", 1)[1].split("### Evidence 2", 1)[0]
    assert "6.3重要数据存储" in evidence_one
    assert "车辆应采取安全访问技术" in evidence_one
    assert "个人信息和重要数据处理试验方法" not in evidence_one
    assert "附录A" not in evidence_one


def test_build_context_pack_prioritizes_appendix_d8_body_for_outbound_test_query(
    tmp_path: Path,
):
    processed_root = tmp_path / "processed"
    standard = tmp_path / "gbt.md"
    standard.write_text(
        "\n".join(
            [
                "# Page 2",
                "",
                "目次",
                "6.7重要数据出境",
                "D.8个人信息和重要数据出境试验方法",
                "",
                "# Page 7",
                "",
                "6.7重要数据出境",
                "车辆不应直接向境外传输重要数据等数据。",
                "注：用户使用浏览器访问境外网站、使用通信软件向境外传递消息、自主安装可能导致数据出境的第三方应用等用户自主行为不受本条限制。",
                "",
                "# Page 13",
                "",
                "附录D（规范性）",
                "个人信息和重要数据处理试验方法",
                "D.8个人信息和重要数据出境试验方法",
                "开启车辆全部移动蜂窝通信通道和无线局域网（WLAN）通信通道。",
                "依次模拟测试车辆处于未上电、仅上电、各项预装的数据传输功能正常启用的状态。",
                "使用网络数据抓包工具对对外通信网络通道同时抓包。",
                "总抓包时长不少于3600s。",
                "解析通信报文数据，检查目的IP地址中是否包含境外IP地址，判定车辆是否满足5.8和6.7要求。",
            ]
        ),
        encoding="utf-8",
    )
    unrelated_flow = tmp_path / "flow.md"
    unrelated_flow.write_text(
        "\n".join(
            [
                "# 开发流程",
                "",
                "设计、拆解、实现、审查、测试形成 artifact 链。",
                "任何阶段失败，都必须能回到上一阶段仍可运行的状态。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=standard,
        out_dir=processed_root,
        title="GBT 44464-2024 汽车数据通用要求",
        source_type="national standard pdf",
        owner="checker",
        document_version="v1",
        max_chunk_chars=430,
        overlap_chars=0,
    )
    ingest_file(
        file_path=unrelated_flow,
        out_dir=processed_root,
        title="OpenClaw实施迁移计划",
        source_type="engineering document",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="GB/T 44464-2024 中，重要数据出境限制和出境试验方法的关键检查点是什么？需要 D.8、抓包、3600s、境外IP。",
        top_k=3,
        per_document_limit=3,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)
    first_text = result.selected_chunks[0].text

    assert "D.8个人信息和重要数据出境试验方法" in selected_text
    assert "总抓包时长不少于3600s" in selected_text
    assert "目的IP地址中是否包含境外IP地址" in selected_text
    assert "D.8个人信息和重要数据出境试验方法" in first_text
    assert "目次" not in first_text
    assert "artifact 链" not in first_text


def test_build_context_pack_keeps_outbound_constraint_and_method_with_document_limit(
    tmp_path: Path,
):
    processed_root = tmp_path / "processed"
    standard = tmp_path / "gbt.md"
    standard.write_text(
        "\n".join(
            [
                "# Page 2",
                "",
                "目次",
                "6.7重要数据出境",
                "D.8个人信息和重要数据出境试验方法",
                "",
                "# Page 7",
                "",
                "6.7重要数据出境",
                "车辆不应直接向境外传输重要数据等数据。",
                "注：用户使用浏览器访问境外网站、使用通信软件向境外传递消息、自主安装可能导致数据出境的第三方应用等用户自主行为不受本条限制。",
                "",
                "# Page 13",
                "",
                "附录D（规范性）",
                "个人信息和重要数据处理试验方法",
                "D.1试验输入信息",
                "试验开始前，应提供试验车辆涉及的处理个人信息和重要数据的功能清单。",
                "D.4个人信息和重要数据存储试验方法",
                "判定试验结果是否符合5.4.1和6.3的要求。",
                "D.6个人信息和重要数据传输试验方法",
                "使用车辆制造商提供的端口和访问权限抓取传输的数据包，检查是否对车辆传输的敏感个人信息、重要数据进行加密。",
                "D.8个人信息和重要数据出境试验方法",
                "开启车辆全部移动蜂窝通信通道和无线局域网（WLAN）通信通道。",
                "依次模拟测试车辆处于未上电、仅上电、各项预装的数据传输功能正常启用的状态。",
                "使用网络数据抓包工具对对外通信网络通道同时抓包，总抓包时长不少于3600s。",
                "解析通信报文数据，检查目的IP地址中是否包含境外IP地址，判定车辆是否满足5.8和6.7要求。",
            ]
        ),
        encoding="utf-8",
    )
    unrelated_flow = tmp_path / "flow.md"
    unrelated_flow.write_text(
        "\n".join(
            [
                "# 开发流程",
                "",
                "设计、拆解、实现、审查、测试形成 artifact 链。",
                "任何阶段失败，都必须能回到上一阶段仍可运行的状态。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=standard,
        out_dir=processed_root,
        title="GBT 44464-2024 汽车数据通用要求",
        source_type="national standard pdf",
        owner="checker",
        document_version="v1",
        max_chunk_chars=900,
        overlap_chars=0,
    )
    ingest_file(
        file_path=unrelated_flow,
        out_dir=processed_root,
        title="OpenClaw实施迁移计划",
        source_type="engineering document",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="GB/T 44464-2024 中，重要数据出境限制和出境试验方法的关键检查点是什么？",
        top_k=5,
        per_document_limit=2,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)
    gbt_chunks = [
        chunk
        for chunk in result.selected_chunks
        if chunk.document_title == "GBT 44464-2024 汽车数据通用要求"
    ]

    assert len(gbt_chunks) == 2
    assert "车辆不应直接向境外传输重要数据等数据" in selected_text
    assert "D.8个人信息和重要数据出境试验方法" in selected_text
    assert "总抓包时长不少于3600s" in selected_text
    assert "目的IP地址中是否包含境外IP地址" in selected_text
    assert not any("目次" in chunk.text for chunk in gbt_chunks)


def test_build_context_pack_prefers_clause_coverage_over_duplicate_chunks(tmp_path: Path):
    processed_root = tmp_path / "processed"
    architecture = tmp_path / "architecture.md"
    architecture.write_text(
        "\n".join(
            [
                "# 架构",
                "",
                "第一阶段采用第三种 runtime 模式，第三种 runtime 模式与现有架构最一致，第三种 runtime 模式是推荐方案。",
                "第三种 runtime 模式比 Skill/MCP 更适合正式方案，第三种 runtime 模式保持平台边界清晰。",
                "",
                "## 继续说明",
                "",
                "第三种 runtime 模式仍然是第一阶段推荐方案，第三种 runtime 模式继续作为正式方案，第三种 runtime 模式优于源码嵌入。",
            ]
        ),
        encoding="utf-8",
    )
    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API",
                "",
                "Runtime Runs 包括 GET /runtime-runs/{run_id}/events。",
                "websocket 事件包括 runtime_status 和 runtime_error。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=architecture,
        out_dir=processed_root,
        title="架构",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
        max_chunk_chars=70,
    )
    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="API",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="为什么选第三种 runtime 模式，第一阶段最小 API 能力是什么？",
        top_k=2,
        per_document_limit=2,
    )

    titles = [chunk.document_title for chunk in result.selected_chunks]

    assert "架构" in titles
    assert "API" in titles


def test_compare_context_pack_against_reference_reports_missing_constraints(tmp_path: Path):
    processed_root = tmp_path / "processed"
    doc = tmp_path / "safety.md"
    doc.write_text(
        "\n".join(
            [
                "# 安全治理",
                "",
                "默认不写主仓库。",
                "默认不开放无限网络。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=doc,
        out_dir=processed_root,
        title="安全治理",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    from agent_knowledge_hub.retrieval import compare_context_pack_against_reference

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="默认安全规则是什么？",
        top_k=2,
        per_document_limit=1,
    )

    reference = tmp_path / "reference.md"
    reference.write_text(
        "\n".join(
            [
                "# Context Pack",
                "",
                "## Summary",
                "",
                "- 默认不写主仓库",
                "- 默认不开放无限网络",
                "- 默认不绕过审批",
                "",
                "## Hard Constraints",
                "",
                "1. 默认不能直写 main",
                "2. 默认不能绕过审批",
            ]
        ),
        encoding="utf-8",
    )

    gap = compare_context_pack_against_reference(
        auto_result=result,
        reference_markdown_path=reference,
    )

    assert gap.covered_reference_item_count >= 2
    assert any("默认不绕过审批" in item for item in gap.missing_reference_items)
    assert any("默认不能直写 main" in item for item in gap.missing_reference_items)


def test_gap_report_does_not_count_query_text_as_coverage(tmp_path: Path):
    processed_root = tmp_path / "processed"
    doc = tmp_path / "architecture.md"
    doc.write_text(
        "\n".join(
            [
                "# 架构",
                "",
                "采用第三种 runtime 模式。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=doc,
        out_dir=processed_root,
        title="架构",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    from agent_knowledge_hub.retrieval import compare_context_pack_against_reference

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="默认不绕过审批的规则是什么？",
        top_k=1,
        per_document_limit=1,
    )

    reference = tmp_path / "reference.md"
    reference.write_text(
        "\n".join(
            [
                "# Context Pack",
                "",
                "- 默认不绕过审批",
            ]
        ),
        encoding="utf-8",
    )

    gap = compare_context_pack_against_reference(
        auto_result=result,
        reference_markdown_path=reference,
    )

    assert gap.covered_reference_item_count == 0
    assert any("默认不绕过审批" in item for item in gap.missing_reference_items)


def test_normalize_query_text_strips_markdown_wrapper_and_requirement_noise():
    query = "\n".join(
        [
            "# Question",
            "",
            "如果 Claude Code runtime 第一阶段只允许给一个内部 tenant 灰度上线，请综合材料回答：",
            "",
            "1. 为什么最终选择第三种 runtime 模式。",
            "2. 第一阶段最小可交付范围包括哪些 API/事件能力。",
            "",
            "要求：",
            "",
            "- 只基于给定材料回答。",
            "- 输出中文。",
            "- 明确区分：架构决策、实现范围、默认治理、灰度门槛、回滚策略。",
            "- 不要把建议项和第一阶段硬要求混在一起。",
        ]
    )

    normalized = _normalize_query_text(query)

    assert "# Question" not in normalized
    assert "要求" not in normalized
    assert "只基于给定材料回答" not in normalized
    assert "输出中文" not in normalized
    assert "不要把建议项" not in normalized
    assert "为什么最终选择第三种 runtime 模式" in normalized
    assert "API/事件能力" in normalized


def test_build_context_pack_prefers_topic_primary_document_for_api(tmp_path: Path):
    processed_root = tmp_path / "processed"
    architecture = tmp_path / "architecture.md"
    architecture.write_text(
        "\n".join(
            [
                "# 方案选型与总体架构",
                "",
                "采用第三种 runtime 模式。",
                "后续需要设计运行时状态与事件映射。",
                "统一定义 AgentRuntimeAdapter。",
            ]
        ),
        encoding="utf-8",
    )
    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API与事件协议设计",
                "",
                "POST /runtime-profiles",
                "GET /runtime-runs/{run_id}/events",
                "websocket 事件包括 runtime_status、runtime_requires_approval、runtime_done、runtime_error。",
            ]
        ),
        encoding="utf-8",
    )
    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "默认不写主仓库。",
                "默认高风险动作必须审批。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=architecture,
        out_dir=processed_root,
        title="01-方案选型与总体架构",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="03-API与事件协议设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=governance,
        out_dir=processed_root,
        title="05-安全隔离与治理设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "# Question\n\n"
            "如果第一阶段上线，需要说明为什么选第三种 runtime 模式，"
            "还要明确第一阶段的 API/事件能力、默认治理规则和灰度回滚要求。\n\n"
            "要求：\n- 输出中文。\n- 不要把建议项和硬要求混在一起。"
        ),
        top_k=4,
        per_document_limit=2,
    )

    titles = [chunk.document_title for chunk in result.selected_chunks]
    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert "03-API与事件协议设计" in titles
    assert "GET /runtime-runs/{run_id}/events" in selected_text
    assert "runtime_requires_approval" in selected_text


def test_build_context_pack_uses_section_titles_to_pick_rollback_evidence(tmp_path: Path):
    processed_root = tmp_path / "processed"
    rollout = tmp_path / "rollout.md"
    rollout.write_text(
        "\n".join(
            [
                "# 测试验收与回滚方案",
                "",
                "## 验收标准",
                "",
                "- 可以创建 claude_code agent",
                "- 可以看到最终结果与产物",
                "- 第一步仅内部 tenant 开启",
                "",
                "## 功能开关回滚",
                "",
                "- ENABLE_CLAUDE_CODE_RUNTIME=false",
                "",
                "## 执行回滚",
                "",
                "- router 不再分发给 claude_code",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=rollout,
        out_dir=processed_root,
        title="02-测试验收与回滚方案",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
        max_chunk_chars=120,
        overlap_chars=24,
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="如果第一阶段只给内部 tenant 灰度上线，最小回滚条件和 feature flag 是什么？",
        top_k=2,
        per_document_limit=2,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)
    selected_section_titles = [" > ".join(chunk.section_titles) for chunk in result.selected_chunks]

    assert "ENABLE_CLAUDE_CODE_RUNTIME=false" in selected_text
    assert any("功能开关回滚" in title for title in selected_section_titles)
    assert "Section Titles:" in result.markdown


def test_context_pack_markdown_uses_normalized_query_text(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "architecture.md"
    source.write_text(
        "\n".join(
            [
                "# 架构",
                "",
                "采用第三种 runtime 模式。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="架构",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "# Question\n\n"
            "1. 为什么选择第三种 runtime 模式？\n\n"
            "要求：\n- 输出中文。\n- 不要把建议项和硬要求混在一起。"
        ),
        top_k=1,
        per_document_limit=1,
    )

    assert "# Question" not in result.markdown
    assert "要求：" not in result.markdown
    assert "输出中文" not in result.markdown
    assert "为什么选择第三种 runtime 模式" in result.markdown


def test_build_context_pack_ignores_stale_document_versions(tmp_path: Path):
    processed_root = tmp_path / "processed"
    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "旧版本旧版本旧版本旧版本。",
                "默认允许无限网络。",
                "默认允许绕过审批。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=governance,
        out_dir=processed_root,
        title="05-安全隔离与治理设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    governance.write_text(
        "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "新版本。",
                "默认不开放无限网络。",
                "高风险动作必须审批。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=governance,
        out_dir=processed_root,
        title="05-安全隔离与治理设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="第一阶段默认治理规则是什么，网络和审批必须怎么做？",
        top_k=2,
        per_document_limit=2,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert "默认不开放无限网络" in selected_text
    assert "高风险动作必须审批" in selected_text
    assert "默认允许无限网络" not in selected_text
    assert "默认允许绕过审批" not in selected_text
    assert "旧版本旧版本" not in selected_text


def test_build_context_pack_prefers_backend_core_responsibilities_for_minimum_scope(tmp_path: Path):
    processed_root = tmp_path / "processed"
    backend = tmp_path / "backend.md"
    backend.write_text(
        "\n".join(
            [
                "# 后端执行链路设计",
                "",
                "## 6. ClaudeCodeRuntimeAdapter 设计",
                "",
                "### 6.1 核心职责",
                "",
                "- 准备 repo/worktree",
                "- 生成执行参数",
                "- 选择 SDK 或 CLI 执行器",
                "- 接收事件流",
                "- 把事件映射到平台",
                "- 回写结果",
                "",
                "## 8. EventMapper 设计",
                "",
                "- assistant chunk -> websocket chunk",
                "- final result -> task result",
                "- permission request -> approval request",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=backend,
        out_dir=processed_root,
        title="02-后端执行链路设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
        max_chunk_chars=120,
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="第一阶段最小可交付范围里的后端能力必须包含什么？请明确 ClaudeCodeRuntimeAdapter 的核心职责。",
        top_k=1,
        per_document_limit=1,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)
    selected_titles = [" > ".join(chunk.section_titles) for chunk in result.selected_chunks]

    assert "准备 repo/worktree" in selected_text
    assert any("核心职责" in title for title in selected_titles)


def test_build_context_pack_prefers_api_event_sections_over_artifact_endpoint(tmp_path: Path):
    processed_root = tmp_path / "processed"
    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## 3.3 Runtime Runs",
                "",
                "### GET `/runtime-runs/{run_id}/events`",
                "",
                "- 分页拉取事件",
                "",
                "### GET `/runtime-runs/{run_id}/artifacts`",
                "",
                "- 查询运行产物",
                "",
                "## 4. websocket 事件类型",
                "",
                "- `runtime_status`",
                "- `runtime_chunk`",
                "- `runtime_requires_approval`",
                "- `runtime_done`",
                "- `runtime_error`",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="03-API与事件协议设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
        max_chunk_chars=120,
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="第一阶段 API/事件能力必须包含哪些 websocket 事件和事件查询能力？",
        top_k=1,
        per_document_limit=1,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)
    selected_titles = [" > ".join(chunk.section_titles) for chunk in result.selected_chunks]

    assert "runtime_requires_approval" in selected_text or "分页拉取事件" in selected_text
    assert not any("artifacts" in title.lower() for title in selected_titles)


def test_build_context_pack_prefers_governance_defaults_and_forbidden_rules(tmp_path: Path):
    processed_root = tmp_path / "processed"
    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "## 1. 设计目标",
                "",
                "- 不默认写主仓库",
                "- 不默认开放无限网络",
                "- 不默认绕过审批",
                "",
                "## 5. 密钥与凭证",
                "",
                "- 凭证只由后端注入",
                "- 不把长期密钥写入 workspace",
                "",
                "## 8. 第一版强制规则",
                "",
                "- 禁止默认 dangerously-skip-permissions",
                "- 禁止无 run_id 的后台执行",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=governance,
        out_dir=processed_root,
        title="05-安全隔离与治理设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
        max_chunk_chars=120,
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="如果第一阶段要上线，默认必须启用哪些治理规则，哪些事项必须明确禁止，不能默认放开？",
        top_k=2,
        per_document_limit=2,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert "不默认开放无限网络" in selected_text
    assert "禁止默认 dangerously-skip-permissions" in selected_text


def test_context_pack_markdown_renders_structured_sections_and_evidence_appendix(tmp_path: Path):
    processed_root = tmp_path / "processed"

    architecture = tmp_path / "architecture.md"
    architecture.write_text(
        "\n".join(
            [
                "# 方案选型与总体架构",
                "",
                "## 选型结论",
                "",
                "采用方案 B：第三种 runtime 模式。",
                "- 领域层统一定义 AgentRuntimeAdapter",
                "- 第一实现为 ClaudeCodeSDKExecutor",
            ]
        ),
        encoding="utf-8",
    )
    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## websocket 事件类型",
                "",
                "- runtime_status",
                "- runtime_requires_approval",
            ]
        ),
        encoding="utf-8",
    )
    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "## 第一版强制规则",
                "",
                "- 禁止默认 dangerously-skip-permissions",
                "- 禁止无 run_id 的后台执行",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=architecture,
        out_dir=processed_root,
        title="01-方案选型与总体架构",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="03-API与事件协议设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=governance,
        out_dir=processed_root,
        title="05-安全隔离与治理设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="为什么选第三种 runtime，API 事件能力和默认禁止项分别是什么？",
        top_k=3,
        per_document_limit=1,
    )

    assert "## Summary" in result.markdown
    assert "## Architecture Decision" in result.markdown
    assert "## API / Event Scope" in result.markdown
    assert "## Safety / Governance Defaults" in result.markdown
    assert "## Evidence Appendix" in result.markdown
    assert "[Evidence 1]" in result.markdown
    assert "### Evidence 1" in result.markdown


def test_gap_report_matches_code_span_terms_with_underscores(tmp_path: Path):
    processed_root = tmp_path / "processed"
    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "- runtime_status",
                "- runtime_requires_approval",
                "- claude_code",
                "- run_id",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="03-API与事件协议设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    from agent_knowledge_hub.retrieval import compare_context_pack_against_reference

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="第一阶段 API 事件能力和运行标识需要哪些字段？",
        top_k=1,
        per_document_limit=1,
    )

    reference = tmp_path / "reference.md"
    reference.write_text(
        "\n".join(
            [
                "# Context Pack",
                "",
                "- `runtime_status`",
                "- `runtime_requires_approval`",
                "- `claude_code`",
                "- `run_id`",
            ]
        ),
        encoding="utf-8",
    )

    gap = compare_context_pack_against_reference(
        auto_result=result,
        reference_markdown_path=reference,
    )

    assert gap.covered_reference_item_count == 4
    assert gap.missing_reference_item_count == 0


def test_gap_report_matches_runtime_metadata_paths(tmp_path: Path):
    processed_root = tmp_path / "processed"
    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## 3.1 Agent 创建",
                "",
                "- runtime_metadata.execution_mode",
                "- runtime_metadata.repo_policy",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="03-API与事件协议设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    from agent_knowledge_hub.retrieval import compare_context_pack_against_reference

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="第一阶段 API 字段需要什么？",
        top_k=1,
        per_document_limit=1,
    )

    reference = tmp_path / "reference.md"
    reference.write_text(
        "\n".join(
            [
                "# Context Pack",
                "",
                "- `runtime_metadata.execution_mode`",
                "- `runtime_metadata.repo_policy`",
            ]
        ),
        encoding="utf-8",
    )

    gap = compare_context_pack_against_reference(
        auto_result=result,
        reference_markdown_path=reference,
    )

    assert gap.covered_reference_item_count == 2
    assert gap.missing_reference_item_count == 0


def test_context_pack_json_contains_structured_sections(tmp_path: Path):
    processed_root = tmp_path / "processed"

    architecture = tmp_path / "architecture.md"
    architecture.write_text(
        "\n".join(
            [
                "# 方案选型与总体架构",
                "",
                "## 选型结论",
                "",
                "采用方案 B：第三种 runtime 模式。",
            ]
        ),
        encoding="utf-8",
    )
    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## websocket 事件类型",
                "",
                "- runtime_status",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=architecture,
        out_dir=processed_root,
        title="01-方案选型与总体架构",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="03-API与事件协议设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="为什么选第三种 runtime，事件能力需要什么？",
        top_k=2,
        per_document_limit=1,
    )

    payload = result.to_json_dict()

    assert "sections" in payload
    assert payload["sections"][0]["title"] == "Architecture Decision"
    assert payload["sections"][0]["items"][0]["evidence_number"] == 1
    assert payload["sections"][0]["items"][0]["summary"]
    assert payload["sections"][1]["title"] == "API / Event Scope"


def test_build_context_pack_prefers_subfacet_coverage_within_api_and_governance_topics(
    tmp_path: Path,
):
    processed_root = tmp_path / "processed"

    docs = {
        "01-方案选型与总体架构": "\n".join(
            [
                "# 方案选型与总体架构",
                "",
                "## 方案 A",
                "",
                "- 不推荐作为正式方案",
                "- 只适合极短期 PoC",
                "",
                "## 方案 B",
                "",
                "- 第三种 runtime 模式",
                "- 抽象统一 runtime adapter",
                "- Clawith 统一管理身份、任务、协作、审计",
                "",
                "## 方案 C",
                "",
                "- 工程代价极高",
                "- 第一阶段不推荐",
            ]
        ),
        "02-后端执行链路设计": "\n".join(
            [
                "# 后端执行链路设计",
                "",
                "## 6.1 核心职责",
                "",
                "- 准备 repo/worktree",
                "- 生成执行参数",
                "- 回写结果",
            ]
        ),
        "03-API与事件协议设计": "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## 3.1 Agent 创建",
                "",
                "- runtime_profile_id",
                "- runtime_metadata.execution_mode",
                "- runtime_metadata.repo_policy",
                "",
                "## 3.2 Runtime Profiles",
                "",
                "- POST /runtime-profiles",
                "- GET /runtime-profiles",
                "- GET /runtime-profiles/{id}",
                "- PATCH /runtime-profiles/{id}",
                "",
                "## 3.3 Runtime Runs",
                "",
                "- GET /agents/{agent_id}/runtime-runs",
                "- GET /runtime-runs/{run_id}",
                "- GET /runtime-runs/{run_id}/events",
                "",
                "## 4. websocket 事件类型",
                "",
                "- runtime_status",
                "- runtime_requires_approval",
                "- runtime_done",
            ]
        ),
        "05-安全隔离与治理设计": "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "## 1. 设计目标",
                "",
                "- 不默认写主仓库",
                "- 不默认开放无限网络",
                "- 不默认绕过审批",
                "",
                "## 5. 密钥与凭证",
                "",
                "- 凭证只由 Clawith 后端注入",
                "- 不把长期密钥写入 agent workspace",
                "- runtime 进程只拿最小必要凭证",
                "",
                "## 6. 审计策略",
                "",
                "- 谁发起",
                "- 哪个 Agent",
                "- 哪个 runtime",
                "- 运行参数摘要",
                "",
                "## 7. 治理策略",
                "",
                "- tenant 默认 profile",
                "- Agent 级是否允许 claude_code",
                "- 任务级是否需要额外审批",
                "",
                "## 8. 第一版强制规则",
                "",
                "- 禁止默认 dangerously-skip-permissions",
                "- 禁止无 run_id 的后台执行",
            ]
        ),
        "02-测试验收与回滚方案": "\n".join(
            [
                "# 测试验收与回滚方案",
                "",
                "## 安全验收",
                "",
                "- 默认不会绕过日志与审计",
                "",
                "## 上线建议",
                "",
                "- 第一步仅内部 tenant 开启",
                "",
                "## 功能开关回滚",
                "",
                "- ENABLE_CLAUDE_CODE_RUNTIME=false",
            ]
        ),
    }

    for title, content in docs.items():
        path = tmp_path / f"{title}.md"
        path.write_text(content, encoding="utf-8")
        ingest_file(
            file_path=path,
            out_dir=processed_root,
            title=title,
            source_type="内部设计文档",
            owner="checker",
            document_version="v1",
            max_chunk_chars=140,
            overlap_chars=24,
        )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "为什么选第三种 runtime，第一阶段 API 资源接口、字段和 websocket 事件要包含什么，"
            "默认治理规则、凭证、审计与治理层级分别是什么，灰度与回滚怎么做？"
        ),
        top_k=8,
        per_document_limit=3,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert "runtime_profile_id" in selected_text
    assert "GET /agents/{agent_id}/runtime-runs" in selected_text
    assert "runtime_status" in selected_text
    assert "凭证只由 Clawith 后端注入" in selected_text
    assert "谁发起" in selected_text
    assert "tenant 默认 profile" in selected_text


def test_build_context_pack_treats_broad_api_and_governance_scope_as_multi_subfacet_request(
    tmp_path: Path,
):
    processed_root = tmp_path / "processed"

    docs = {
        "03-API与事件协议设计": "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## 3.1 Agent 创建",
                "",
                "- runtime_profile_id",
                "- runtime_metadata.execution_mode",
                "- runtime_metadata.repo_policy",
                "",
                "## 3.2 Runtime Profiles",
                "",
                "- POST /runtime-profiles",
                "- GET /runtime-profiles",
                "- GET /runtime-profiles/{id}",
                "- PATCH /runtime-profiles/{id}",
                "",
                "## 3.3 Runtime Runs",
                "",
                "- GET /agents/{agent_id}/runtime-runs",
                "- GET /runtime-runs/{run_id}/events",
                "",
                "## 4. websocket 事件类型",
                "",
                "- runtime_status",
                "- runtime_requires_approval",
            ]
        ),
        "05-安全隔离与治理设计": "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "## 1. 设计目标",
                "",
                "- 不默认写主仓库",
                "- 不默认开放无限网络",
                "- 不默认绕过审批",
                "",
                "## 6. 审计策略",
                "",
                "- 谁发起",
                "- 哪个 runtime",
                "",
                "## 7. 治理策略",
                "",
                "### 平台级",
                "",
                "- tenant 默认 profile",
                "- tenant 默认预算",
                "",
                "### Agent 级",
                "",
                "- 是否允许 claude_code",
                "- 是否允许 git 写入",
                "",
                "### 任务级",
                "",
                "- 是否覆盖默认策略",
                "- 是否需要额外审批",
            ]
        ),
    }

    for title, content in docs.items():
        path = tmp_path / f"{title}.md"
        path.write_text(content, encoding="utf-8")
        ingest_file(
            file_path=path,
            out_dir=processed_root,
            title=title,
            source_type="内部设计文档",
            owner="checker",
            document_version="v1",
            max_chunk_chars=140,
            overlap_chars=24,
        )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "第一阶段最小可交付范围里的 API/事件能力要包含什么，"
            "默认治理规则有哪些，治理层级怎么分？"
        ),
        top_k=6,
        per_document_limit=3,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert "runtime_profile_id" in selected_text
    assert "GET /agents/{agent_id}/runtime-runs" in selected_text
    assert "GET /runtime-profiles" in selected_text
    assert "runtime_status" in selected_text
    assert "不默认开放无限网络" in selected_text
    assert "tenant 默认 profile" in selected_text
    assert "是否允许 claude_code" in selected_text


def test_trace_evidence_in_processed_dir_returns_document_section_and_chunk_refs(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "api.md"
    source.write_text(
        "\n".join(
            [
                "# API",
                "",
                "GET /runtime-runs/{run_id}/events 提供事件流查询。",
                "",
                "runtime_requires_approval 事件用于审批。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_result = ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="API",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    payload = json.loads(ingest_result.document_json_path.read_text(encoding="utf-8"))
    evidence_id = next(
        evidence["evidence_id"]
        for evidence in payload["evidence_spans"]
        if "/runtime-runs/{run_id}/events" in evidence["text"]
    )

    trace = trace_evidence_in_processed_dir(
        processed_dir=processed_root,
        evidence_id=evidence_id,
    )

    assert trace.evidence_id == evidence_id
    assert trace.document_title == "API"
    assert trace.document_version_id == ingest_result.document_version_id
    assert trace.source_path == str(source.resolve())
    assert trace.section_titles == ["API"]
    assert "/runtime-runs/{run_id}/events" in trace.text
    assert trace.chunk_references
    assert any(reference.chunk_id for reference in trace.chunk_references)
    assert all(reference.section_titles == ["API"] for reference in trace.chunk_references)


def test_build_context_pack_prefers_governance_modes_profile_details_and_approval_triggers(
    tmp_path: Path,
):
    processed_root = tmp_path / "processed"

    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## Runtime Profiles",
                "",
                "GET /runtime-profiles/{id}",
                "PATCH /runtime-profiles/{id}",
                "",
                "## 审批协议",
                "",
                "- shell 写入高风险目录",
                "- 修改受保护分支",
                "- 网络访问超出策略",
                "- 调用被禁用工具",
            ]
        ),
        encoding="utf-8",
    )
    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "## 设计目标",
                "",
                "- 不默认开放无限 shell",
                "- 不默认开放无限网络",
                "- 不默认绕过审批",
                "",
                "## 网络策略",
                "",
                "- `none`",
                "- `allowlisted`",
                "- `default`",
                "",
                "## 治理策略",
                "",
                "### 平台级",
                "",
                "- tenant 默认 profile",
                "- tenant 默认预算",
                "- tenant 默认工具策略",
            ]
        ),
        encoding="utf-8",
    )

    for path, title in ((api, "API 与事件协议设计"), (governance, "安全隔离与治理设计")):
        ingest_file(
            file_path=path,
            out_dir=processed_root,
            title=title,
            source_type="内部设计文档",
            owner="checker",
            document_version="v1",
            max_chunk_chars=140,
            overlap_chars=24,
        )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "第一阶段最小可交付范围里的 API/事件能力、审批触发条件、"
            "默认治理规则、平台默认策略和网络模式要包含什么？"
        ),
        top_k=6,
        per_document_limit=3,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert "GET /runtime-profiles/{id}" in selected_text
    assert "PATCH /runtime-profiles/{id}" in selected_text
    assert "shell 写入高风险目录" in selected_text
    assert "调用被禁用工具" in selected_text
    assert "不默认开放无限 shell" in selected_text
    assert "allowlisted" in selected_text
    assert "tenant 默认工具策略" in selected_text


def test_build_context_pack_does_not_treat_rollout_safety_acceptance_as_governance_defaults(
    tmp_path: Path,
):
    processed_root = tmp_path / "processed"

    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## Runtime Profiles",
                "",
                "GET /runtime-profiles/{id}",
                "",
                "## Runtime Runs",
                "",
                "GET /agents/{agent_id}/runtime-runs",
                "GET /runtime-runs/{run_id}/events",
            ]
        ),
        encoding="utf-8",
    )
    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "## 设计目标",
                "",
                "- 不默认开放无限 shell",
                "- 不默认开放无限网络",
                "- 不默认绕过审批",
                "",
                "## 密钥与凭证",
                "",
                "- 凭证只由后端注入",
                "",
                "## 审计策略",
                "",
                "- 谁发起",
                "- 哪个 runtime",
            ]
        ),
        encoding="utf-8",
    )
    rollout = tmp_path / "rollout.md"
    rollout.write_text(
        "\n".join(
            [
                "# 测试验收与回滚方案",
                "",
                "## 安全验收",
                "",
                "- 默认不会写主仓库",
                "- 默认高风险动作会审批",
                "- 默认不会绕过日志与审计",
                "",
                "## 上线建议",
                "",
                "- 第一步仅内部 tenant 开启",
            ]
        ),
        encoding="utf-8",
    )

    for path, title in (
        (api, "API 与事件协议设计"),
        (governance, "安全隔离与治理设计"),
        (rollout, "测试验收与回滚方案"),
    ):
        ingest_file(
            file_path=path,
            out_dir=processed_root,
            title=title,
            source_type="内部设计文档",
            owner="checker",
            document_version="v1",
            max_chunk_chars=140,
            overlap_chars=24,
        )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "第一阶段最小可交付范围里的 API/事件能力、默认治理规则、"
            "凭证、审计、灰度门槛分别是什么？"
        ),
        top_k=6,
        per_document_limit=3,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert "不默认开放无限 shell" in selected_text
    assert "不默认开放无限网络" in selected_text
    assert "不默认绕过审批" in selected_text


def test_build_context_pack_prefers_governance_isolation_defaults_for_broad_safety_query(
    tmp_path: Path,
):
    processed_root = tmp_path / "processed"

    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "## 目录隔离",
                "",
                "- 主仓库只读",
                "- 工作发生在独立 worktree",
                "- 每次运行单独目录",
                "",
                "## 分支隔离",
                "",
                "- `cc/<agent-name>/<run-id>`",
                "- 默认直写 `main`",
                "- 默认直写当前开发分支",
                "",
                "## 设计目标",
                "",
                "- 不默认开放无限 shell",
                "- 不默认开放无限网络",
                "- 不默认绕过审批",
            ]
        ),
        encoding="utf-8",
    )
    rollout = tmp_path / "rollout.md"
    rollout.write_text(
        "\n".join(
            [
                "# 测试验收与回滚方案",
                "",
                "## 安全验收",
                "",
                "- 默认不会写主仓库",
                "- 默认高风险动作会审批",
                "- 默认不会绕过日志与审计",
            ]
        ),
        encoding="utf-8",
    )

    for path, title in (
        (governance, "安全隔离与治理设计"),
        (rollout, "测试验收与回滚方案"),
    ):
        ingest_file(
            file_path=path,
            out_dir=processed_root,
            title=title,
            source_type="内部设计文档",
            owner="checker",
            document_version="v1",
            max_chunk_chars=140,
            overlap_chars=24,
        )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="默认必须启用哪些隔离和治理规则，哪些事项不能默认放开？",
        top_k=4,
        per_document_limit=3,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert "主仓库只读" in selected_text
    assert "工作发生在独立 worktree" in selected_text
    assert "cc/<agent-name>/<run-id>" in selected_text
    assert "默认直写 `main`" in selected_text
    assert "默认直写当前开发分支" in selected_text


def test_build_context_pack_prefers_broad_api_seed_over_event_only_chunk(tmp_path: Path):
    processed_root = tmp_path / "processed"

    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## 3.1 Agent 创建",
                "",
                "- runtime_profile_id",
                "- execution_mode",
                "- repo_policy",
                "",
                "## 3.2 Runtime Profiles",
                "",
                "POST /runtime-profiles",
                "GET /runtime-profiles",
                "",
                "## 4. websocket 事件类型",
                "",
                "- runtime_status",
                "- runtime_chunk",
                "- runtime_requires_approval",
                "- runtime_done",
                "- runtime_error",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="03-API与事件协议设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
        max_chunk_chars=120,
        overlap_chars=24,
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "第一阶段的 API/事件能力要一起说明，"
            "包括 agent 创建字段、runtime profile 资源接口和 websocket 事件类型。"
        ),
        top_k=1,
        per_document_limit=1,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert "runtime_profile_id" in selected_text
    assert "POST /runtime-profiles" in selected_text
    assert "runtime_status" in selected_text


def test_build_context_pack_includes_rollout_progression_for_broad_rollout_query(
    tmp_path: Path,
):
    processed_root = tmp_path / "processed"

    rollout = tmp_path / "rollout.md"
    rollout.write_text(
        "\n".join(
            [
                "# 测试验收与回滚方案",
                "",
                "## 上线建议",
                "",
                "第一步",
                "",
                "- 仅内部 tenant 开启",
                "",
                "第二步",
                "",
                "- 仅特定 profile 开启",
                "",
                "第三步",
                "",
                "- 对更多团队开放",
                "",
                "## 回滚方案",
                "",
                "- ENABLE_CLAUDE_CODE_RUNTIME=false",
            ]
        ),
        encoding="utf-8",
    )
    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## Runtime Runs",
                "",
                "GET /agents/{agent_id}/runtime-runs",
                "GET /runtime-runs/{run_id}/events",
            ]
        ),
        encoding="utf-8",
    )

    for path, title in (
        (rollout, "测试验收与回滚方案"),
        (api, "API 与事件协议设计"),
    ):
        ingest_file(
            file_path=path,
            out_dir=processed_root,
            title=title,
            source_type="内部设计文档",
            owner="checker",
            document_version="v1",
            max_chunk_chars=80,
            overlap_chars=16,
        )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="如果第一阶段只允许内部 tenant 灰度上线，第二步和第三步的放量路径是什么，相关 run 查询接口是什么？",
        top_k=4,
        per_document_limit=2,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)

    assert "仅特定 profile 开启" in selected_text
    assert "对更多团队开放" in selected_text
    assert "GET /agents/{agent_id}/runtime-runs" in selected_text


def test_build_context_pack_can_exceed_document_limit_to_fill_required_api_subfacet(
    tmp_path: Path,
):
    processed_root = tmp_path / "processed"
    filler = "\n".join(
        f"这是一段用于打断合并窗口的 filler line {index}，长度足够长以形成多个 chunk。"
        for index in range(1, 80)
    )

    architecture = tmp_path / "architecture.md"
    architecture.write_text(
        "\n".join(
            [
                "# 方案选型",
                "",
                "采用第三种 runtime 模式。",
            ]
        ),
        encoding="utf-8",
    )
    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "## 3.1 Agent 创建",
                "",
                "- runtime_profile_id",
                "- execution_mode",
                "- repo_policy",
                "",
                "## filler-a",
                "",
                filler,
                "",
                "## 3.2 Runtime Profiles",
                "",
                "POST /runtime-profiles",
                "GET /runtime-profiles",
                "GET /runtime-profiles/{id}",
                "PATCH /runtime-profiles/{id}",
                "",
                "## filler-b",
                "",
                filler,
                "",
                "## 3.3 Runtime Runs",
                "",
                "GET /agents/{agent_id}/runtime-runs",
                "GET /runtime-runs/{run_id}/events",
                "",
                "## filler-c",
                "",
                filler,
                "",
                "## 4. websocket 事件类型",
                "",
                "- runtime_status",
                "- runtime_chunk",
                "- runtime_done",
                "",
                "## filler-d",
                "",
                filler,
                "",
                "## 6. 审批协议",
                "",
                "- shell 写入高风险目录",
                "- 调用被禁用工具",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=architecture,
        out_dir=processed_root,
        title="方案选型",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="API 与事件协议设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
        max_chunk_chars=90,
        overlap_chars=18,
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=(
            "第一阶段的最小 API/事件能力要一起说明，"
            "包括 agent 创建字段、runtime profile 接口、runtime run 查询接口、"
            "websocket 事件类型和审批触发条件。"
        ),
        top_k=6,
        per_document_limit=3,
    )

    selected_text = "\n".join(chunk.text for chunk in result.selected_chunks)
    api_chunk_count = sum(
        1 for chunk in result.selected_chunks if chunk.document_title == "API 与事件协议设计"
    )

    assert "GET /agents/{agent_id}/runtime-runs" in selected_text
    assert "runtime_status" in selected_text
    assert "shell 写入高风险目录" in selected_text
    assert api_chunk_count >= 4


def test_gap_report_matches_detailed_governance_and_api_reference_items(tmp_path: Path):
    processed_root = tmp_path / "processed"

    api = tmp_path / "api.md"
    api.write_text(
        "\n".join(
            [
                "# API 与事件协议设计",
                "",
                "GET /runtime-profiles/{id}",
                "PATCH /runtime-profiles/{id}",
                "",
                "## 审批协议",
                "",
                "- shell 写入高风险目录",
                "- 修改受保护分支",
                "- 网络访问超出策略",
                "- 调用被禁用工具",
            ]
        ),
        encoding="utf-8",
    )
    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "- 不默认开放无限 shell",
                "- 不默认开放无限网络",
                "- 不默认绕过审批",
                "- tenant 默认 profile",
                "- tenant 默认预算",
                "- tenant 默认工具策略",
                "- `none`",
                "- `allowlisted`",
                "- `default`",
                "- 默认直写当前开发分支",
            ]
        ),
        encoding="utf-8",
    )

    for path, title in ((api, "API 与事件协议设计"), (governance, "安全隔离与治理设计")):
        ingest_file(
            file_path=path,
            out_dir=processed_root,
            title=title,
            source_type="内部设计文档",
            owner="checker",
            document_version="v1",
        )

    from agent_knowledge_hub.retrieval import compare_context_pack_against_reference

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="默认治理规则、审批触发条件和 runtime profile 详情接口是什么？",
        top_k=4,
        per_document_limit=2,
    )

    reference = tmp_path / "reference.md"
    reference.write_text(
        "\n".join(
            [
                "# Context Pack",
                "",
                "- GET /runtime-profiles/{id}",
                "- PATCH /runtime-profiles/{id}",
                "- shell 写入高风险目录",
                "- 修改受保护分支",
                "- 网络访问超出策略",
                "- 调用被禁用工具",
                "- 不默认开放无限 shell",
                "- 不默认开放无限网络",
                "- 不默认绕过审批",
                "- none",
                "- allowlisted",
                "- default",
                "- tenant 默认 profile / 预算 / 工具策略",
                "- 默认不能直写 `main`，也不能直写当前开发分支。",
                "- 默认不能开放无限 shell / 网络，也不能默认绕过审批。",
            ]
        ),
        encoding="utf-8",
    )

    gap = compare_context_pack_against_reference(
        auto_result=result,
        reference_markdown_path=reference,
    )

    assert "GET /runtime-profiles/{id}" in gap.covered_reference_items
    assert "PATCH /runtime-profiles/{id}" in gap.covered_reference_items
    assert "shell 写入高风险目录" in gap.covered_reference_items
    assert "调用被禁用工具" in gap.covered_reference_items
    assert "tenant 默认 profile / 预算 / 工具策略" in gap.covered_reference_items
    assert "默认不能开放无限 shell / 网络，也不能默认绕过审批。" in gap.covered_reference_items


def test_gap_report_ignores_editorial_summary_but_keeps_evidence_items(tmp_path: Path):
    processed_root = tmp_path / "processed"

    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# 安全隔离与治理设计",
                "",
                "- 主仓库只读",
                "- 不默认开放无限网络",
                "- 不默认绕过审批",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=governance,
        out_dir=processed_root,
        title="安全隔离与治理设计",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    from agent_knowledge_hub.retrieval import compare_context_pack_against_reference

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="默认治理规则是什么？",
        top_k=2,
        per_document_limit=1,
    )

    reference = tmp_path / "reference.md"
    reference.write_text(
        "\n".join(
            [
                "# Context Pack",
                "",
                "- 这轮问题的真正难点不是“知道要有安全”，而是把默认规则重新拼齐。",
                "- 主仓库只读",
                "- 不默认开放无限网络",
                "- 不默认绕过审批",
            ]
        ),
        encoding="utf-8",
    )

    gap = compare_context_pack_against_reference(
        auto_result=result,
        reference_markdown_path=reference,
    )

    assert gap.missing_reference_item_count == 0
    assert not any("真正难点不是" in item for item in gap.covered_reference_items)


def test_gap_report_matches_backend_injected_credentials_phrase(tmp_path: Path):
    processed_root = tmp_path / "processed"

    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# Governance And Safety",
                "",
                "Credentials are injected only by the backend and the runtime receives "
                "the minimum required token set.",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=governance,
        out_dir=processed_root,
        title="04-governance-and-safety",
        source_type="internal design doc",
        owner="checker",
        document_version="v1",
    )

    from agent_knowledge_hub.retrieval import compare_context_pack_against_reference

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="Which credential governance rule must stay enabled by default?",
        top_k=1,
        per_document_limit=1,
    )

    reference = tmp_path / "reference.md"
    reference.write_text(
        "\n".join(
            [
                "# Context Pack",
                "",
                "- credentials come from backend injection",
            ]
        ),
        encoding="utf-8",
    )

    gap = compare_context_pack_against_reference(
        auto_result=result,
        reference_markdown_path=reference,
    )

    assert gap.missing_reference_item_count == 0
    assert "credentials come from backend injection" in gap.covered_reference_items


def test_build_context_pack_penalizes_low_quality_documents(tmp_path: Path):
    processed_root = tmp_path / "processed"
    low_quality = tmp_path / "low-quality.txt"
    low_quality.write_text("默认治理规则", encoding="utf-8")
    good = tmp_path / "good.md"
    good.write_text(
        "\n".join(
            [
                "# 安全治理正文",
                "",
                "默认治理规则要求主仓库只读，不默认开放无限网络，不默认绕过审批。",
                "高风险动作必须触发审批，并且审计记录要保留运行参数摘要。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=low_quality,
        out_dir=processed_root,
        title="低质量短文本",
        source_type="内部说明",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=good,
        out_dir=processed_root,
        title="安全治理正文",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="默认治理规则是什么？",
        top_k=2,
        per_document_limit=1,
    )

    assert result.selected_chunks
    first = result.selected_chunks[0]
    assert first.document_title == "安全治理正文"
    assert first.quality_status == "ok"
    assert first.allowed_for_context_pack is True
    assert "主仓库只读" in first.text
    assert all(chunk.document_title != "低质量短文本" for chunk in result.selected_chunks)


def test_build_context_pack_returns_parse_warnings_for_agent_context(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "governance.md"
    source.write_text(
        "\n".join(
            [
                "# 安全治理",
                "",
                "默认治理规则要求主仓库只读，不默认开放无限网络，不默认绕过审批。",
                "高风险动作必须触发审批，并且审计记录要保留运行参数摘要。",
            ]
        ),
        encoding="utf-8",
    )

    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="安全治理",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    canonical_path = next(processed_root.rglob("canonical-document.json"))
    canonical_payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical_payload["parse_report"]["warnings"] = ["synthetic_parse_warning"]
    canonical_path.write_text(
        json.dumps(canonical_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="默认治理规则是什么？",
        top_k=1,
        per_document_limit=1,
    )

    assert result.selected_chunks
    first = result.selected_chunks[0]
    payload = result.to_json_dict()

    assert first.warnings == ["synthetic_parse_warning"]
    assert payload["selected_chunks"][0]["warnings"] == ["synthetic_parse_warning"]
    assert payload["sections"][0]["items"][0]["warnings"] == ["synthetic_parse_warning"]
    assert "Warnings: `synthetic_parse_warning`" in result.markdown


def test_neighbor_merged_chunks_are_capped_for_large_documents():
    from agent_knowledge_hub.retrieval import _LoadedChunk, _build_neighbor_merged_chunks

    chunks = [
        _LoadedChunk(
            chunk_id=f"chunk-{index}",
            document_version_id="docver-large",
            document_version="v1",
            document_title="Large API Reference",
            source_type="supplier api reference",
            project="qnx-validation",
            supplier="QNX",
            source_path="large.pdf",
            section_path=[str(index)],
            section_titles=[f"Function {index}"],
            page_start=index,
            page_end=index,
            text=f"Function {index} returns constraints and caveats.",
            evidence_ids=[f"span-{index}"],
            quality_status="ok",
            quality_score=100.0,
            allowed_for_context_pack=True,
            quality_gate_reasons=[],
            warnings=[],
        )
        for index in range(1201)
    ]

    assert _build_neighbor_merged_chunks(chunks) == []


def test_quality_gate_adjustment_penalizes_disallowed_chunk_before_ok_status():
    from agent_knowledge_hub.retrieval import _LoadedChunk, _quality_gate_adjustment

    chunk = _LoadedChunk(
        chunk_id="chunk-disallowed",
        document_version_id="docver-disallowed",
        document_version="v1",
        document_title="Disallowed Doc",
        source_type="internal note",
        project="project",
        supplier="internal",
        source_path="disallowed.md",
        section_path=["1"],
        section_titles=["Disallowed"],
        page_start=None,
        page_end=None,
        text="This chunk is externally matched but not allowed for Context Pack.",
        evidence_ids=["span-disallowed"],
        quality_status="ok",
        quality_score=100.0,
        allowed_for_context_pack=False,
        quality_gate_reasons=["manual_block"],
        warnings=[],
    )

    assert _quality_gate_adjustment(chunk) == -56.0


def _ingest_three_topic_docs(tmp_path: Path) -> Path:
    processed_root = tmp_path / "processed"
    architecture = tmp_path / "architecture.md"
    architecture.write_text(
        "\n".join(
            [
                "# 方案选型",
                "",
                "第一阶段正式方案采用第三种 runtime 模式。",
                "Skill/MCP 只适合短期 PoC。",
            ]
        ),
        encoding="utf-8",
    )
    safety = tmp_path / "safety.md"
    safety.write_text(
        "\n".join(
            [
                "# 安全治理",
                "",
                "默认不写主仓库。",
                "高风险动作必须审批。",
            ]
        ),
        encoding="utf-8",
    )
    rollback = tmp_path / "rollback.md"
    rollback.write_text(
        "\n".join(
            [
                "# 灰度与回滚",
                "",
                "功能开关使用 ENABLE_CLAUDE_CODE_RUNTIME=false。",
                "router 停止分发到 claude_code。",
            ]
        ),
        encoding="utf-8",
    )
    for path, title in (
        (architecture, "架构设计"),
        (safety, "安全治理"),
        (rollback, "灰度与回滚"),
    ):
        ingest_file(
            file_path=path,
            out_dir=processed_root,
            title=title,
            source_type="内部设计文档",
            owner="checker",
            document_version="v1",
        )
    return processed_root


def test_estimate_tokens_weights_cjk_higher_than_latin():
    from agent_knowledge_hub.retrieval import estimate_tokens

    assert estimate_tokens("") == 0
    # 14 CJK chars -> int(14 * 1.6) tokens.
    assert estimate_tokens("数据安全治理隔离审批回滚架构") == int(14 * 1.6)
    # Latin text is ~1 token per 4 chars.
    assert estimate_tokens("a" * 40) == 10


def test_build_context_pack_reports_token_usage_without_budget(tmp_path: Path):
    processed_root = _ingest_three_topic_docs(tmp_path)

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="runtime 选型、审批治理、回滚开关分别是什么？",
        top_k=4,
        per_document_limit=2,
    )

    from agent_knowledge_hub.retrieval import estimate_tokens

    assert result.token_budget is None
    assert result.token_used == estimate_tokens(result.markdown)
    assert result.token_used > 0


def test_build_context_pack_trims_chunks_to_fit_token_budget(tmp_path: Path):
    processed_root = tmp_path / "processed"
    body = "这是一段足够长的治理与回滚说明，用于撑大每个证据块的体积，便于预算裁剪验证。" * 6
    for index, (title, topic_line) in enumerate(
        (
            ("架构设计", "第一阶段正式方案采用第三种 runtime 模式。"),
            ("安全治理", "默认不写主仓库，高风险动作必须审批。"),
            ("灰度与回滚", "功能开关使用 ENABLE_CLAUDE_CODE_RUNTIME=false。"),
            ("接口协议", "runtime profile 详情接口返回预算与工具策略。"),
        )
    ):
        path = tmp_path / f"doc-{index}.md"
        path.write_text(
            "\n".join([f"# {title}", "", topic_line, body]),
            encoding="utf-8",
        )
        ingest_file(
            file_path=path,
            out_dir=processed_root,
            title=title,
            source_type="内部设计文档",
            owner="checker",
            document_version="v1",
        )

    query = "runtime 选型、审批治理、回滚开关、profile 接口分别是什么？"
    full = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=query,
        top_k=4,
        per_document_limit=1,
    )
    assert full.chunk_count >= 3

    # Budget large enough for a strict subset (well above the fixed scaffolding
    # plus one chunk) but below the full pack, so trimming drops the tail.
    budget = (full.token_used * 2) // 3
    trimmed = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query=query,
        top_k=4,
        per_document_limit=1,
        token_budget=budget,
    )

    assert trimmed.token_budget == budget
    assert trimmed.chunk_count < full.chunk_count
    assert trimmed.chunk_count >= 1
    assert trimmed.token_used <= budget
    assert "token_budget_too_small:kept_single_best_chunk" not in trimmed.warnings
    assert any(
        warning.startswith("token_budget_exceeded:") for warning in trimmed.warnings
    )
    # The highest-priority chunk must survive trimming.
    assert trimmed.selected_chunks[0].chunk_id == full.selected_chunks[0].chunk_id


def test_build_context_pack_keeps_single_best_chunk_when_budget_too_small(tmp_path: Path):
    processed_root = _ingest_three_topic_docs(tmp_path)

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="runtime 选型、审批治理、回滚开关分别是什么？",
        top_k=4,
        per_document_limit=2,
        token_budget=1,
    )

    assert result.chunk_count == 1
    assert any(
        warning.startswith("token_budget_too_small:") for warning in result.warnings
    )


def test_build_context_pack_warns_when_fts_index_missing(tmp_path: Path):
    processed_root = _ingest_three_topic_docs(tmp_path)

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="runtime 选型是什么？",
        top_k=3,
        per_document_limit=2,
        fts_index_path=tmp_path / "does-not-exist.sqlite3",
    )

    assert result.selected_chunks
    assert any(
        warning.startswith("fts_index_unavailable:not_found") for warning in result.warnings
    )


def test_build_context_pack_warns_when_vector_index_missing(tmp_path: Path):
    processed_root = _ingest_three_topic_docs(tmp_path)

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="runtime 选型是什么？",
        top_k=3,
        per_document_limit=2,
        vector_index_path=tmp_path / "missing-vectors.json",
    )

    assert result.selected_chunks
    assert any(
        warning.startswith("vector_index_unavailable:not_found")
        for warning in result.warnings
    )


def test_context_pack_token_fields_round_trip_through_json(tmp_path: Path):
    from agent_knowledge_hub.retrieval import (
        load_context_pack_result,
        write_context_pack_bundle,
    )

    processed_root = _ingest_three_topic_docs(tmp_path)
    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="runtime 选型、审批治理、回滚开关分别是什么？",
        top_k=4,
        per_document_limit=2,
        token_budget=10_000,
    )

    bundle = write_context_pack_bundle(output_dir=tmp_path / "bundle", result=result)
    reloaded = load_context_pack_result(bundle["json_path"])

    assert reloaded.token_budget == result.token_budget
    assert reloaded.token_used == result.token_used

