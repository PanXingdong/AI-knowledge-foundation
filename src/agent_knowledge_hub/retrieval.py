from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from agent_knowledge_hub.fts_index import query_fts_index
from agent_knowledge_hub.utils import normalize_space, stable_id, write_json
from agent_knowledge_hub.vector_index import query_vector_index


CONTEXT_PACK_SCHEMA_VERSION = "context-pack.v1"
DEFAULT_CONTEXT_PACK_TASK_TYPE = "general_query"
MAX_CHUNKS_FOR_NEIGHBOR_MERGE = 1200
CONTEXT_PACK_STABLE_FIELDS = (
    "schema_version",
    "task_type",
    "task_profile",
    "query",
    "normalized_query",
    "processed_dir",
    "applied_filters",
    "chunk_count",
    "document_count",
    "warnings",
    "sections",
    "selected_chunks",
)
CONTEXT_PACK_ITEM_STABLE_FIELDS = (
    "evidence_number",
    "task_item_type",
    "summary",
    "document_title",
    "document_version",
    "project",
    "supplier",
    "source_type",
    "source_path",
    "section_titles",
    "section_path",
    "matched_clauses",
    "score",
    "retrieval_signals",
    "evidence_ids",
    "quality_status",
    "quality_score",
    "allowed_for_context_pack",
    "quality_gate_reasons",
    "warnings",
)
CONTEXT_PACK_TASK_ALIASES = {
    "": DEFAULT_CONTEXT_PACK_TASK_TYPE,
    "general": DEFAULT_CONTEXT_PACK_TASK_TYPE,
    "general_query": DEFAULT_CONTEXT_PACK_TASK_TYPE,
    "query": DEFAULT_CONTEXT_PACK_TASK_TYPE,
    "constraint": "constraint_lookup",
    "constraint_query": "constraint_lookup",
    "constraints": "constraint_lookup",
    "constraint_lookup": "constraint_lookup",
    "查约束": "constraint_lookup",
    "code_review": "code_review",
    "review": "code_review",
    "代码评审": "code_review",
    "impact": "impact_analysis",
    "impact_analysis": "impact_analysis",
    "影响分析": "impact_analysis",
    "test": "test_design",
    "test_design": "test_design",
    "test_focus": "test_design",
    "test_focus_generation": "test_design",
    "test_review_checklist": "test_design",
    "qa": "test_design",
    "测试设计": "test_design",
    "生成测试关注点": "test_design",
    "生成测试点": "test_design",
    "api": "api_usage",
    "api_usage": "api_usage",
    "interface_lookup": "api_usage",
    "interface_mechanism_lookup": "api_usage",
    "interface_mechanism": "api_usage",
    "接口使用": "api_usage",
    "机制查询": "api_usage",
    "查接口": "api_usage",
    "查接口/机制": "api_usage",
    "查接口机制": "api_usage",
}
CONTEXT_PACK_TASK_PROFILES: dict[str, dict[str, object]] = {
    "general_query": {
        "label": "General Query",
        "intent": "Answer the current question with compact, traceable evidence.",
        "agent_use": (
            "Use summary items first.",
            "Quote evidence ids when an answer depends on a source claim.",
            "Treat quality warnings as uncertainty, not as confirmed facts.",
        ),
        "preferred_sections": ("summary", "evidence", "evidence_appendix"),
    },
    "constraint_lookup": {
        "label": "Constraint Lookup",
        "intent": "Surface applicable constraints, risks, caveats, and source evidence.",
        "agent_use": (
            "Prioritize constraints and caveats over background text.",
            "Keep document version and supplier visible in the answer.",
            "Use evidence trace for any disputed or safety-relevant claim.",
        ),
        "preferred_sections": ("constraints", "risks", "evidence", "evidence_appendix"),
    },
    "code_review": {
        "label": "Code Review",
        "intent": "Provide review-ready constraints, implementation contracts, and risk evidence.",
        "agent_use": (
            "Turn constraints into concrete review checklist items.",
            "Connect risks to changed modules or interfaces before raising findings.",
            "Do not invent a finding when evidence only provides background context.",
        ),
        "preferred_sections": ("risks", "implementation_contracts", "tests", "evidence"),
    },
    "impact_analysis": {
        "label": "Impact Analysis",
        "intent": "Identify likely affected modules, interfaces, tests, and version constraints.",
        "agent_use": (
            "Group evidence by affected area before proposing changes.",
            "Flag version-specific claims explicitly.",
            "Use missing evidence as an open question rather than a conclusion.",
        ),
        "preferred_sections": ("affected_areas", "interfaces", "tests", "open_questions"),
    },
    "test_design": {
        "label": "Test Design",
        "intent": "Extract behaviors, constraints, and risks that should become test coverage.",
        "agent_use": (
            "Translate constraints into observable test conditions.",
            "Preserve preconditions, error cases, and version applicability.",
            "Reference evidence ids beside high-risk test cases.",
        ),
        "preferred_sections": ("behaviors", "edge_cases", "risks", "evidence"),
    },
    "api_usage": {
        "label": "API Usage",
        "intent": "Provide interface signatures, required arguments, return/error behavior, and caveats.",
        "agent_use": (
            "Keep API names, arguments, error codes, and caveats together.",
            "Preserve version and safety classifications when present.",
            "Use evidence ids for behavior that affects implementation choices.",
        ),
        "preferred_sections": ("interfaces", "arguments", "errors", "caveats", "evidence"),
    },
}


ASCII_TOKEN_RE = re.compile(r"[a-z0-9_./=-]+")
CJK_SEQUENCE_RE = re.compile(r"[\u4e00-\u9fff]+")
CLAUSE_SPLIT_RE = re.compile(r"[，,。；;：:\n]+")
LIST_ITEM_RE = re.compile(r"^(\-|\*|\d+\.)\s+")
NUMBERED_ITEM_RE = re.compile(r"^\d+\.\s+")
MARKDOWN_HEADING_RE = re.compile(r"^#+\s*")
INLINE_MARKDOWN_RE = re.compile(r"[`*#>]")
REFERENCE_EVIDENCE_RE = re.compile(r"[（(]\s*证据[^)）]*[)）]")
CJK_STOPGRAMS = {
    "如果",
    "哪些",
    "什么",
    "这个",
    "那个",
    "一下",
    "一个",
    "如何",
    "需要",
    "应该",
    "请综",
    "综合",
    "说明",
}
QUERY_CORE_TERM_STOPWORDS = {
    "a",
    "an",
    "and",
    "api",
    "apis",
    "be",
    "caveat",
    "caveats",
    "consider",
    "considered",
    "constraint",
    "constraints",
    "for",
    "how",
    "or",
    "qnx",
    "related",
    "sdp",
    "should",
    "the",
    "to",
    "using",
    "what",
    "when",
}
QUERY_NOISE_PREFIXES = (
    "只基于给定材料回答",
    "输出中文",
    "明确区分",
    "不要把",
)
APPENDIX_METHOD_QUERY_TERMS = (
    "试验方法",
    "测试方法",
    "验证方法",
    "检测方法",
    "检查点",
    "测试点",
    "试验要求",
    "抓包",
    "境外ip",
    "境外 ip",
    "3600s",
    "test method",
    "packet capture",
)
OUTBOUND_QUERY_TERMS = (
    "出境",
    "境外",
    "跨境",
    "海外",
    "outbound",
    "overseas",
)
APPENDIX_METHOD_BODY_SIGNALS = (
    "判定试验结果是否符合",
    "检查是否",
    "记录试验结果",
    "启动相应功能",
    "开启车辆",
    "抓包",
    "总抓包时长",
    "3600s",
    "解析通信报文",
    "目的ip",
    "目的 ip",
    "境外ip",
    "境外 ip",
    "网络数据",
    "通信通道",
)
REFERENCE_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "third_runtime_choice": (
        "第三种 runtime",
        "third runtime",
        "方案 b",
        "claude_code runtime",
    ),
    "not_skill_mcp_formal": (
        "skill/mcp",
        "skill 或 mcp",
        "普通 skill",
        "不是“工具”",
        "不推荐作为正式方案",
        "只适合极短期 poc",
        "not for formal phase-1",
    ),
    "not_source_embed": (
        "源码嵌入",
        "source embed",
        "工程代价极高",
        "长期维护风险大",
        "与上游演进高度耦合",
        "第一阶段不推荐",
    ),
    "runtime_adapter_router": (
        "runtime adapter",
        "runtime router",
        "agentruntimeadapter",
        "claudecoderuntimeadapter",
        "router abstraction",
    ),
    "sdk_cli_executor": (
        "sdk / cli",
        "sdk 或 cli",
        "sdk 执行器",
        "cli 执行器",
        "claudecodesdkexecutor",
        "claudecodecliexecutor",
    ),
    "repo_worktree_isolation": (
        "repo/worktree",
        "git worktree",
        "worktree",
        "目录隔离",
        "隔离 clone / copy",
        "独立 worktree",
        "每次运行单独目录",
        "worktree path",
        "cc/<agent-name>/<run-id>",
    ),
    "runtime_profile_run_events": (
        "runtime profile",
        "runtime profiles",
        "runtime run",
        "runtime runs",
        "websocket 事件",
        "websocket event",
        "event stream",
        "runtime events",
    ),
    "event_capabilities": (
        "runtime_status",
        "runtime_chunk",
        "runtime_tool",
        "runtime_artifact",
        "runtime_requires_approval",
        "runtime_done",
        "runtime_error",
        "get `/runtime-runs/{run_id}/events`",
        "get /runtime-runs/{run_id}/events",
    ),
    "runtime_metadata_execution_mode": (
        "runtime_metadata.execution_mode",
        "\"execution_mode\":",
        "execution_mode",
    ),
    "runtime_metadata_repo_policy": (
        "runtime_metadata.repo_policy",
        "\"repo_policy\":",
        "repo_policy",
    ),
    "failure_retry_writeback": (
        "回写结果",
        "task/status",
        "手动重试",
        "最后错误摘要",
        "run_id",
        "失败恢复",
        "retry",
        "error summary",
    ),
    "default_no_main_write": (
        "默认不会写主仓库",
        "不默认写主仓库",
        "不能默认写主仓库",
        "主仓库只读",
        "禁止直写主",
        "默认直写 main",
        "默认直写当前开发分支",
        "main repository stays read only",
        "read only",
    ),
    "approval_mechanism": (
        "approval 机制",
        "审批机制",
        "审批协议",
        "approval request",
        "runtime_requires_approval",
        "审批流",
    ),
    "no_write_main": (
        "默认直写 main",
        "不能直写 `main`",
        "不能直写 main",
    ),
    "no_write_current_branch": (
        "默认直写当前开发分支",
        "不能直写当前开发分支",
    ),
    "default_no_unlimited_shell_network": (
        "默认不开放无限 shell / 网络",
        "不默认开放无限 shell",
        "不默认开放无限网络",
        "默认不开放无限 shell",
        "默认不开放无限网络",
        "默认不开放无限 shell / 网络",
        "默认不能开放无限 shell / 网络",
        "无限 shell",
        "无限网络",
        "allowlisted",
        "none",
    ),
    "no_unlimited_shell": (
        "不默认开放无限 shell",
        "默认不开放无限 shell",
        "默认不能开放无限 shell",
    ),
    "no_unlimited_network": (
        "不默认开放无限网络",
        "默认不开放无限网络",
        "默认不能开放无限网络",
    ),
    "default_approval": (
        "不默认绕过审批",
        "默认高风险动作会审批",
        "默认进入审批",
        "approval request",
        "审批策略",
        "高风险 shell",
        "git push",
        "修改保护目录",
        "超预算继续执行",
    ),
    "no_bypass_approval": (
        "不默认绕过审批",
        "默认不绕过审批",
        "不能默认绕过审批",
        "默认不能默认绕过审批",
    ),
    "default_audit": (
        "不默认绕过日志与审计",
        "无审计运行",
        "审计策略",
        "关键事件序列",
        "最终结果",
        "哪个 repo/worktree",
        "audit",
    ),
    "credential_injection": (
        "凭证只由",
        "后端注入",
        "backend injection",
        "injected only by the backend",
        "不把长期密钥写入",
        "最小必要凭证",
        "minimum required token",
        "credentials come from backend injection",
    ),
    "tenant_default_profile": (
        "tenant 默认 profile",
        "默认 profile",
    ),
    "tenant_default_budget": (
        "tenant 默认预算",
        "默认预算",
    ),
    "tenant_default_tool_policy": (
        "tenant 默认工具策略",
        "默认工具策略",
        "工具策略",
    ),
    "network_mode_none": (
        "`none`",
        " none ",
    ),
    "network_mode_allowlisted": (
        "`allowlisted`",
        "allowlisted",
    ),
    "network_mode_default": (
        "`default`",
        " default ",
    ),
    "runtime_profile_get_by_id": (
        "get `/runtime-profiles/{id}`",
        "get /runtime-profiles/{id}",
    ),
    "runtime_profile_patch_by_id": (
        "patch `/runtime-profiles/{id}`",
        "patch /runtime-profiles/{id}",
    ),
    "approval_trigger_shell_write_high_risk_dir": (
        "shell 写入高风险目录",
    ),
    "approval_trigger_modify_protected_branch": (
        "修改受保护分支",
    ),
    "approval_trigger_network_out_of_policy": (
        "网络访问超出策略",
    ),
    "approval_trigger_disabled_tool": (
        "调用被禁用工具",
    ),
    "forbid_danger_skip": (
        "dangerously-skip-permissions",
    ),
    "forbid_run_idless": (
        "无 run_id",
        "run_id 的后台执行",
        "run_id-less",
    ),
    "feature_flag_rollback": (
        "功能开关回滚",
        "feature flag",
        "enable_claude_code_runtime=false",
    ),
    "execution_rollback": (
        "执行回滚",
        "不再分发给 claude_code",
        "退回 native / openclaw",
        "直接拒绝",
    ),
    "internal_tenant_gate": (
        "仅内部 tenant 开启",
        "内部 tenant",
        "第一步",
        "rollout gate",
    ),
    "rollout_progression": (
        "第二步",
        "第三步",
        "仅特定 profile 开启",
        "对更多团队开放",
        "灰度与回滚",
        "测试、灰度、回滚与安全默认值",
        "安全默认值",
    ),
}
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "architecture": (
        "第三种 runtime",
        "runtime 模式",
        "skill/mcp",
        "skill",
        "mcp",
        "源码嵌入",
        "方案选型",
        "总体架构",
        "架构决策",
    ),
    "backend": (
        "后端",
        "执行链路",
        "runtime router",
        "router",
        "adapter",
        "executor",
        "worktree",
        "artifact",
        "回写结果",
        "手动重试",
        "失败恢复",
    ),
    "api": (
        "api",
        "接口",
        "事件",
        "协议",
        "websocket",
        "runtime_status",
        "runtime_requires_approval",
        "runtime_done",
        "runtime_error",
        "get /",
        "post /",
        "/runtime-",
    ),
    "governance": (
        "安全",
        "隔离",
        "审批",
        "凭证",
        "审计",
        "治理",
        "主仓库只读",
        "dangerously-skip-permissions",
        "无限 shell",
        "无限网络",
        "默认必须",
        "禁止",
    ),
    "rollout": (
        "灰度",
        "tenant",
        "feature flag",
        "回滚",
        "验收",
        "测试",
        "上线门槛",
        "内测",
        "上线",
    ),
}
TOPIC_FOCUS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "architecture": (
        "third runtime",
        "第三种 runtime",
        "skill/mcp",
        "source embed",
        "源码嵌入",
        "agentruntimeadapter",
    ),
    "backend": (
        "runtime router",
        "runtime adapter",
        "adapter",
        "router",
        "worktree",
        "run_id",
        "retry",
        "event mapper",
    ),
    "api": (
        "get /",
        "post /",
        "runtime_status",
        "runtime_requires_approval",
        "runtime_done",
        "runtime_error",
        "runtime-runs",
        "runtime-profiles",
    ),
    "governance": (
        "default",
        "审批",
        "approval",
        "audit",
        "credential",
        "read only",
        "只读",
        "dangerously-skip-permissions",
    ),
    "rollout": (
        "tenant",
        "rollback",
        "回滚",
        "验收",
        "acceptance",
        "enable_claude_code_runtime",
        "feature flag",
    ),
}
TOPIC_SECTION_HINTS: dict[str, tuple[tuple[str, float], ...]] = {
    "architecture": (
        ("选型结论", 10.0),
        ("方案 b", 8.0),
        ("方案 a", 6.0),
        ("第三种 runtime", 8.0),
        ("总体架构", 4.0),
        ("备选方案", 4.0),
        ("方案 c", 3.0),
    ),
    "backend": (
        ("runtimeadapter 接口", 14.0),
        ("核心职责", 15.0),
        ("eventmapper", 6.0),
        ("event mapper", 6.0),
        ("worktree", 7.0),
        ("失败恢复", 7.0),
        ("执行器", 5.0),
        ("运行时适配", 5.0),
    ),
    "api": (
        ("runtime runs", 11.0),
        ("websocket 事件类型", 11.0),
        ("runtime_status", 10.0),
        ("runtime_requires_approval", 9.0),
        ("events", 8.0),
        ("审批协议", 7.0),
        ("claude code 事件适配", 6.0),
        ("runtime profiles", 4.0),
        ("artifacts", -12.0),
        ("cancel", -2.0),
        ("错误响应格式", -4.0),
        ("版本策略", -6.0),
    ),
    "governance": (
        ("第一版强制规则", 14.0),
        ("设计目标", 10.0),
        ("目录隔离", 10.0),
        ("分支隔离", 9.0),
        ("审批策略", 10.0),
        ("密钥与凭证", 8.0),
        ("网络策略", 6.0),
        ("工具隔离", 6.0),
        ("审计策略", 6.0),
        ("平台级", 8.0),
        ("agent 级", 6.0),
        ("任务级", 4.0),
        ("治理策略", -1.0),
        ("风险清单", -3.0),
    ),
    "rollout": (
        ("回滚方案", 10.0),
        ("功能开关回滚", 18.0),
        ("执行回滚", 12.0),
        ("数据回滚", 6.0),
        ("上线建议", 8.0),
        ("第一步", 4.0),
        ("第二步", -2.0),
        ("第三步", -4.0),
        ("验收标准", 5.0),
        ("集成测试", 3.0),
        ("单元测试", 2.0),
        ("端到端测试", 3.0),
        ("风险项", -3.0),
        ("最终验收结论模板", -4.0),
    ),
}
QUERY_INTENT_HINTS: dict[str, tuple[tuple[tuple[str, ...], tuple[tuple[str, float], ...]], ...]] = {
    "architecture": (
        (
            ("为什么", "而不是", "skill/mcp", "源码嵌入"),
            (
                ("方案 a", 8.0),
                ("方案 b", 6.0),
                ("方案 c", 8.0),
                ("选型结论", 6.0),
                ("skill 或 mcp", 6.0),
                ("源码嵌入", 6.0),
            ),
        ),
    ),
    "backend": (
        (
            ("后端能力", "最小可交付范围", "实现范围"),
            (
                ("核心职责", 16.0),
                ("runtimeadapter 接口", 14.0),
                ("runtime router", 8.0),
                ("websocket 入口", 6.0),
                ("worktreemanager", 8.0),
            ),
        ),
        (
            ("失败", "重试"),
            (
                ("失败恢复", 8.0),
                ("手动重试", 8.0),
                ("task/status", 6.0),
            ),
        ),
    ),
    "api": (
        (
            ("字段", "websocket", "事件"),
            (
                ("agent 创建", 14.0),
                ("runtime_profile_id", 12.0),
                ("execution_mode", 10.0),
                ("repo_policy", 10.0),
                ("runtime runs", 4.0),
                ("runtime profiles", 4.0),
            ),
        ),
        (
            ("资源接口",),
            (
                ("runtime runs", 12.0),
                ("get /agents/{agent_id}/runtime-runs", 10.0),
                ("get /runtime-runs/{run_id}/events", 8.0),
                ("runtime profiles", 8.0),
                ("post /runtime-profiles", 6.0),
            ),
        ),
        (
            ("事件", "事件能力", "流式过程"),
            (
                ("websocket 事件类型", 12.0),
                ("runtime_status", 10.0),
                ("runtime_requires_approval", 10.0),
                ("runtime_done", 8.0),
                ("runtime_error", 8.0),
                ("events", 8.0),
                ("事件适配", 6.0),
                ("artifacts", -4.0),
            ),
        ),
        (
            ("审批",),
            (
                ("审批协议", 10.0),
                ("runtime_requires_approval", 8.0),
            ),
        ),
    ),
    "governance": (
        (
            ("凭证",),
            (
                ("密钥与凭证", 12.0),
                ("凭证只由", 12.0),
                ("长期密钥", 8.0),
                ("最小必要凭证", 8.0),
            ),
        ),
        (
            ("审计",),
            (
                ("审计策略", 14.0),
                ("谁发起", 10.0),
                ("哪个 Agent", 10.0),
                ("哪个 runtime", 10.0),
                ("运行参数摘要", 8.0),
            ),
        ),
        (
            ("治理层级",),
            (
                ("平台级", 14.0),
                ("治理策略", 14.0),
                ("tenant 默认 profile", 10.0),
                ("agent 级", 9.0),
                ("任务级", 7.0),
            ),
        ),
        (
            ("默认", "默认必须", "治理规则"),
            (
                ("设计目标", 10.0),
                ("目录隔离", 8.0),
                ("分支隔离", 8.0),
                ("审批策略", 8.0),
                ("网络策略", 8.0),
                ("第一版强制规则", 8.0),
            ),
        ),
        (
            ("禁止", "不能", "默认放开"),
            (
                ("第一版强制规则", 12.0),
                ("禁止", 6.0),
                ("审批策略", 4.0),
            ),
        ),
    ),
    "rollout": (
        (
            ("回滚", "回滚条件"),
            (
                ("功能开关回滚", 16.0),
                ("执行回滚", 8.0),
                ("enable_claude_code_runtime", 14.0),
                ("不再分发", 8.0),
                ("第二步", -3.0),
                ("第三步", -4.0),
            ),
        ),
        (
            ("灰度", "tenant", "上线门槛"),
            (
                ("第一步", 8.0),
                ("仅内部 tenant 开启", 10.0),
            ),
        ),
    ),
}
TOPIC_PRIORITY = ("architecture", "backend", "api", "governance", "rollout")
RENDER_TOPIC_ORDER = ("architecture", "backend", "api", "rollout", "governance")
TOPIC_SECTION_LABELS: dict[str, str] = {
    "architecture": "Architecture Decision",
    "backend": "Backend Scope",
    "api": "API / Event Scope",
    "rollout": "Test / Rollback Scope",
    "governance": "Safety / Governance Defaults",
    "other": "Additional Evidence",
}
TASK_TOPIC_SECTION_LABELS: dict[str, dict[str, str]] = {
    "constraint_lookup": {
        "architecture": "Design Constraints",
        "backend": "Implementation Constraints",
        "api": "Interface Constraints",
        "rollout": "Validation / Rollback Constraints",
        "governance": "Safety / Governance Constraints",
        "other": "Additional Constraints",
    },
    "code_review": {
        "architecture": "Review Design Decisions",
        "backend": "Review Implementation Scope",
        "api": "Review Interface Contracts",
        "rollout": "Review Tests / Rollback",
        "governance": "Review Safety Risks",
        "other": "Additional Review Evidence",
    },
    "impact_analysis": {
        "architecture": "Impacted Decisions",
        "backend": "Impacted Backend Scope",
        "api": "Impacted Interfaces",
        "rollout": "Impacted Tests / Rollback",
        "governance": "Impacted Governance Rules",
        "other": "Additional Impact Evidence",
    },
    "test_design": {
        "architecture": "Design Behaviors To Verify",
        "backend": "Implementation Behaviors To Verify",
        "api": "Interface Behaviors To Verify",
        "rollout": "Rollback / Acceptance Tests",
        "governance": "Safety / Governance Tests",
        "other": "Additional Test Evidence",
    },
    "api_usage": {
        "architecture": "Design Context",
        "backend": "Implementation Context",
        "api": "API Usage Evidence",
        "rollout": "API Validation / Rollback",
        "governance": "API Safety / Governance",
        "other": "Additional API Evidence",
    },
}
TASK_TOPIC_ITEM_TYPES: dict[str, dict[str, str]] = {
    "constraint_lookup": {
        "architecture": "design_constraint",
        "backend": "implementation_constraint",
        "api": "interface_constraint",
        "rollout": "validation_constraint",
        "governance": "safety_constraint",
        "other": "supporting_constraint",
    },
    "code_review": {
        "architecture": "review_design_context",
        "backend": "review_implementation_context",
        "api": "review_interface_contract",
        "rollout": "review_test_or_rollback_context",
        "governance": "review_risk",
        "other": "review_supporting_evidence",
    },
    "impact_analysis": {
        "architecture": "impacted_decision",
        "backend": "impacted_implementation",
        "api": "impacted_interface",
        "rollout": "impacted_test_or_rollback",
        "governance": "impacted_governance",
        "other": "impact_supporting_evidence",
    },
    "test_design": {
        "architecture": "design_test_condition",
        "backend": "implementation_test_condition",
        "api": "interface_test_condition",
        "rollout": "rollout_test_condition",
        "governance": "safety_test_condition",
        "other": "test_supporting_evidence",
    },
    "api_usage": {
        "architecture": "api_design_context",
        "backend": "api_implementation_context",
        "api": "api_contract",
        "rollout": "api_validation_context",
        "governance": "api_safety_context",
        "other": "api_supporting_evidence",
    },
}
TOPIC_SUBFACET_HINTS: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {
    "api": {
        "agent_create_fields": {
            "chunk": (
                "runtime_profile_id",
                "agent 创建",
            ),
            "query": (
                "字段",
                "参数",
                "创建",
                "agent 创建",
                "创建字段",
                "创建参数",
                "runtime_profile_id",
                "execution_mode",
                "repo_policy",
            ),
        },
        "runtime_profile_routes_basic": {
            "chunk": (
                "post `/runtime-profiles`",
                "get `/runtime-profiles`",
                "post /runtime-profiles",
                "get /runtime-profiles",
            ),
            "query": (
                "profile",
                "profiles",
                "runtime profile",
                "runtime profiles",
            ),
        },
        "runtime_profile_routes_detail": {
            "chunk": (
                "get `/runtime-profiles/{id}`",
                "patch `/runtime-profiles/{id}`",
                "get /runtime-profiles/{id}",
                "patch /runtime-profiles/{id}",
            ),
            "query": (
                "profile",
                "profiles",
                "runtime profile",
                "runtime profiles",
            ),
        },
        "runtime_run_routes": {
            "chunk": (
                "get `/agents/{agent_id}/runtime-runs`",
                "get /agents/{agent_id}/runtime-runs",
                "get `/runtime-runs/{run_id}`",
                "get /runtime-runs/{run_id}",
                "get `/runtime-runs/{run_id}/events`",
                "get /runtime-runs/{run_id}/events",
            ),
            "query": (
                "runtime run",
                "runtime runs",
                "run",
                "runs",
                "资源接口",
                "事件查询",
                "events",
            ),
        },
        "event_types": {
            "chunk": (
                "websocket 事件类型",
                "runtime_status",
                "runtime_requires_approval",
                "runtime_done",
                "runtime_error",
            ),
            "query": (
                "websocket",
                "事件",
                "事件能力",
                "事件类型",
                "流式过程",
            ),
        },
        "approval_protocol": {
            "chunk": (
                "shell 写入高风险目录",
                "修改受保护分支",
                "网络访问超出策略",
                "调用被禁用工具",
            ),
            "query": (
                "审批",
                "approval",
                "触发条件",
                "禁止",
                "不能默认放开",
            ),
        },
    },
    "governance": {
        "isolation_defaults": {
            "chunk": (
                "主仓库只读",
                "工作发生在独立 worktree",
                "每次运行单独目录",
                "cc/<agent-name>/<run-id>",
                "默认直写 `main`",
                "默认直写当前开发分支",
            ),
            "query": (
                "隔离",
                "隔离策略",
                "repo/worktree",
                "worktree",
                "主仓库",
                "分支隔离",
                "分支",
            ),
        },
        "defaults": {
            "chunk": (
                "不默认开放无限 shell",
                "不默认开放无限网络",
                "不默认绕过审批",
                "默认不开放无限 shell",
                "默认不开放无限网络",
                "默认不绕过审批",
                "默认不能开放无限 shell",
                "默认不能开放无限网络",
                "默认不能默认绕过审批",
            ),
            "query": (
                "默认治理规则",
                "默认规则",
                "默认必须",
                "默认",
            ),
        },
        "credentials": {
            "chunk": (
                "密钥与凭证",
                "凭证只由",
                "长期密钥",
                "最小必要凭证",
            ),
            "query": (
                "凭证",
                "密钥",
                "credential",
            ),
        },
        "audit": {
            "chunk": (
                "审计策略",
                "谁发起",
                "哪个 Agent",
                "哪个 runtime",
                "运行参数摘要",
            ),
            "query": (
                "审计",
                "日志",
                "谁发起",
                "运行参数",
                "audit",
            ),
        },
        "governance_layers": {
            "chunk": (
                "治理策略",
                "tenant 默认 profile",
                "Agent 级",
                "任务级",
            ),
            "query": (
                "治理层级",
                "治理策略",
                "平台级",
                "Agent 级",
                "任务级",
            ),
        },
        "platform_defaults": {
            "chunk": (
                "tenant 默认 profile",
                "tenant 默认预算",
                "tenant 默认工具策略",
            ),
            "query": (
                "治理层级",
                "平台级",
                "tenant 默认",
                "治理规则",
            ),
        },
        "network_policy_modes": {
            "chunk": (
                "网络策略",
                "`none`",
                "`allowlisted`",
                "`default`",
                "allowlisted",
                "default",
            ),
            "query": (
                "网络",
                "默认放开",
                "治理规则",
                "隔离",
            ),
        },
        "forbidden_rules": {
            "chunk": (
                "第一版强制规则",
                "dangerously-skip-permissions",
                "无 run_id",
                "禁止",
            ),
            "query": (
                "禁止",
                "不能默认放开",
                "默认放开",
            ),
        },
    },
    "rollout": {
        "rollout_gate": {
            "chunk": (
                "第一步",
                "仅内部 tenant 开启",
                "内部 tenant",
            ),
            "query": (
                "灰度",
                "tenant",
                "上线门槛",
            ),
        },
        "rollout_progression": {
            "chunk": (
                "第二步",
                "第三步",
                "仅特定 profile 开启",
                "对更多团队开放",
            ),
            "query": (
                "灰度",
                "上线门槛",
                "分阶段",
                "第二步",
                "第三步",
                "更多团队",
                "特定 profile",
            ),
        },
        "feature_flag": {
            "chunk": (
                "功能开关回滚",
                "enable_claude_code_runtime=false",
                "feature flag",
            ),
            "query": (
                "功能开关",
                "feature flag",
                "回滚",
            ),
        },
        "execution_rollback": {
            "chunk": (
                "执行回滚",
                "不再分发给 claude_code",
                "退回 native / openclaw",
            ),
            "query": (
                "执行回滚",
                "回滚条件",
            ),
        },
        "acceptance": {
            "chunk": (
                "功能验收",
                "稳定性验收",
                "安全验收",
                "可以创建 claude_code agent",
                "连续执行 20 次",
            ),
            "query": (
                "验收",
                "测试",
                "稳定性",
                "安全门槛",
            ),
        },
    },
}
TOPIC_SUBFACET_WEIGHTS: dict[str, dict[str, float]] = {
    "api": {
        "agent_create_fields": 4.0,
        "runtime_run_routes": 3.0,
        "event_types": 2.0,
        "runtime_profile_routes_basic": 1.0,
        "runtime_profile_routes_detail": 2.5,
        "approval_protocol": 2.5,
    },
    "governance": {
        "isolation_defaults": 4.5,
        "credentials": 4.0,
        "audit": 4.0,
        "governance_layers": 4.0,
        "platform_defaults": 3.0,
        "network_policy_modes": 3.0,
        "defaults": 1.0,
        "forbidden_rules": 1.0,
    },
    "rollout": {
        "rollout_progression": 2.5,
        "feature_flag": 3.0,
        "rollout_gate": 2.0,
        "execution_rollback": 1.0,
        "acceptance": 0.5,
    },
}


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_version_id: str
    document_version: str
    document_title: str
    source_type: str
    project: str
    supplier: str
    source_path: str
    section_path: list[str]
    section_titles: list[str]
    page_start: int | None
    page_end: int | None
    text: str
    evidence_ids: list[str]
    score: float
    matched_clauses: list[str]
    quality_status: str
    quality_score: float | None
    allowed_for_context_pack: bool
    quality_gate_reasons: list[str]
    warnings: list[str]
    retrieval_signals: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ContextPackResult:
    schema_version: str
    task_type: str
    task_profile: dict[str, object]
    query: str
    normalized_query: str
    processed_dir: Path
    applied_filters: dict[str, list[str]]
    selected_chunks: list[RetrievedChunk]
    markdown: str
    chunk_count: int
    document_count: int
    warnings: list[str]

    def to_json_dict(self) -> dict[str, object]:
        sections = _build_context_pack_section_payloads(
            self.selected_chunks,
            task_type=self.task_type,
        )
        return {
            "schema_version": self.schema_version,
            "task_type": self.task_type,
            "task_profile": dict(self.task_profile),
            "contract": _build_context_pack_contract(),
            "query": self.query,
            "normalized_query": self.normalized_query,
            "processed_dir": str(self.processed_dir),
            "applied_filters": {key: list(value) for key, value in self.applied_filters.items()},
            "chunk_count": self.chunk_count,
            "document_count": self.document_count,
            "warnings": list(self.warnings),
            "sections": sections,
            "selected_chunks": [chunk.to_dict() for chunk in self.selected_chunks],
        }

    def to_summary_dict(self, *, output_dir: Path | None = None) -> dict[str, object]:
        sections = _build_context_pack_section_payloads(
            self.selected_chunks,
            task_type=self.task_type,
            include_full_chunk=False,
        )
        return {
            "schema_version": self.schema_version,
            "task_type": self.task_type,
            "task_profile": dict(self.task_profile),
            "contract": _build_context_pack_contract(),
            "processed_dir": str(self.processed_dir),
            "query": self.query,
            "normalized_query": self.normalized_query,
            "applied_filters": {key: list(value) for key, value in self.applied_filters.items()},
            "chunk_count": self.chunk_count,
            "document_count": self.document_count,
            "warnings": list(self.warnings),
            "output_dir": str(output_dir) if output_dir else None,
            "sections": sections,
            "selected_chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "document_title": chunk.document_title,
                    "document_version": chunk.document_version,
                    "project": chunk.project,
                    "supplier": chunk.supplier,
                    "source_type": chunk.source_type,
                    "source_path": chunk.source_path,
                    "score": round(chunk.score, 4),
                    "matched_clauses": chunk.matched_clauses,
                    "evidence_ids": chunk.evidence_ids,
                    "quality_status": chunk.quality_status,
                    "allowed_for_context_pack": chunk.allowed_for_context_pack,
                    "warnings": chunk.warnings,
                    "retrieval_signals": chunk.retrieval_signals,
                }
                for chunk in self.selected_chunks
            ],
        }


@dataclass(frozen=True)
class SearchResult:
    query: str
    normalized_query: str
    processed_dir: Path
    applied_filters: dict[str, list[str]]
    results: list[RetrievedChunk]
    result_count: int
    document_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "normalized_query": self.normalized_query,
            "processed_dir": str(self.processed_dir),
            "applied_filters": {key: list(value) for key, value in self.applied_filters.items()},
            "result_count": self.result_count,
            "document_count": self.document_count,
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(frozen=True)
class ReferenceGapReport:
    reference_markdown_path: Path
    covered_reference_items: list[str]
    missing_reference_items: list[str]
    covered_reference_item_count: int
    missing_reference_item_count: int
    markdown: str

    def to_dict(self) -> dict[str, object]:
        return {
            "reference_markdown_path": str(self.reference_markdown_path),
            "covered_reference_item_count": self.covered_reference_item_count,
            "missing_reference_item_count": self.missing_reference_item_count,
            "covered_reference_items": self.covered_reference_items,
            "missing_reference_items": self.missing_reference_items,
        }


@dataclass(frozen=True)
class EvidenceChunkReference:
    chunk_id: str
    section_path: list[str]
    section_titles: list[str]
    page_start: int | None
    page_end: int | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceTraceResult:
    evidence_id: str
    document_id: str
    document_title: str
    document_version_id: str
    document_version: str
    source_type: str
    source_path: str
    created_at: str
    page: int | None
    section_path: list[str]
    section_titles: list[str]
    block_id: str
    text: str
    bbox: list[float] | None
    chunk_references: list[EvidenceChunkReference]

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "document_version_id": self.document_version_id,
            "document_version": self.document_version,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "created_at": self.created_at,
            "page": self.page,
            "section_path": list(self.section_path),
            "section_titles": list(self.section_titles),
            "block_id": self.block_id,
            "text": self.text,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "chunk_references": [reference.to_dict() for reference in self.chunk_references],
        }


@dataclass(frozen=True)
class _LoadedChunk:
    chunk_id: str
    document_version_id: str
    document_version: str
    document_title: str
    source_type: str
    project: str
    supplier: str
    source_path: str
    section_path: list[str]
    section_titles: list[str]
    page_start: int | None
    page_end: int | None
    text: str
    evidence_ids: list[str]
    quality_status: str
    quality_score: float | None
    allowed_for_context_pack: bool
    quality_gate_reasons: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class _CandidateScore:
    chunk: _LoadedChunk
    overall_score: float
    clause_scores: tuple[float, ...]
    clause_hits: frozenset[int]
    coherence_bonus: float
    topic_scores: dict[str, float]
    topic_subfacets: dict[str, frozenset[str]]
    retrieval_signals: frozenset[str]


def build_context_pack_for_processed_dir(
    *,
    processed_dir: Path | str,
    query: str,
    task_type: str = DEFAULT_CONTEXT_PACK_TASK_TYPE,
    top_k: int = 8,
    per_document_limit: int = 2,
    metadata_filters: dict[str, list[str]] | None = None,
    fts_index_path: Path | str | None = None,
    vector_index_path: Path | str | None = None,
) -> ContextPackResult:
    processed_root = Path(processed_dir).resolve()
    normalized_task_type = _normalize_context_pack_task_type(task_type)
    task_profile = _build_context_pack_task_profile(normalized_task_type)
    if top_k <= 0:
        raise ValueError("top_k must be > 0")
    if per_document_limit <= 0:
        raise ValueError("per_document_limit must be > 0")
    if not query.strip():
        raise ValueError("query must not be empty")
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")

    loaded_chunks = _load_processed_chunks(processed_root)
    if not loaded_chunks:
        raise ValueError(f"No chunks.jsonl files found under: {processed_root}")
    normalized_filters = _normalize_metadata_filters(metadata_filters)
    filtered_chunks = _filter_loaded_chunks(
        chunks=loaded_chunks,
        metadata_filters=normalized_filters,
    )
    if normalized_filters and not filtered_chunks:
        raise ValueError("No chunks matched metadata filters.")

    normalized_query = _normalize_query_text(query)
    clauses = _split_query_clauses(normalized_query)
    clause_tokens = [_tokenize_for_search(clause) for clause in clauses]
    query_tokens = _tokenize_for_search(normalized_query)
    desired_topics = _derive_query_topics(normalized_query, clauses)
    requested_subfacets = _derive_requested_topic_subfacets(
        query=normalized_query,
        clauses=clauses,
        desired_topics=desired_topics,
    )
    fts_bonus_by_chunk_id = _load_fts_bonus_by_chunk_id(
        fts_index_path=fts_index_path,
        query=normalized_query,
        limit=max(20, top_k * max(4, per_document_limit)),
    )
    vector_bonus_by_chunk_id = _load_vector_bonus_by_chunk_id(
        vector_index_path=vector_index_path,
        query=normalized_query,
        limit=max(20, top_k * max(4, per_document_limit)),
    )
    retrieval_chunks = filtered_chunks if normalized_filters else loaded_chunks
    eligible_chunks = [chunk for chunk in retrieval_chunks if chunk.allowed_for_context_pack]
    external_bonus_by_chunk_id = {
        **fts_bonus_by_chunk_id,
        **{
            chunk_id: max(vector_bonus, fts_bonus_by_chunk_id.get(chunk_id, 0.0))
            for chunk_id, vector_bonus in vector_bonus_by_chunk_id.items()
        },
    }
    if external_bonus_by_chunk_id:
        eligible_chunk_ids = {chunk.chunk_id for chunk in eligible_chunks}
        external_gate_bypass_chunks = [
            chunk
            for chunk in retrieval_chunks
            if chunk.chunk_id in external_bonus_by_chunk_id and chunk.chunk_id not in eligible_chunk_ids
        ]
        eligible_chunks.extend(external_gate_bypass_chunks)
    if not eligible_chunks:
        eligible_chunks = retrieval_chunks
    # Build / reuse BM25 corpus stats (query-independent, safe to cache for
    # the lifetime of the service process for a fixed processed_dir).
    _bm25_cache_key = str(processed_root)
    if _bm25_cache_key not in _BM25_CONTEXT_CACHE:
        _BM25_CONTEXT_CACHE[_bm25_cache_key] = _build_bm25_context(list(loaded_chunks))
    cached_bm25_context: _Bm25Context = _BM25_CONTEXT_CACHE[_bm25_cache_key]  # type: ignore[assignment]
    scored_chunks = _build_candidate_scores(
        chunks=eligible_chunks,
        query_tokens=query_tokens,
        clause_tokens=clause_tokens,
        desired_topics=desired_topics,
        query_text=normalized_query,
        fts_bonus_by_chunk_id=fts_bonus_by_chunk_id,
        vector_bonus_by_chunk_id=vector_bonus_by_chunk_id,
        bm25_context=cached_bm25_context,
    )
    # _select_candidates is O(pool_size²). Candidates are already sorted by
    # score, so capping the pool here gives ample diversity room while avoiding
    # a quadratic blowup on large corpora (e.g. 9 000+ neighbor-merged chunks).
    _pool_size = min(max(top_k * 30, 300), len(scored_chunks))
    scored_chunks = scored_chunks[:_pool_size]
    selected = _select_candidates(
        candidates=scored_chunks,
        clauses=clauses,
        top_k=top_k,
        per_document_limit=per_document_limit,
        desired_topics=desired_topics,
        requested_subfacets=requested_subfacets,
        query_text=normalized_query,
    )

    selected_chunks = [
        RetrievedChunk(
            chunk_id=candidate.chunk.chunk_id,
            document_version_id=candidate.chunk.document_version_id,
            document_version=candidate.chunk.document_version,
            document_title=candidate.chunk.document_title,
            source_type=candidate.chunk.source_type,
            project=candidate.chunk.project,
            supplier=candidate.chunk.supplier,
            source_path=candidate.chunk.source_path,
            section_path=list(candidate.chunk.section_path),
            section_titles=list(candidate.chunk.section_titles),
            page_start=candidate.chunk.page_start,
            page_end=candidate.chunk.page_end,
            text=candidate.chunk.text,
            evidence_ids=list(candidate.chunk.evidence_ids),
            score=round(candidate.overall_score, 4),
            matched_clauses=[clauses[index] for index in sorted(candidate.clause_hits)],
            quality_status=candidate.chunk.quality_status,
            quality_score=candidate.chunk.quality_score,
            allowed_for_context_pack=candidate.chunk.allowed_for_context_pack,
            quality_gate_reasons=list(candidate.chunk.quality_gate_reasons),
            warnings=list(candidate.chunk.warnings),
            retrieval_signals=sorted(candidate.retrieval_signals),
        )
        for candidate in selected
    ]
    warnings = _build_context_pack_warnings(selected_chunks)
    markdown = _render_context_pack_markdown(
        query=normalized_query,
        task_type=normalized_task_type,
        task_profile=task_profile,
        warnings=warnings,
        chunks=selected_chunks,
    )
    return ContextPackResult(
        schema_version=CONTEXT_PACK_SCHEMA_VERSION,
        task_type=normalized_task_type,
        task_profile=task_profile,
        query=query,
        normalized_query=normalized_query,
        processed_dir=processed_root,
        applied_filters=normalized_filters,
        selected_chunks=selected_chunks,
        markdown=markdown,
        chunk_count=len(selected_chunks),
        document_count=len({chunk.document_version_id for chunk in selected_chunks}),
        warnings=warnings,
    )


def _normalize_context_pack_task_type(task_type: str | None) -> str:
    normalized = normalize_space(str(task_type or DEFAULT_CONTEXT_PACK_TASK_TYPE)).lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    resolved = CONTEXT_PACK_TASK_ALIASES.get(normalized)
    if resolved:
        return resolved
    allowed = ", ".join(sorted(CONTEXT_PACK_TASK_PROFILES))
    raise ValueError(f"Unsupported task_type '{task_type}'. Supported task types: {allowed}")


def _build_context_pack_task_profile(task_type: str) -> dict[str, object]:
    profile = CONTEXT_PACK_TASK_PROFILES[task_type]
    return {
        "label": str(profile["label"]),
        "intent": str(profile["intent"]),
        "agent_use": list(profile["agent_use"]),
        "preferred_sections": list(profile["preferred_sections"]),
    }


def _build_context_pack_contract() -> dict[str, object]:
    return {
        "name": "Context Pack v1",
        "schema_version": CONTEXT_PACK_SCHEMA_VERSION,
        "stability": "stable_for_layer3",
        "stable_fields": list(CONTEXT_PACK_STABLE_FIELDS),
        "item_stable_fields": list(CONTEXT_PACK_ITEM_STABLE_FIELDS),
    }


def _build_context_pack_warnings(chunks: list[RetrievedChunk]) -> list[str]:
    warnings: list[str] = []
    for chunk in chunks:
        if not chunk.allowed_for_context_pack:
            warnings.append(
                f"quality_gate_bypassed:{chunk.document_title}:{chunk.chunk_id}"
            )
        for reason in chunk.quality_gate_reasons:
            warnings.append(f"quality_gate_reason:{chunk.document_title}:{reason}")
        for warning in chunk.warnings:
            warnings.append(f"source_warning:{chunk.document_title}:{warning}")
    return list(dict.fromkeys(warnings))


def search_processed_dir(
    *,
    processed_dir: Path | str,
    query: str,
    top_k: int = 8,
    per_document_limit: int = 2,
    metadata_filters: dict[str, list[str]] | None = None,
    fts_index_path: Path | str | None = None,
    vector_index_path: Path | str | None = None,
) -> SearchResult:
    context_pack = build_context_pack_for_processed_dir(
        processed_dir=processed_dir,
        query=query,
        top_k=top_k,
        per_document_limit=per_document_limit,
        metadata_filters=metadata_filters,
        fts_index_path=fts_index_path,
        vector_index_path=vector_index_path,
    )
    return SearchResult(
        query=context_pack.query,
        normalized_query=context_pack.normalized_query,
        processed_dir=context_pack.processed_dir,
        applied_filters=dict(context_pack.applied_filters),
        results=list(context_pack.selected_chunks),
        result_count=len(context_pack.selected_chunks),
        document_count=context_pack.document_count,
    )


def trace_evidence_in_processed_dir(
    *,
    processed_dir: Path | str,
    evidence_id: str,
) -> EvidenceTraceResult:
    processed_root = Path(processed_dir).resolve()
    normalized_evidence_id = normalize_space(evidence_id)
    if not normalized_evidence_id:
        raise ValueError("evidence_id must not be empty")
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")

    for chunks_path, document_payload in _iter_latest_processed_versions(processed_root):
        evidence_payload = _find_evidence_payload(document_payload, normalized_evidence_id)
        if evidence_payload is None:
            continue

        section_titles_by_path = _build_section_title_map(document_payload)
        trace_section_path = [str(part) for part in (evidence_payload.get("section_path") or [])]
        document_info = document_payload.get("document") or {}
        version_info = document_payload.get("document_version") or {}

        return EvidenceTraceResult(
            evidence_id=normalized_evidence_id,
            document_id=str(document_info.get("document_id") or ""),
            document_title=normalize_space(str(document_info.get("title") or "")),
            document_version_id=str(version_info.get("document_version_id") or ""),
            document_version=normalize_space(str(version_info.get("version") or "")),
            source_type=normalize_space(str(document_info.get("source_type") or "")),
            source_path=normalize_space(str(version_info.get("file_path") or "")),
            created_at=normalize_space(
                str(version_info.get("created_at") or document_info.get("created_at") or "")
            ),
            page=evidence_payload.get("page"),
            section_path=trace_section_path,
            section_titles=_derive_section_titles(
                section_path=trace_section_path,
                section_titles_by_path=section_titles_by_path,
            ),
            block_id=str(evidence_payload.get("block_id") or ""),
            text=str(evidence_payload.get("text") or ""),
            bbox=_normalize_optional_bbox(evidence_payload.get("bbox")),
            chunk_references=_load_evidence_chunk_references(
                chunks_path=chunks_path,
                evidence_id=normalized_evidence_id,
                section_titles_by_path=section_titles_by_path,
            ),
        )

    raise ValueError(f"Evidence not found: {normalized_evidence_id}")


def write_context_pack_bundle(
    *,
    output_dir: Path | str,
    result: ContextPackResult,
) -> dict[str, Path]:
    bundle_dir = Path(output_dir).resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = bundle_dir / "context_pack.md"
    json_path = bundle_dir / "context_pack.json"
    summary_path = bundle_dir / "context_pack-summary.json"

    markdown_path.write_text(result.markdown, encoding="utf-8")
    write_json(json_path, result.to_json_dict())
    write_json(summary_path, result.to_summary_dict(output_dir=bundle_dir))
    return {
        "markdown_path": markdown_path,
        "json_path": json_path,
        "summary_path": summary_path,
    }


def load_context_pack_result(path: Path | str) -> ContextPackResult:
    json_path = Path(path).resolve()
    payload = _read_json(json_path)
    selected_chunks = [
        RetrievedChunk(
            chunk_id=item["chunk_id"],
            document_version_id=item["document_version_id"],
            document_version=str(item.get("document_version") or "unknown"),
            document_title=item["document_title"],
            source_type=item["source_type"],
            project=str(item.get("project") or "unknown"),
            supplier=str(item.get("supplier") or "unknown"),
            source_path=item["source_path"],
            section_path=list(item.get("section_path") or []),
            section_titles=list(item.get("section_titles") or []),
            page_start=item.get("page_start"),
            page_end=item.get("page_end"),
            text=item.get("text") or "",
            evidence_ids=list(item.get("evidence_ids") or []),
            score=float(item.get("score") or 0.0),
            matched_clauses=list(item.get("matched_clauses") or []),
            quality_status=str(item.get("quality_status") or "unknown"),
            quality_score=_optional_float(item.get("quality_score")),
            allowed_for_context_pack=bool(item.get("allowed_for_context_pack", True)),
            quality_gate_reasons=list(item.get("quality_gate_reasons") or []),
            warnings=list(item.get("warnings") or []),
            retrieval_signals=list(item.get("retrieval_signals") or ["fallback"]),
        )
        for item in payload.get("selected_chunks") or []
    ]
    task_type = _normalize_context_pack_task_type(str(payload.get("task_type") or ""))
    task_profile = _build_context_pack_task_profile(task_type)
    warnings = [str(item) for item in (payload.get("warnings") or [])]
    markdown = _render_context_pack_markdown(
        query=payload.get("normalized_query") or payload.get("query") or "",
        task_type=task_type,
        task_profile=task_profile,
        warnings=warnings,
        chunks=selected_chunks,
    )
    return ContextPackResult(
        schema_version=str(payload.get("schema_version") or CONTEXT_PACK_SCHEMA_VERSION),
        task_type=task_type,
        task_profile=task_profile,
        query=payload.get("query") or "",
        normalized_query=payload.get("normalized_query") or payload.get("query") or "",
        processed_dir=Path(payload.get("processed_dir") or json_path.parent),
        applied_filters={
            str(key): [str(item) for item in (values or [])]
            for key, values in (payload.get("applied_filters") or {}).items()
        },
        selected_chunks=selected_chunks,
        markdown=markdown,
        chunk_count=int(payload.get("chunk_count") or len(selected_chunks)),
        document_count=int(
            payload.get("document_count")
            or len({chunk.document_version_id for chunk in selected_chunks})
        ),
        warnings=warnings,
    )


def compare_context_pack_against_reference(
    *,
    auto_result: ContextPackResult,
    reference_markdown_path: Path | str,
) -> ReferenceGapReport:
    reference_path = Path(reference_markdown_path).resolve()
    reference_text = reference_path.read_text(encoding="utf-8")
    reference_items = _extract_reference_items(reference_text)
    auto_corpus = normalize_space(
        "\n".join(
            "\n".join(
                [
                    chunk.document_title,
                    " > ".join(chunk.section_titles),
                    ".".join(chunk.section_path),
                    chunk.text,
                ]
            )
            for chunk in auto_result.selected_chunks
        )
    ).lower()
    auto_tokens = _tokenize_for_search(auto_corpus)
    auto_concepts = _extract_reference_concepts(auto_corpus)

    covered: list[str] = []
    missing: list[str] = []
    for item in reference_items:
        normalized_item = _normalize_reference_item_text(item)
        item_tokens = _tokenize_for_search(normalized_item)
        item_concepts = _extract_reference_concepts(normalized_item)
        if _item_is_covered(
            normalized_item=normalized_item,
            item_tokens=item_tokens,
            item_concepts=item_concepts,
            auto_corpus=auto_corpus,
            auto_tokens=auto_tokens,
            auto_concepts=auto_concepts,
        ):
            covered.append(item)
        else:
            missing.append(item)

    markdown = _render_gap_report_markdown(
        reference_markdown_path=reference_path,
        covered=covered,
        missing=missing,
    )
    return ReferenceGapReport(
        reference_markdown_path=reference_path,
        covered_reference_items=covered,
        missing_reference_items=missing,
        covered_reference_item_count=len(covered),
        missing_reference_item_count=len(missing),
        markdown=markdown,
    )


def write_gap_report_bundle(
    *,
    output_dir: Path | str,
    report: ReferenceGapReport,
) -> dict[str, Path]:
    bundle_dir = Path(output_dir).resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = bundle_dir / "context_pack_gap_report.md"
    json_path = bundle_dir / "context_pack_gap_report.json"

    markdown_path.write_text(report.markdown, encoding="utf-8")
    write_json(json_path, report.to_dict())
    return {
        "markdown_path": markdown_path,
        "json_path": json_path,
    }


# ---------------------------------------------------------------------------
# Module-level caches for expensive repeated computations.
# These persist across HTTP requests for the lifetime of the service process,
# eliminating repeated disk I/O and corpus tokenization.
# Call clear_retrieval_caches() to invalidate after re-ingestion.
# ---------------------------------------------------------------------------
_CHUNK_CACHE: dict[str, list] = {}          # str(processed_dir) → list[_LoadedChunk]
_BM25_CONTEXT_CACHE: dict[str, object] = {} # str(processed_dir) → _Bm25Context
# chunk_id → (topic_scores, topic_subfacets, coherence, structure, ev_quality, thin_penalty)
_CHUNK_STATIC_SCORE_CACHE: dict[str, tuple] = {}
# chunk_id → (chunk_tokens, title_normalized, section_text, leaf_section_text)
_CHUNK_TOKEN_CACHE: dict[str, tuple] = {}


def clear_retrieval_caches() -> None:
    """Invalidate all module-level retrieval caches (call after re-ingestion)."""
    _CHUNK_CACHE.clear()
    _BM25_CONTEXT_CACHE.clear()
    _CHUNK_STATIC_SCORE_CACHE.clear()
    _CHUNK_TOKEN_CACHE.clear()


def _load_processed_chunks(processed_dir: Path) -> list[_LoadedChunk]:
    cache_key = str(processed_dir)
    if cache_key in _CHUNK_CACHE:
        return _CHUNK_CACHE[cache_key]  # type: ignore[return-value]
    chunks: list[_LoadedChunk] = []
    for chunks_path, document_payload in _iter_latest_processed_versions(processed_dir):
        document_chunks: list[_LoadedChunk] = []
        document_info = document_payload.get("document", {}) if document_payload else {}
        document_version_info = document_payload.get("document_version", {}) if document_payload else {}
        document_title = (
            document_info.get("title") if document_payload else None
        )
        source_path = (
            document_version_info.get("file_path")
            if document_payload
            else None
        )
        source_type = normalize_space(str(document_info.get("source_type") or "unknown"))
        project = normalize_space(str(document_info.get("project") or "unknown"))
        supplier = normalize_space(str(document_info.get("supplier") or "unknown"))
        document_version = normalize_space(str(document_version_info.get("version") or "unknown"))
        section_titles_by_path = _build_section_title_map(document_payload)
        quality_status, quality_score, allowed_for_context_pack, quality_gate_reasons = (
            _extract_document_quality_gate(document_payload)
        )
        warnings = _extract_document_warnings(document_payload)
        for line in chunks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            metadata = payload.get("metadata") or {}
            section_path = list(payload.get("section_path") or [])
            document_chunks.append(
                _LoadedChunk(
                    chunk_id=payload["chunk_id"],
                    document_version_id=payload["document_version_id"],
                    document_version=document_version,
                    document_title=metadata.get("document_title") or document_title or "unknown",
                    source_type=metadata.get("source_type") or source_type or "unknown",
                    project=project,
                    supplier=supplier,
                    source_path=source_path or "",
                    section_path=section_path,
                    section_titles=_derive_section_titles(
                        section_path=section_path,
                        section_titles_by_path=section_titles_by_path,
                    ),
                    page_start=payload.get("page_start"),
                    page_end=payload.get("page_end"),
                    text=_trim_trailing_appendix_noise(payload.get("text") or ""),
                    evidence_ids=list(payload.get("evidence_ids") or []),
                    quality_status=quality_status,
                    quality_score=quality_score,
                    allowed_for_context_pack=allowed_for_context_pack,
                    quality_gate_reasons=list(quality_gate_reasons),
                    warnings=list(warnings),
                )
            )
        chunks.extend(document_chunks)
        chunks.extend(_build_neighbor_merged_chunks(document_chunks))
    _CHUNK_CACHE[cache_key] = chunks
    return chunks


def _extract_document_quality_gate(document_payload: dict) -> tuple[str, float | None, bool, list[str]]:
    parse_report = document_payload.get("parse_report") or {}
    quality_report = parse_report.get("quality_report") or {}
    quality_status = normalize_space(str(quality_report.get("status") or "unknown"))
    quality_score = _optional_float(quality_report.get("score"))
    gate_reasons: list[str] = []
    if quality_status not in {"ok", "recovered_by_fallback"}:
        gate_reasons.append(f"quality_status_{quality_status or 'unknown'}")
    if quality_score is not None and quality_score < 40.0:
        gate_reasons.append("quality_score_below_40")
    return quality_status, quality_score, not gate_reasons, gate_reasons


def _extract_document_warnings(document_payload: dict) -> list[str]:
    parse_report = document_payload.get("parse_report") or {}
    return [str(warning) for warning in (parse_report.get("warnings") or [])]


def _build_neighbor_merged_chunks(document_chunks: list[_LoadedChunk]) -> list[_LoadedChunk]:
    merged_chunks: list[_LoadedChunk] = []
    if len(document_chunks) > MAX_CHUNKS_FOR_NEIGHBOR_MERGE:
        return merged_chunks

    seen_ids: set[str] = set()
    max_window = min(7, len(document_chunks))

    for window_size in range(2, max_window + 1):
        for start in range(0, len(document_chunks) - window_size + 1):
            window = document_chunks[start : start + window_size]
            total_chars = sum(len(chunk.text) for chunk in window)
            if total_chars > 2800:
                continue
            common_path = _common_section_prefix([chunk.section_path for chunk in window])
            common_titles = _common_section_prefix([chunk.section_titles for chunk in window])
            leaf_titles = [
                chunk.section_titles[-1]
                for chunk in window
                if chunk.section_titles
            ]
            if _window_mixes_noise_and_body_chunks(window):
                continue
            merged_leaf_title = " + ".join(dict.fromkeys(leaf_titles))
            if merged_leaf_title and (
                not common_titles or common_titles[-1] != merged_leaf_title
            ):
                section_titles = [*common_titles, merged_leaf_title]
            else:
                section_titles = common_titles

            merged_text = "\n\n".join(chunk.text for chunk in window if chunk.text.strip()).strip()
            if not merged_text:
                continue

            merged_evidence_ids = list(
                dict.fromkeys(
                    evidence_id
                    for chunk in window
                    for evidence_id in chunk.evidence_ids
                )
            )
            chunk_id = stable_id(
                "chunkmerge",
                window[0].document_version_id,
                window[0].chunk_id,
                window[-1].chunk_id,
            )
            if chunk_id in seen_ids:
                continue
            seen_ids.add(chunk_id)
            merged_chunks.append(
                _LoadedChunk(
                    chunk_id=chunk_id,
                    document_version_id=window[0].document_version_id,
                    document_version=window[0].document_version,
                    document_title=window[0].document_title,
                    source_type=window[0].source_type,
                    project=window[0].project,
                    supplier=window[0].supplier,
                    source_path=window[0].source_path,
                    section_path=common_path,
                    section_titles=section_titles,
                    page_start=_min_optional_int(chunk.page_start for chunk in window),
                    page_end=_max_optional_int(chunk.page_end for chunk in window),
                    text=merged_text,
                    evidence_ids=merged_evidence_ids,
                    quality_status=window[0].quality_status,
                    quality_score=window[0].quality_score,
                    allowed_for_context_pack=window[0].allowed_for_context_pack,
                    quality_gate_reasons=list(window[0].quality_gate_reasons),
                    warnings=list(window[0].warnings),
                )
            )

    return merged_chunks


def _trim_trailing_appendix_noise(text: str) -> str:
    if not text.strip():
        return text

    lines = text.splitlines()
    appendix_index: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if re.fullmatch(r"附录[A-ZＡ-Ｚ]?", stripped, flags=re.IGNORECASE) or re.fullmatch(
            r"appendix\s+[a-z]",
            stripped,
            flags=re.IGNORECASE,
        ):
            appendix_index = index
            break

    if appendix_index is None or appendix_index < 6:
        return text

    before = "\n".join(lines[:appendix_index]).strip()
    after = "\n".join(lines[appendix_index:]).strip()
    if not before or not after:
        return text
    if _normative_body_clause_count(before) == 0:
        return text

    return before


def _common_section_prefix(paths: list[list[str]]) -> list[str]:
    if not paths:
        return []
    prefix = list(paths[0])
    for path in paths[1:]:
        matched = 0
        for left, right in zip(prefix, path):
            if left != right:
                break
            matched += 1
        prefix = prefix[:matched]
        if not prefix:
            break
    return prefix


def _min_optional_int(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _max_optional_int(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


SUPPORTED_METADATA_FILTERS = frozenset({"source_type", "project", "supplier", "document_version"})


def _normalize_metadata_filters(
    metadata_filters: dict[str, list[str]] | None,
) -> dict[str, list[str]]:
    if not metadata_filters:
        return {}

    normalized: dict[str, list[str]] = {}
    for raw_key, raw_values in metadata_filters.items():
        key = normalize_space(str(raw_key))
        if not key:
            continue
        if key not in SUPPORTED_METADATA_FILTERS:
            raise ValueError(f"Unsupported metadata filter: {key}")
        values = [
            normalize_space(str(item))
            for item in (raw_values or [])
            if normalize_space(str(item))
        ]
        if values:
            normalized[key] = list(dict.fromkeys(values))
    return normalized


def _filter_loaded_chunks(
    *,
    chunks: list[_LoadedChunk],
    metadata_filters: dict[str, list[str]],
) -> list[_LoadedChunk]:
    if not metadata_filters:
        return list(chunks)

    normalized_filters = {
        key: {normalize_space(value).lower() for value in values}
        for key, values in metadata_filters.items()
    }
    filtered: list[_LoadedChunk] = []
    for chunk in chunks:
        if _chunk_matches_metadata_filters(chunk=chunk, metadata_filters=normalized_filters):
            filtered.append(chunk)
    return filtered


def _load_fts_bonus_by_chunk_id(
    *,
    fts_index_path: Path | str | None,
    query: str,
    limit: int,
) -> dict[str, float]:
    if fts_index_path is None:
        return {}

    hits = query_fts_index(
        index_path=fts_index_path,
        query=query,
        limit=limit,
    )
    bonuses: dict[str, float] = {}
    for rank, hit in enumerate(hits, start=1):
        bonuses[hit.chunk_id] = max(bonuses.get(hit.chunk_id, 0.0), 72.0 / (rank * rank))
    return bonuses


def _load_vector_bonus_by_chunk_id(
    *,
    vector_index_path: Path | str | None,
    query: str,
    limit: int,
) -> dict[str, float]:
    if vector_index_path is None:
        return {}

    hits = query_vector_index(
        index_path=vector_index_path,
        query=query,
        limit=limit,
    )
    bonuses: dict[str, float] = {}
    for rank, hit in enumerate(hits, start=1):
        rank_bonus = 54.0 / (rank * rank)
        similarity_bonus = hit.similarity_score * 32.0
        bonuses[hit.chunk_id] = max(
            bonuses.get(hit.chunk_id, 0.0),
            rank_bonus + similarity_bonus,
        )
    return bonuses


def _chunk_matches_metadata_filters(
    *,
    chunk: _LoadedChunk,
    metadata_filters: dict[str, set[str]],
) -> bool:
    field_map = {
        "source_type": chunk.source_type,
        "project": chunk.project,
        "supplier": chunk.supplier,
        "document_version": chunk.document_version,
    }
    for key, accepted_values in metadata_filters.items():
        candidate = normalize_space(str(field_map.get(key) or "")).lower()
        if candidate not in accepted_values:
            return False
    return True


def _iter_latest_processed_versions(processed_dir: Path) -> list[tuple[Path, dict]]:
    latest_by_document: dict[str, tuple[tuple[int, str, int, str], Path, dict]] = {}
    for chunks_path in sorted(processed_dir.rglob("chunks.jsonl")):
        document_json_path = chunks_path.with_name("canonical-document.json")
        document_payload = _read_json(document_json_path) if document_json_path.exists() else {}
        document_key = _processed_document_key(chunks_path, document_payload)
        version_key = _processed_version_sort_key(chunks_path, document_payload)
        current = latest_by_document.get(document_key)
        if current is None or version_key > current[0]:
            latest_by_document[document_key] = (version_key, chunks_path, document_payload)

    return sorted(
        ((chunks_path, document_payload) for _, chunks_path, document_payload in latest_by_document.values()),
        key=lambda item: str(item[0]),
    )


def _processed_document_key(chunks_path: Path, document_payload: dict) -> str:
    file_path = normalize_space(
        str((document_payload.get("document_version") or {}).get("file_path") or "")
    )
    if file_path:
        return file_path.lower()

    document_id = normalize_space(
        str((document_payload.get("document") or {}).get("document_id") or "")
    )
    if document_id:
        return document_id

    return str(chunks_path.parent.parent)


def _processed_version_sort_key(chunks_path: Path, document_payload: dict) -> tuple[int, str, int, str]:
    version_payload = document_payload.get("document_version") or {}
    created_at = normalize_space(str(version_payload.get("created_at") or ""))
    document_version_id = normalize_space(
        str(version_payload.get("document_version_id") or chunks_path.parent.name)
    )
    try:
        modified_ns = chunks_path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0
    return (
        1 if created_at else 0,
        created_at,
        modified_ns,
        document_version_id,
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_evidence_payload(document_payload: dict, evidence_id: str) -> dict | None:
    for evidence in document_payload.get("evidence_spans") or []:
        if str(evidence.get("evidence_id") or "") == evidence_id:
            return evidence
    return None


def _normalize_optional_bbox(value: object) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    normalized: list[float] = []
    for item in value:
        try:
            normalized.append(float(item))
        except (TypeError, ValueError):
            return None
    return normalized


def _load_evidence_chunk_references(
    *,
    chunks_path: Path,
    evidence_id: str,
    section_titles_by_path: dict[tuple[str, ...], str],
) -> list[EvidenceChunkReference]:
    references: list[EvidenceChunkReference] = []
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if evidence_id not in {str(item) for item in (payload.get("evidence_ids") or [])}:
            continue
        section_path = [str(part) for part in (payload.get("section_path") or [])]
        references.append(
            EvidenceChunkReference(
                chunk_id=str(payload.get("chunk_id") or ""),
                section_path=section_path,
                section_titles=_derive_section_titles(
                    section_path=section_path,
                    section_titles_by_path=section_titles_by_path,
                ),
                page_start=payload.get("page_start"),
                page_end=payload.get("page_end"),
            )
        )

    references.sort(
        key=lambda item: (
            item.page_start is None,
            item.page_start if item.page_start is not None else 0,
            ".".join(item.section_path),
            item.chunk_id,
        )
    )
    return references


def _build_candidate_scores(
    *,
    chunks: Iterable[_LoadedChunk],
    query_tokens: Counter[str],
    clause_tokens: list[Counter[str]],
    desired_topics: list[str],
    query_text: str,
    fts_bonus_by_chunk_id: dict[str, float] | None = None,
    vector_bonus_by_chunk_id: dict[str, float] | None = None,
    bm25_context: _Bm25Context | None = None,
) -> list[_CandidateScore]:
    chunk_list = list(chunks)
    if bm25_context is None:
        bm25_context = _build_bm25_context(chunk_list)
    resolved_fts_bonus = fts_bonus_by_chunk_id or {}
    resolved_vector_bonus = vector_bonus_by_chunk_id or {}
    candidates: list[_CandidateScore] = []
    for chunk in chunk_list:
        # Restore query-independent per-chunk scores from cache when available.
        static_key = chunk.chunk_id
        if static_key in _CHUNK_STATIC_SCORE_CACHE:
            (
                topic_scores,
                topic_subfacets,
                coherence_bonus,
                structure_bonus,
                evidence_quality_adjustment,
                thin_chunk_penalty,
            ) = _CHUNK_STATIC_SCORE_CACHE[static_key]
        else:
            topic_scores = _compute_topic_scores(
                document_title=chunk.document_title,
                section_titles=chunk.section_titles,
                chunk_text=chunk.text,
            )
            topic_subfacets = _compute_topic_subfacets(
                document_title=chunk.document_title,
                section_titles=chunk.section_titles,
                chunk_text=chunk.text,
            )
            coherence_bonus = _coherence_bonus(chunk.text)
            structure_bonus = _structure_bonus(chunk.text)
            evidence_quality_adjustment = _evidence_quality_adjustment(
                chunk_text=chunk.text,
                section_titles=chunk.section_titles,
            )
            thin_chunk_penalty = _thin_chunk_penalty(
                chunk_text=chunk.text,
                document_title=chunk.document_title,
                section_titles=chunk.section_titles,
            )
            _CHUNK_STATIC_SCORE_CACHE[static_key] = (
                topic_scores,
                topic_subfacets,
                coherence_bonus,
                structure_bonus,
                evidence_quality_adjustment,
                thin_chunk_penalty,
            )
        # Use cached token data to avoid re-tokenising the same chunk text on
        # every request (tokenisation is query-independent).
        _chunk_tokens, _title_text, _section_text, _leaf_section_text = _get_chunk_token_data(chunk)
        overall_score = _score_tokens_from_cached(
            chunk_tokens=_chunk_tokens,
            title_text=_title_text,
            section_text=_section_text,
            leaf_section_text=_leaf_section_text,
            query_tokens=query_tokens,
        )
        bm25_score = _score_bm25(
            chunk=chunk,
            query_tokens=query_tokens,
            bm25_context=bm25_context,
        )
        fts_bonus = resolved_fts_bonus.get(chunk.chunk_id, 0.0)
        vector_bonus = resolved_vector_bonus.get(chunk.chunk_id, 0.0)
        retrieval_signals = _derive_retrieval_signals(
            lexical_score=overall_score,
            bm25_score=bm25_score,
            fts_bonus=fts_bonus,
            vector_bonus=vector_bonus,
            topic_scores=topic_scores,
        )
        per_clause_scores = tuple(
            _score_tokens_from_cached(
                chunk_tokens=_chunk_tokens,
                title_text=_title_text,
                section_text=_section_text,
                leaf_section_text=_leaf_section_text,
                query_tokens=one_clause_tokens,
            )
            + _score_bm25(
                chunk=chunk,
                query_tokens=one_clause_tokens,
                bm25_context=bm25_context,
            )
            for one_clause_tokens in clause_tokens
        )
        clause_hits = frozenset(
            index
            for index, score in enumerate(per_clause_scores)
            if score >= 2.0 or (score > 0 and len(clause_tokens[index]) <= 3)
        )
        appendix_method_query_bonus = _appendix_method_query_bonus(
            query_text=query_text,
            chunk_text=chunk.text,
            section_titles=chunk.section_titles,
        )
        topic_bonus = _topic_alignment_bonus(topic_scores, desired_topics)
        candidates.append(
            _CandidateScore(
                chunk=chunk,
                overall_score=(
                    overall_score
                    + bm25_score
                    + fts_bonus
                    + vector_bonus
                    + coherence_bonus
                    + structure_bonus
                    + evidence_quality_adjustment
                    + appendix_method_query_bonus
                    + _quality_gate_adjustment(chunk)
                    + topic_bonus
                    + thin_chunk_penalty
                ),
                clause_scores=per_clause_scores,
                clause_hits=clause_hits,
                coherence_bonus=coherence_bonus,
                topic_scores=topic_scores,
                topic_subfacets=topic_subfacets,
                retrieval_signals=frozenset(retrieval_signals),
            )
        )
    candidates.sort(
        key=lambda item: (
            -item.overall_score,
            -len(item.clause_hits),
            item.chunk.document_title,
            ".".join(item.chunk.section_path),
            item.chunk.chunk_id,
        )
    )
    return candidates


def _derive_retrieval_signals(
    *,
    lexical_score: float,
    bm25_score: float,
    fts_bonus: float,
    vector_bonus: float,
    topic_scores: dict[str, float],
) -> list[str]:
    signals: list[str] = []
    if lexical_score > 0.0:
        signals.append("lexical")
    if bm25_score > 0.0:
        signals.append("bm25")
    if fts_bonus > 0.0:
        signals.append("fts")
    if vector_bonus > 0.0:
        signals.append("vector")
    if any(score > 0.0 for score in topic_scores.values()):
        signals.append("topic")
    return signals or ["fallback"]


@dataclass(frozen=True)
class _Bm25Context:
    average_document_length: float
    document_frequencies: dict[str, int]
    token_counts_by_chunk_id: dict[str, Counter[str]]
    total_documents: int


def _build_bm25_context(chunks: list[_LoadedChunk]) -> _Bm25Context:
    token_counts_by_chunk_id: dict[str, Counter[str]] = {}
    document_frequencies: Counter[str] = Counter()
    total_length = 0

    for chunk in chunks:
        token_counts = _tokenize_bm25_document(chunk)
        token_counts_by_chunk_id[chunk.chunk_id] = token_counts
        total_length += sum(token_counts.values())
        for token in token_counts:
            document_frequencies[token] += 1

    total_documents = len(chunks)
    average_document_length = total_length / total_documents if total_documents else 0.0
    return _Bm25Context(
        average_document_length=average_document_length,
        document_frequencies=dict(document_frequencies),
        token_counts_by_chunk_id=token_counts_by_chunk_id,
        total_documents=total_documents,
    )


def _tokenize_bm25_document(chunk: _LoadedChunk) -> Counter[str]:
    title_text = normalize_space(chunk.document_title).lower()
    section_text = normalize_space("\n".join(chunk.section_titles)).lower()
    chunk_text = normalize_space(chunk.text).lower()
    return _tokenize_for_search(f"{title_text}\n{section_text}\n{chunk_text}")


def _score_bm25(
    *,
    chunk: _LoadedChunk,
    query_tokens: Counter[str],
    bm25_context: _Bm25Context,
) -> float:
    if not query_tokens or bm25_context.total_documents == 0:
        return 0.0

    token_counts = bm25_context.token_counts_by_chunk_id.get(chunk.chunk_id)
    if not token_counts:
        return 0.0

    document_length = sum(token_counts.values())
    if document_length <= 0:
        return 0.0

    average_length = bm25_context.average_document_length or float(document_length)
    k1 = 1.2
    b = 0.75
    score = 0.0
    for term, query_count in query_tokens.items():
        term_frequency = token_counts.get(term, 0)
        if term_frequency <= 0:
            continue
        document_frequency = bm25_context.document_frequencies.get(term, 0)
        idf = math.log(1.0 + (bm25_context.total_documents - document_frequency + 0.5) / (document_frequency + 0.5))
        numerator = term_frequency * (k1 + 1.0)
        denominator = term_frequency + k1 * (1.0 - b + b * (document_length / average_length))
        score += idf * (numerator / denominator) * query_count * _term_weight(term)
    return score


def _select_candidates(
    *,
    candidates: list[_CandidateScore],
    clauses: list[str],
    top_k: int,
    per_document_limit: int,
    desired_topics: list[str],
    requested_subfacets: dict[str, set[str]],
    query_text: str,
) -> list[_CandidateScore]:
    if not candidates:
        return []

    selected: list[_CandidateScore] = []
    per_document_counts: defaultdict[str, int] = defaultdict(int)
    covered_clauses: set[int] = set()
    covered_topics: set[str] = set()
    covered_subfacets: defaultdict[str, set[str]] = defaultdict(set)
    remaining = list(candidates)

    for topic in desired_topics:
        if len(selected) >= top_k:
            break
        topic_candidate = _pick_topic_candidate(
            remaining=remaining,
            selected=selected,
            per_document_counts=per_document_counts,
            per_document_limit=per_document_limit,
            topic=topic,
            covered_subfacets=covered_subfacets,
            requested_subfacets=requested_subfacets,
            query_text=query_text,
        )
        if topic_candidate is None:
            continue
        selected.append(topic_candidate)
        per_document_counts[topic_candidate.chunk.document_version_id] += 1
        covered_clauses.update(topic_candidate.clause_hits)
        covered_topics.update(
            one_topic for one_topic, score in topic_candidate.topic_scores.items() if score > 0
        )
        for one_topic, subfacets in topic_candidate.topic_subfacets.items():
            covered_subfacets[one_topic].update(subfacets)
        remaining = [candidate for candidate in remaining if candidate != topic_candidate]

    while remaining and len(selected) < top_k:
        best_index: int | None = None
        best_value: float | None = None
        selected_documents = {item.chunk.document_version_id for item in selected}
        missing_requested_subfacets = _missing_requested_subfacets(
            requested_subfacets=requested_subfacets,
            covered_subfacets=covered_subfacets,
        )
        must_fill_requested_subfacets = bool(missing_requested_subfacets) and any(
            _candidate_covers_missing_requested_subfacet(candidate, missing_requested_subfacets)
            for candidate in remaining
        )
        for index, candidate in enumerate(remaining):
            document_key = candidate.chunk.document_version_id
            candidate_needs_soft_limit_exception = _candidate_needs_soft_document_limit_exception(
                candidate=candidate,
                remaining=remaining,
                missing_requested_subfacets=missing_requested_subfacets,
                per_document_counts=per_document_counts,
                per_document_limit=per_document_limit,
            )
            if (
                per_document_counts[document_key] >= per_document_limit
                and not candidate_needs_soft_limit_exception
            ):
                continue
            candidate_covers_missing_requested_subfacet = (
                _candidate_covers_missing_requested_subfacet(
                    candidate,
                    missing_requested_subfacets,
                )
            )
            if _is_overlapping_duplicate(candidate, selected) and not candidate_covers_missing_requested_subfacet:
                continue
            if must_fill_requested_subfacets and not _candidate_covers_missing_requested_subfacet(
                candidate,
                missing_requested_subfacets,
            ):
                continue

            new_clause_hits = candidate.clause_hits - covered_clauses
            new_topics = {
                topic for topic in desired_topics if candidate.topic_scores.get(topic, 0.0) > 0
            } - covered_topics
            utility = candidate.overall_score
            utility += 18.0 * len(new_clause_hits)
            utility += 12.0 * len(new_topics)
            utility += _topic_subfacet_novelty_bonus(
                candidate=candidate,
                desired_topics=desired_topics,
                covered_subfacets=covered_subfacets,
                requested_subfacets=requested_subfacets,
            )
            utility += max(
                (
                    _topic_section_hint_bonus(topic, candidate.chunk.section_titles)
                    for topic in desired_topics
                ),
                default=0.0,
            )
            utility += max(
                (
                    _query_intent_bonus(
                        topic=topic,
                        query_text=query_text,
                        document_title=candidate.chunk.document_title,
                        section_titles=candidate.chunk.section_titles,
                        chunk_text=candidate.chunk.text,
                    )
                    for topic in desired_topics
                ),
                default=0.0,
            )
            utility += min(
                (
                    _topic_query_conflict_penalty(
                        topic=topic,
                        query_text=query_text,
                        document_title=candidate.chunk.document_title,
                        section_titles=candidate.chunk.section_titles,
                        chunk_text=candidate.chunk.text,
                    )
                    for topic in desired_topics
                ),
                default=0.0,
            )
            if document_key not in selected_documents:
                utility += 6.0
            utility -= 5.0 * per_document_counts[document_key]
            utility += 1.5 * len(candidate.clause_hits)

            if best_value is None or utility > best_value:
                best_value = utility
                best_index = index

        if best_index is None:
            break

        chosen = remaining.pop(best_index)
        selected.append(chosen)
        per_document_counts[chosen.chunk.document_version_id] += 1
        covered_clauses.update(chosen.clause_hits)
        covered_topics.update(
            topic for topic in desired_topics if chosen.topic_scores.get(topic, 0.0) > 0
        )
        for one_topic, subfacets in chosen.topic_subfacets.items():
            covered_subfacets[one_topic].update(subfacets)

        if len(covered_clauses) == len(clauses):
            # 继续补充但更强烈要求文档多样性和非重复。
            remaining.sort(
                key=lambda item: (
                    item.chunk.document_version_id in {c.chunk.document_version_id for c in selected},
                    -item.overall_score,
                    -len(item.clause_hits),
                )
            )

    if not selected:
        return candidates[: min(top_k, len(candidates))]
    return selected


def _is_overlapping_duplicate(
    candidate: _CandidateScore,
    selected: list[_CandidateScore],
) -> bool:
    candidate_chunk = candidate.chunk
    candidate_text = _canonical_chunk_text(candidate_chunk.text)
    candidate_tokens = set(_tokenize_for_search(candidate_text))

    for existing in selected:
        if existing.chunk.document_version_id != candidate_chunk.document_version_id:
            continue
        existing_text = _canonical_chunk_text(existing.chunk.text)
        if candidate_text == existing_text:
            return True

        if candidate_chunk.section_path == existing.chunk.section_path:
            overlap = _token_overlap_ratio(candidate_tokens, set(_tokenize_for_search(existing_text)))
            if overlap >= 0.8:
                return True

        min_len = min(len(candidate_text), len(existing_text))
        if min_len >= 40 and (
            candidate_text in existing_text or existing_text in candidate_text
        ):
            return True

        evidence_overlap = _sequence_overlap_ratio(
            candidate_chunk.evidence_ids,
            existing.chunk.evidence_ids,
        )
        if evidence_overlap >= 0.7:
            return True

    return False


def _canonical_chunk_text(text: str) -> str:
    return normalize_space(text).lower()


def _sequence_overlap_ratio(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    shared = len(set(left) & set(right))
    return shared / max(1, min(len(left), len(right)))


def _token_overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    return intersection / max(1, min(len(left), len(right)))


def _get_chunk_token_data(chunk: _LoadedChunk) -> tuple[Counter[str], str, str, str]:
    """Return pre-tokenised chunk data, using a module-level cache keyed by chunk_id."""
    cache_key = chunk.chunk_id
    if cache_key in _CHUNK_TOKEN_CACHE:
        return _CHUNK_TOKEN_CACHE[cache_key]  # type: ignore[return-value]
    chunk_text_normalized = normalize_space(chunk.text).lower()
    title_text = normalize_space(chunk.document_title).lower()
    section_text = normalize_space("\n".join(chunk.section_titles)).lower()
    leaf_section_text = normalize_space(chunk.section_titles[-1]).lower() if chunk.section_titles else ""
    chunk_tokens = _tokenize_for_search(f"{title_text}\n{section_text}\n{chunk_text_normalized}")
    result = (chunk_tokens, title_text, section_text, leaf_section_text)
    _CHUNK_TOKEN_CACHE[cache_key] = result
    return result


def _score_tokens_from_cached(
    *,
    chunk_tokens: Counter[str],
    title_text: str,
    section_text: str,
    leaf_section_text: str,
    query_tokens: Counter[str],
) -> float:
    """Score query tokens against pre-tokenised chunk data (no repeat tokenization)."""
    if not query_tokens:
        return 0.0
    score = 0.0
    for term, query_count in query_tokens.items():
        chunk_count = chunk_tokens.get(term, 0)
        if not chunk_count:
            continue
        weight = _term_weight(term)
        score += weight * min(chunk_count, 3) * query_count
        if term in title_text:
            score += weight * 1.5
        if leaf_section_text and term in leaf_section_text:
            score += weight * 2.5
        if section_text and term in section_text:
            score += weight * 1.5
    return score


def _score_tokens(
    *,
    chunk_text: str,
    document_title: str,
    section_titles: list[str],
    query_tokens: Counter[str],
) -> float:
    if not query_tokens:
        return 0.0

    chunk_text_normalized = normalize_space(chunk_text).lower()
    title_text = normalize_space(document_title).lower()
    section_text = normalize_space("\n".join(section_titles)).lower()
    leaf_section_text = normalize_space(section_titles[-1]).lower() if section_titles else ""
    chunk_tokens = _tokenize_for_search(f"{title_text}\n{section_text}\n{chunk_text_normalized}")
    score = 0.0

    for term, query_count in query_tokens.items():
        chunk_count = chunk_tokens.get(term, 0)
        if not chunk_count:
            continue
        weight = _term_weight(term)
        score += weight * min(chunk_count, 3) * query_count
        if term in title_text:
            score += weight * 1.5
        if leaf_section_text and term in leaf_section_text:
            score += weight * 2.5
        if section_text and term in section_text:
            score += weight * 1.5

    return score


def _term_weight(term: str) -> float:
    if re.fullmatch(r"[a-z0-9_./=-]+", term):
        if len(term) >= 12:
            return 4.2
        if len(term) >= 6:
            return 2.6
        return 1.6

    if len(term) >= 4:
        return 2.3
    if len(term) == 3:
        return 1.7
    return 1.0


def _coherence_bonus(text: str) -> float:
    normalized = normalize_space(text)
    if not normalized:
        return -3.0

    bonus = 0.0
    first_char = normalized[0]
    if first_char in "#0123456789" or "\u4e00" <= first_char <= "\u9fff":
        bonus += 1.2
    if re.match(r"^[a-z]", normalized):
        bonus -= 2.0
    if normalized.startswith(("`", "_", "-", ".", ",")):
        bonus -= 1.5
    if normalized[:12].count(" ") > 4:
        bonus -= 0.5
    return bonus


def _structure_bonus(text: str) -> float:
    normalized = normalize_space(text).lower()
    if not normalized:
        return 0.0

    bonus = 0.0
    if "get /" in normalized or "post /" in normalized:
        bonus += 1.6
    if "runtime_" in normalized:
        bonus += 1.2
    if any(keyword in normalized for keyword in ("默认策略", "默认创建", "第一版必须坚持", "禁止")):
        bonus += 1.0
    if any(keyword in normalized for keyword in ("验收", "回滚", "灰度", "feature flag")):
        bonus += 0.8
    if any(keyword in normalized for keyword in ("应", "不应", "必须", "不得", "shall", "must")):
        bonus += 1.4
    if re.search(r"(?:^|\n)\s*\d+(?:\.\d+){1,4}\s*[\u4e00-\u9fffA-Za-z]", text):
        bonus += 1.6
    bullet_count = sum(1 for line in text.splitlines() if line.lstrip().startswith(("-", "*")))
    if bullet_count >= 3:
        bonus += 0.8
    return bonus


def _evidence_quality_adjustment(*, chunk_text: str, section_titles: list[str]) -> float:
    normalized_text = normalize_space(chunk_text)
    if not normalized_text:
        return -8.0

    adjustment = 0.0
    is_appendix_method = _looks_like_appendix_method_chunk(normalized_text, section_titles)
    is_appendix = _looks_like_appendix_chunk(normalized_text, section_titles)
    if _looks_like_toc_or_index_chunk(normalized_text):
        adjustment -= 34.0
    if is_appendix_method:
        adjustment -= 42.0
    elif is_appendix:
        adjustment -= 16.0
    if _looks_like_page_marker_only_chunk(normalized_text, section_titles):
        adjustment -= 12.0

    body_clause_count = (
        0 if is_appendix_method or is_appendix else _normative_body_clause_count(normalized_text)
    )
    if body_clause_count:
        adjustment += min(28.0, 5.5 * body_clause_count)
    if not is_appendix_method and not is_appendix and _contains_direct_answer_sentence(normalized_text):
        adjustment += 8.0
    return adjustment


def _appendix_method_query_bonus(
    *,
    query_text: str,
    chunk_text: str,
    section_titles: list[str],
) -> float:
    normalized_query = normalize_space(query_text).lower()
    if not normalized_query:
        return 0.0
    if not _looks_like_appendix_method_chunk(chunk_text, section_titles):
        return 0.0
    if _looks_like_toc_or_index_chunk(chunk_text) or not _looks_like_appendix_method_body_chunk(
        chunk_text,
        section_titles,
    ):
        return 0.0

    combined_chunk = normalize_space("\n".join([*section_titles, chunk_text])).lower()
    asks_method = _query_asks_appendix_method(normalized_query)
    if not asks_method:
        return 0.0

    score = 32.0
    for term, weight in (
        ("d.8", 22.0),
        ("d8", 10.0),
        ("出境试验", 16.0),
        ("出境试验方法", 18.0),
        ("出境", 12.0),
        ("境外", 8.0),
        ("抓包", 14.0),
        ("境外ip", 14.0),
        ("境外 ip", 14.0),
        ("3600s", 12.0),
        ("移动蜂窝", 8.0),
        ("wlan", 8.0),
    ):
        if term in normalized_query and term in combined_chunk:
            score += weight

    if "d.8" in normalized_query and re.search(r"(?:^|\n)\s*d\.8", combined_chunk):
        score += 16.0
    if "附录" in normalized_query and "附录" in combined_chunk:
        score += 6.0
    if _query_asks_outbound_method(normalized_query) and _looks_like_outbound_appendix_method_body(
        combined_chunk
    ):
        score += 34.0
    return min(score, 80.0)


def _query_asks_appendix_method(normalized_query: str) -> bool:
    return any(term in normalized_query for term in APPENDIX_METHOD_QUERY_TERMS) or any(
        term in normalized_query
        for term in (
            "d.8",
            "d8",
            "附录 d",
            "附录d",
        )
    )


def _query_asks_outbound_method(normalized_query: str) -> bool:
    return _query_asks_appendix_method(normalized_query) and any(
        term in normalized_query for term in OUTBOUND_QUERY_TERMS
    )


def _quality_gate_adjustment(chunk: _LoadedChunk) -> float:
    status = chunk.quality_status
    if status in {"unsupported", "ocr_unavailable"}:
        return -80.0
    if not chunk.allowed_for_context_pack:
        return -56.0
    if status == "ok":
        return 0.0
    if status == "recovered_by_fallback":
        return -4.0
    if status == "low_quality":
        return -42.0
    return -24.0


def _window_mixes_noise_and_body_chunks(window: list[_LoadedChunk]) -> bool:
    has_noise = any(
        _looks_like_toc_or_index_chunk(chunk.text)
        or _looks_like_appendix_method_chunk(chunk.text, chunk.section_titles)
        or _looks_like_appendix_chunk(chunk.text, chunk.section_titles)
        or _looks_like_page_marker_only_chunk(chunk.text, chunk.section_titles)
        for chunk in window
    )
    has_body = any(_normative_body_clause_count(chunk.text) > 0 for chunk in window)
    return has_noise and has_body


def _looks_like_toc_or_index_chunk(text: str) -> bool:
    normalized = normalize_space(text)
    if not normalized:
        return False
    if _looks_like_compact_pdf_toc_chunk(normalized):
        return True
    lines = [
        line.strip()
        for line in normalized.splitlines()
        if line.strip() and not re.fullmatch(r"page\s+\d+", line.strip().lower())
    ]
    if not lines:
        return False
    has_toc_marker = any(line in {"目录", "目次", "contents"} for line in lines[:6])
    heading_like_lines = sum(
        1
        for line in lines
        if (
            re.match(r"^(?:\d+(?:\.\d+){0,4}|[A-Z]\.\d+(?:\.\d+)*)\s*[\u4e00-\u9fffA-Za-z]", line)
            or line.startswith(("附录", "Appendix", "appendix"))
            or line in {"前言", "范围", "规范性引用文件", "术语和定义"}
        )
    )
    short_heading_ratio = sum(
        1
        for line in lines
        if len(line) <= 32 and not line.endswith(("。", ".", "；", ";"))
    ) / len(lines)
    has_normative_sentence = _contains_direct_answer_sentence(normalized)
    return (
        has_toc_marker
        and heading_like_lines >= 5
        and short_heading_ratio >= 0.6
        and not has_normative_sentence
    )


def _looks_like_compact_pdf_toc_chunk(normalized_text: str) -> bool:
    lowered = normalized_text.lower()
    has_toc_marker = (
        "contents" in lowered[:120]
        or " contents " in f" {lowered} "
        or lowered.rstrip().endswith("contents")
        or "目录" in normalized_text[:80]
        or " 目录 " in f" {normalized_text} "
        or "目次" in normalized_text[:80]
        or " 目次 " in f" {normalized_text} "
    )

    dot_leader_hits = len(re.findall(r"\.{4,}\s*\d+\b", normalized_text))
    chapter_hits = len(re.findall(r"\bchapter\s+\d+\s*[:：]", normalized_text, re.IGNORECASE))
    numbered_heading_hits = len(
        re.findall(
            r"(?:^|\s)(?:\d+(?:\.\d+){0,4}|[A-Z]\.\d+(?:\.\d+)*)\s*"
            r"[\u4e00-\u9fffA-Za-z][^.\n]{0,80}\.{4,}\s*\d+\b",
            normalized_text,
        )
    )
    section_like_hits = chapter_hits + numbered_heading_hits

    return (
        dot_leader_hits >= 6
        and (section_like_hits >= 2 or has_toc_marker)
        and (has_toc_marker or dot_leader_hits >= 10)
        and not _contains_direct_answer_sentence(normalized_text)
    )


def _looks_like_appendix_method_chunk(text: str, section_titles: list[str]) -> bool:
    combined = normalize_space("\n".join([*section_titles, text])).lower()
    if not combined:
        return False
    appendix_terms = ("附录", "appendix")
    method_terms = ("试验方法", "测试方法", "评估方法", "计算方法", "test method")
    has_appendix_method = any(term in combined for term in appendix_terms) and any(
        term in combined for term in method_terms
    )
    if has_appendix_method:
        return True

    has_method_title = any(term in combined for term in method_terms)
    if not has_method_title:
        return False

    return (
        bool(re.search(r"(?:^|\n)\s*[a-z]\.\d+(?:\.\d+)*\s*", combined))
        or "试验输入信息" in combined
        or "判定试验结果是否符合" in combined
    )


def _looks_like_appendix_method_body_chunk(text: str, section_titles: list[str]) -> bool:
    combined = normalize_space("\n".join([*section_titles, text])).lower()
    if not combined or _looks_like_toc_or_index_chunk(text):
        return False

    return any(signal in combined for signal in APPENDIX_METHOD_BODY_SIGNALS)


def _looks_like_outbound_appendix_method_body(combined_text: str) -> bool:
    return (
        any(term in combined_text for term in OUTBOUND_QUERY_TERMS)
        and any(
            term in combined_text
            for term in (
                "抓包",
                "3600s",
                "目的ip",
                "目的 ip",
                "境外ip",
                "境外 ip",
                "5.8",
                "6.7",
                "wlan",
                "移动蜂窝",
                "通信通道",
            )
        )
    )


def _looks_like_appendix_chunk(text: str, section_titles: list[str]) -> bool:
    combined = normalize_space("\n".join([*section_titles, text]))
    if not combined:
        return False
    has_appendix_heading = bool(
        re.search(r"(?:^|\n)\s*附录[A-ZＡ-Ｚ]?\s*$", combined, flags=re.IGNORECASE)
        or re.search(r"(?:^|\n)\s*appendix\s+[a-z]\s*$", combined, flags=re.IGNORECASE)
    )
    if has_appendix_heading:
        return True

    has_appendix_numbering = bool(
        re.search(r"(?:^|\n)\s*[A-Z]\.\d+(?:\.\d+)*\s*", combined)
        or re.search(r"(?:^|\n)\s*表[A-Z]\.\d+", combined)
    )
    has_appendix_context = any(
        term in combined
        for term in (
            "表A.",
            "图A.",
            "分类分级示例",
            "试验方法",
            "示例见表",
            "附录",
        )
    )
    return has_appendix_numbering and has_appendix_context


def _looks_like_page_marker_only_chunk(text: str, section_titles: list[str]) -> bool:
    normalized = normalize_space(text)
    if not normalized:
        return True
    leaf_title = normalize_space(section_titles[-1]) if section_titles else ""
    return bool(re.fullmatch(r"page\s+\d+", normalized.lower())) or normalized == leaf_title


def _normative_body_clause_count(text: str) -> int:
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        has_normative_language = any(
            term in stripped
            for term in (
                "应",
                "不应",
                "不得",
                "必须",
                "shall",
                "must",
                "requires",
                "required",
            )
        )
        if has_normative_language:
            count += 1
    return count


def _contains_direct_answer_sentence(text: str) -> bool:
    return any(
        term in text
        for term in (
            "应采取",
            "不应直接",
            "应对",
            "应不可",
            "必须",
            "不得",
            "shall",
            "must",
        )
    )


def _normalize_query_text(query: str) -> str:
    normalized_lines: list[str] = []
    in_requirements = False

    for raw_line in query.splitlines():
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue
        if stripped_line.startswith("#"):
            heading = MARKDOWN_HEADING_RE.sub("", stripped_line).strip().lower()
            if heading == "question":
                continue
            stripped_line = MARKDOWN_HEADING_RE.sub("", stripped_line).strip()
            if not stripped_line:
                continue

        if stripped_line in {"要求", "要求："}:
            in_requirements = True
            continue

        cleaned_line = INLINE_MARKDOWN_RE.sub(" ", stripped_line)
        cleaned_line = normalize_space(cleaned_line)
        if not cleaned_line:
            continue

        if cleaned_line.lower().startswith("question"):
            continue
        if any(cleaned_line.startswith(prefix) for prefix in QUERY_NOISE_PREFIXES):
            continue

        is_bullet = stripped_line.startswith(("-", "*"))
        if in_requirements and is_bullet:
            continue
        if in_requirements and "建议项" in cleaned_line and "硬要求" in cleaned_line:
            continue

        cleaned_line = NUMBERED_ITEM_RE.sub("", cleaned_line)
        cleaned_line = LIST_ITEM_RE.sub("", cleaned_line)
        if cleaned_line:
            normalized_lines.append(cleaned_line)

    return "\n".join(normalized_lines) if normalized_lines else query.strip()


def _split_query_clauses(query: str) -> list[str]:
    parts = [part.strip() for part in CLAUSE_SPLIT_RE.split(query) if part.strip()]
    clauses = [part for part in parts if len(normalize_space(part)) >= 4]
    return clauses or [query.strip()]


def _tokenize_for_search(text: str) -> Counter[str]:
    normalized = normalize_space(text).lower()
    tokens: Counter[str] = Counter()

    for token in ASCII_TOKEN_RE.findall(normalized):
        if len(token) >= 2:
            tokens[token] += 1

    for sequence in CJK_SEQUENCE_RE.findall(normalized):
        if len(sequence) < 2:
            continue
        max_ngram = min(4, len(sequence))
        for size in range(2, max_ngram + 1):
            for index in range(0, len(sequence) - size + 1):
                token = sequence[index : index + size]
                if token in CJK_STOPGRAMS:
                    continue
                tokens[token] += 1

        if len(sequence) <= 8 and sequence not in CJK_STOPGRAMS:
            tokens[sequence] += 1

    return tokens


def _derive_query_topics(query: str, clauses: list[str]) -> list[str]:
    if _looks_like_symbol_lookup_query(query):
        return []

    topic_hits: dict[str, float] = defaultdict(float)
    combined_texts = [query, *clauses]
    for text in combined_texts:
        scores = _compute_topic_scores(document_title="", section_titles=[], chunk_text=text)
        for topic, score in scores.items():
            topic_hits[topic] += score

    prioritized_topics = [
        topic
        for topic in TOPIC_PRIORITY
        if topic_hits.get(topic, 0.0) > 0
    ]
    return prioritized_topics


def _looks_like_symbol_lookup_query(query: str) -> bool:
    normalized = normalize_space(query).lower()
    if not normalized:
        return False
    ascii_tokens = ASCII_TOKEN_RE.findall(normalized)
    cjk_sequences = CJK_SEQUENCE_RE.findall(normalized)
    if not ascii_tokens:
        return False
    if cjk_sequences:
        return False
    if len(ascii_tokens) > 3:
        return False
    return any(
        "_" in token
        or "/" in token
        or "." in token
        or len(token) >= 8
        for token in ascii_tokens
    )


def _derive_requested_topic_subfacets(
    *,
    query: str,
    clauses: list[str],
    desired_topics: list[str],
) -> dict[str, set[str]]:
    combined_text = normalize_space("\n".join([query, *clauses])).lower()
    requested: dict[str, set[str]] = {}

    for topic in desired_topics:
        subfacet_hints = TOPIC_SUBFACET_HINTS.get(topic)
        if not subfacet_hints:
            continue

        matched: set[str] = set()
        for subfacet, hint_groups in subfacet_hints.items():
            query_hints = hint_groups.get("query", ())
            if any(hint.lower() in combined_text for hint in query_hints):
                matched.add(subfacet)

        if topic == "api":
            has_broad_api_scope = (
                "最小可交付范围" in combined_text
                or "一起说明" in combined_text
                or (
                    "api/事件能力" in combined_text
                    and any(
                        hint in combined_text
                        for hint in (
                            "后端能力",
                            "测试与回滚",
                            "治理规则",
                            "默认治理",
                        )
                    )
                )
                or (
                    "api 事件能力" in combined_text
                    and any(
                        hint in combined_text
                        for hint in (
                            "后端能力",
                            "测试与回滚",
                            "治理规则",
                            "默认治理",
                        )
                    )
                )
            )
            if has_broad_api_scope:
                matched.add("agent_create_fields")
                matched.add("runtime_profile_routes_basic")
                matched.add("runtime_profile_routes_detail")
                matched.add("runtime_run_routes")
                matched.add("event_types")
                matched.add("approval_protocol")
        elif topic == "governance":
            has_governance_scope = (
                "治理规则" in combined_text
                or "治理层级" in combined_text
                or ("治理" in combined_text and "规则" in combined_text)
            )
            if has_governance_scope:
                matched.add("governance_layers")

        if matched:
            requested[topic] = matched

    return requested


def _compute_topic_subfacets(
    *,
    document_title: str,
    section_titles: list[str],
    chunk_text: str,
) -> dict[str, frozenset[str]]:
    title_normalized = normalize_space(document_title).lower()
    section_text = normalize_space("\n".join(section_titles)).lower()
    leaf_section_text = normalize_space(section_titles[-1]).lower() if section_titles else ""
    body_normalized = normalize_space(chunk_text).lower()
    topic_subfacets: dict[str, frozenset[str]] = {}

    for topic, subfacet_hints in TOPIC_SUBFACET_HINTS.items():
        matched: set[str] = set()
        for subfacet, hint_groups in subfacet_hints.items():
            chunk_hints = hint_groups.get("chunk", ())
            for hint in chunk_hints:
                lowered_hint = hint.lower()
                if leaf_section_text and lowered_hint in leaf_section_text:
                    matched.add(subfacet)
                    break
                if section_text and lowered_hint in section_text:
                    matched.add(subfacet)
                    break
                if lowered_hint in title_normalized:
                    matched.add(subfacet)
                    break
                if lowered_hint in body_normalized:
                    matched.add(subfacet)
                    break
        if matched:
            topic_subfacets[topic] = frozenset(matched)

    return topic_subfacets


def _topic_subfacet_bonus_for_topic(
    *,
    topic: str,
    candidate: _CandidateScore,
    covered_subfacets: defaultdict[str, set[str]],
    requested_subfacets: dict[str, set[str]],
) -> float:
    candidate_subfacets = candidate.topic_subfacets.get(topic, frozenset())
    if not candidate_subfacets:
        return 0.0

    covered = covered_subfacets[topic]
    requested = requested_subfacets.get(topic, set())
    requested_hits = candidate_subfacets & requested if requested else set(candidate_subfacets)
    uncovered_requested = requested_hits - covered
    uncovered_any = set(candidate_subfacets) - covered
    subfacet_weights = TOPIC_SUBFACET_WEIGHTS.get(topic, {})

    bonus = 0.0
    bonus += 18.0 * len(uncovered_requested)
    bonus += sum(subfacet_weights.get(subfacet, 0.0) for subfacet in uncovered_requested)
    if not requested:
        residual_subfacets = uncovered_any - uncovered_requested
        bonus += 6.0 * len(residual_subfacets)
        bonus += sum(subfacet_weights.get(subfacet, 0.0) for subfacet in residual_subfacets)
    if uncovered_requested and candidate_subfacets & covered:
        bonus += 2.0
    return bonus


def _topic_seed_requested_breadth_bonus(
    *,
    topic: str,
    candidate: _CandidateScore,
    requested_subfacets: dict[str, set[str]],
    max_requested_cover: int,
) -> float:
    requested = requested_subfacets.get(topic, set())
    if len(requested) < 3 or max_requested_cover <= 1:
        return 0.0

    covered_requested = candidate.topic_subfacets.get(topic, frozenset()) & requested
    if len(covered_requested) <= 1:
        return 0.0

    subfacet_weights = TOPIC_SUBFACET_WEIGHTS.get(topic, {})
    weighted_coverage = sum(subfacet_weights.get(subfacet, 0.0) for subfacet in covered_requested)
    breadth_bonus = 20.0 * (len(covered_requested) - 1)
    return breadth_bonus + (2.0 * weighted_coverage)


def _topic_subfacet_novelty_bonus(
    *,
    candidate: _CandidateScore,
    desired_topics: list[str],
    covered_subfacets: defaultdict[str, set[str]],
    requested_subfacets: dict[str, set[str]],
) -> float:
    bonus = 0.0
    for topic in desired_topics:
        if candidate.topic_scores.get(topic, 0.0) <= 0:
            continue
        bonus += _topic_subfacet_bonus_for_topic(
            topic=topic,
            candidate=candidate,
            covered_subfacets=covered_subfacets,
            requested_subfacets=requested_subfacets,
        )
    return bonus


def _missing_requested_subfacets(
    *,
    requested_subfacets: dict[str, set[str]],
    covered_subfacets: defaultdict[str, set[str]],
) -> dict[str, set[str]]:
    missing: dict[str, set[str]] = {}
    for topic, requested in requested_subfacets.items():
        uncovered = set(requested) - covered_subfacets[topic]
        if uncovered:
            missing[topic] = uncovered
    return missing


def _candidate_covers_missing_requested_subfacet(
    candidate: _CandidateScore,
    missing_requested_subfacets: dict[str, set[str]],
) -> bool:
    for topic, missing in missing_requested_subfacets.items():
        if candidate.topic_subfacets.get(topic, frozenset()) & missing:
            return True
    return False


def _candidate_needs_soft_document_limit_exception(
    *,
    candidate: _CandidateScore,
    remaining: list[_CandidateScore],
    missing_requested_subfacets: dict[str, set[str]],
    per_document_counts: defaultdict[str, int],
    per_document_limit: int,
) -> bool:
    candidate_document_key = candidate.chunk.document_version_id
    candidate_hits: dict[str, set[str]] = {}
    for topic, missing in missing_requested_subfacets.items():
        hits = set(candidate.topic_subfacets.get(topic, frozenset()) & missing)
        if hits:
            candidate_hits[topic] = hits

    if not candidate_hits:
        return False

    for other in remaining:
        other_document_key = other.chunk.document_version_id
        if other_document_key == candidate_document_key:
            continue
        if per_document_counts[other_document_key] >= per_document_limit:
            continue
        for topic, hits in candidate_hits.items():
            if other.topic_subfacets.get(topic, frozenset()) & hits:
                return False

    return True


def _compute_topic_scores(
    *,
    document_title: str,
    section_titles: list[str],
    chunk_text: str,
) -> dict[str, float]:
    title_normalized = normalize_space(document_title).lower()
    section_text = normalize_space("\n".join(section_titles)).lower()
    leaf_section_text = normalize_space(section_titles[-1]).lower() if section_titles else ""
    body_normalized = normalize_space(chunk_text).lower()
    topic_scores: dict[str, float] = {}

    for topic, keywords in TOPIC_KEYWORDS.items():
        score = 0.0
        for keyword in keywords:
            lowered_keyword = keyword.lower()
            if leaf_section_text and lowered_keyword in leaf_section_text:
                score += 5.0
            elif section_text and lowered_keyword in section_text:
                score += 4.0
            elif lowered_keyword in title_normalized:
                score += 3.0
            elif lowered_keyword in body_normalized:
                score += 1.0
        if score > 0:
            topic_scores[topic] = score
    return topic_scores


def _topic_alignment_bonus(topic_scores: dict[str, float], desired_topics: list[str]) -> float:
    bonus = 0.0
    for topic in desired_topics:
        if topic_scores.get(topic, 0.0) > 0:
            bonus += 4.0
    return bonus


def _pick_topic_candidate(
    *,
    remaining: list[_CandidateScore],
    selected: list[_CandidateScore],
    per_document_counts: defaultdict[str, int],
    per_document_limit: int,
    topic: str,
    covered_subfacets: defaultdict[str, set[str]],
    requested_subfacets: dict[str, set[str]],
    query_text: str,
) -> _CandidateScore | None:
    best_candidate: _CandidateScore | None = None
    best_value: float | None = None
    selected_documents = {item.chunk.document_version_id for item in selected}
    eligible_candidates: list[_CandidateScore] = []

    for candidate in remaining:
        document_key = candidate.chunk.document_version_id
        if per_document_counts[document_key] >= per_document_limit:
            continue
        if _is_overlapping_duplicate(candidate, selected):
            continue

        topic_score = candidate.topic_scores.get(topic, 0.0)
        if topic_score <= 0:
            continue
        eligible_candidates.append(candidate)

    if not eligible_candidates:
        return None

    title_matched_candidates = [
        candidate
        for candidate in eligible_candidates
        if _document_title_matches_topic(candidate.chunk.document_title, topic)
    ]
    if title_matched_candidates:
        eligible_candidates = title_matched_candidates

    requested = requested_subfacets.get(topic, set())
    max_requested_cover = max(
        (
            len(candidate.topic_subfacets.get(topic, frozenset()) & requested)
            for candidate in eligible_candidates
        ),
        default=0,
    )

    for candidate in eligible_candidates:
        document_key = candidate.chunk.document_version_id
        if _looks_like_toc_or_index_chunk(candidate.chunk.text):
            continue
        if not _candidate_covers_core_query_terms(
            candidate=candidate,
            query_text=query_text,
        ):
            continue
        topic_score = candidate.topic_scores.get(topic, 0.0)
        utility = candidate.overall_score + 28.0 + (topic_score * 1.5)
        utility += 2.0 * len(candidate.clause_hits)
        utility += _topic_subfacet_bonus_for_topic(
            topic=topic,
            candidate=candidate,
            covered_subfacets=covered_subfacets,
            requested_subfacets=requested_subfacets,
        )
        utility += _topic_seed_requested_breadth_bonus(
            topic=topic,
            candidate=candidate,
            requested_subfacets=requested_subfacets,
            max_requested_cover=max_requested_cover,
        )
        utility += _topic_section_hint_bonus(topic, candidate.chunk.section_titles)
        utility += _topic_focus_bonus(
            topic,
            candidate.chunk.document_title,
            candidate.chunk.section_titles,
            candidate.chunk.text,
        )
        utility += _query_intent_bonus(
            topic=topic,
            query_text=query_text,
            document_title=candidate.chunk.document_title,
            section_titles=candidate.chunk.section_titles,
            chunk_text=candidate.chunk.text,
        )
        utility += _topic_query_conflict_penalty(
            topic=topic,
            query_text=query_text,
            document_title=candidate.chunk.document_title,
            section_titles=candidate.chunk.section_titles,
            chunk_text=candidate.chunk.text,
        )
        if document_key not in selected_documents:
            utility += 5.0
        utility -= 4.0 * per_document_counts[document_key]

        if best_value is None or utility > best_value:
            best_value = utility
            best_candidate = candidate

    return best_candidate


def _candidate_covers_core_query_terms(
    *,
    candidate: _CandidateScore,
    query_text: str,
) -> bool:
    core_terms = _extract_core_query_terms(query_text)
    if len(core_terms) < 2:
        return True

    candidate_tokens = _tokenize_for_search(
        "\n".join(
            [
                candidate.chunk.document_title,
                "\n".join(candidate.chunk.section_titles),
                candidate.chunk.text,
            ]
        )
    )
    matched_terms = {term for term in core_terms if candidate_tokens.get(term, 0) > 0}
    required_matches = max(1, min(len(core_terms), math.ceil(len(core_terms) * 0.5)))
    return len(matched_terms) >= required_matches


def _extract_core_query_terms(query_text: str) -> set[str]:
    tokens = _tokenize_for_search(query_text)
    core_terms: set[str] = set()
    for term in tokens:
        if not re.fullmatch(r"[a-z0-9_./=-]+", term):
            continue
        if term in QUERY_CORE_TERM_STOPWORDS:
            continue
        if term.isdigit():
            continue
        if len(term) < 4 and not any(char in term for char in {"_", "/", ".", "-"}):
            continue
        core_terms.add(term)
    return core_terms


def _document_title_matches_topic(document_title: str, topic: str) -> bool:
    title_normalized = normalize_space(document_title).lower()
    if not title_normalized:
        return False

    for keyword in TOPIC_KEYWORDS.get(topic, ()):
        lowered_keyword = keyword.lower()
        if lowered_keyword in title_normalized:
            return True
    return False


def _topic_focus_bonus(
    topic: str,
    document_title: str,
    section_titles: list[str],
    chunk_text: str,
) -> float:
    title_text = normalize_space(document_title).lower()
    section_text = normalize_space("\n".join(section_titles)).lower()
    leaf_section_text = normalize_space(section_titles[-1]).lower() if section_titles else ""
    body_text = normalize_space(chunk_text).lower()
    score = 0.0
    for keyword in TOPIC_FOCUS_KEYWORDS.get(topic, ()):
        lowered_keyword = keyword.lower()
        if leaf_section_text and lowered_keyword in leaf_section_text:
            score += 4.0
        elif section_text and lowered_keyword in section_text:
            score += 3.0
        elif lowered_keyword in title_text:
            score += 2.5
        elif lowered_keyword in body_text:
            score += 1.5
    return min(score, 12.0)


def _topic_section_hint_bonus(topic: str, section_titles: list[str]) -> float:
    if not section_titles:
        return 0.0

    combined_text = normalize_space("\n".join(section_titles)).lower()
    leaf_text = normalize_space(section_titles[-1]).lower()
    score = 0.0

    for hint, weight in TOPIC_SECTION_HINTS.get(topic, ()):
        lowered_hint = hint.lower()
        if leaf_text and lowered_hint in leaf_text:
            score += weight
        elif lowered_hint in combined_text:
            score += weight * 0.6

    return score


def _query_intent_bonus(
    *,
    topic: str,
    query_text: str,
    document_title: str,
    section_titles: list[str],
    chunk_text: str,
) -> float:
    normalized_query = normalize_space(query_text).lower()
    if not normalized_query:
        return 0.0

    title_text = normalize_space(document_title).lower()
    section_text = normalize_space("\n".join(section_titles)).lower()
    leaf_text = normalize_space(section_titles[-1]).lower() if section_titles else ""
    body_text = normalize_space(chunk_text).lower()
    score = 0.0

    for query_terms, hints in QUERY_INTENT_HINTS.get(topic, ()):
        matched_terms = sum(1 for term in query_terms if term.lower() in normalized_query)
        required_matches = max(1, len(query_terms) - 1)
        if matched_terms < required_matches:
            continue

        for hint, weight in hints:
            lowered_hint = hint.lower()
            if leaf_text and lowered_hint in leaf_text:
                score += weight
            elif section_text and lowered_hint in section_text:
                score += weight * 0.8
            elif lowered_hint in title_text:
                score += weight * 0.6
            elif lowered_hint in body_text:
                score += weight * 0.5

    return score


def _topic_query_conflict_penalty(
    *,
    topic: str,
    query_text: str,
    document_title: str,
    section_titles: list[str],
    chunk_text: str,
) -> float:
    normalized_query = normalize_space(query_text).lower()
    if not normalized_query or topic != "api":
        return 0.0

    asks_event_scope = any(
        term in normalized_query
        for term in (
            "websocket",
            "事件能力",
            "事件类型",
            "流式过程",
            "事件查询",
        )
    )
    asks_artifact_scope = any(
        term in normalized_query
        for term in (
            "artifact",
            "artifacts",
            "产物",
        )
    )
    asks_broad_api_scope = any(
        term in normalized_query
        for term in (
            "最小可交付范围",
            "一起说明",
            "字段",
            "profile",
            "profiles",
            "后端能力",
            "治理规则",
            "测试与回滚",
            "灰度",
            "回滚",
        )
    )
    if not asks_event_scope or asks_artifact_scope:
        return 0.0

    title_text = normalize_space(document_title).lower()
    section_text = normalize_space("\n".join(section_titles)).lower()
    leaf_text = normalize_space(section_titles[-1]).lower() if section_titles else ""
    body_text = normalize_space(chunk_text).lower()
    combined_text = "\n".join((title_text, section_text, body_text))
    if "artifacts" not in combined_text:
        return 0.0

    if (
        "审批协议" in combined_text
        or "approve_once" in combined_text
        or "cancel_run" in combined_text
        or "approval request" in combined_text
    ):
        return 0.0

    event_signals = ("websocket", "runtime_status", "runtime_requires_approval", "events")
    if not asks_broad_api_scope:
        if "artifacts" in leaf_text and "events" in leaf_text:
            return -56.0
        if "artifacts" in leaf_text and any(signal in leaf_text for signal in event_signals):
            return -48.0
        if "artifacts" in section_text and any(signal in combined_text for signal in event_signals):
            return -40.0
        if "artifacts" in section_text:
            return -28.0
        return -18.0

    if "artifacts" in leaf_text and "events" in leaf_text:
        return -30.0
    if "artifacts" in leaf_text and any(signal in leaf_text for signal in event_signals):
        return -22.0
    if "artifacts" in leaf_text:
        return -18.0
    if "artifacts" in section_text:
        return -12.0
    return -8.0


def _thin_chunk_penalty(
    *,
    chunk_text: str,
    document_title: str,
    section_titles: list[str],
) -> float:
    normalized_text = normalize_space(chunk_text).lower()
    if not normalized_text:
        return -2.0

    document_title_text = normalize_space(document_title).lower()
    leaf_section_text = normalize_space(section_titles[-1]).lower() if section_titles else ""
    non_empty_lines = [line.strip() for line in chunk_text.splitlines() if line.strip()]
    if normalized_text == document_title_text:
        return -4.0
    if leaf_section_text and normalized_text == leaf_section_text:
        return -3.0
    if len(non_empty_lines) == 1 and len(_tokenize_for_search(normalized_text)) <= 4:
        return -2.0
    return 0.0


def _build_section_title_map(document_payload: dict) -> dict[tuple[str, ...], str]:
    mapping: dict[tuple[str, ...], str] = {}
    for section in document_payload.get("sections") or []:
        section_path = tuple(str(part) for part in (section.get("section_path") or []))
        title = normalize_space(section.get("title") or "")
        if not section_path or not title or title == "Document":
            continue
        mapping[section_path] = title
    return mapping


def _derive_section_titles(
    *,
    section_path: list[str],
    section_titles_by_path: dict[tuple[str, ...], str],
) -> list[str]:
    titles: list[str] = []
    for prefix_length in range(1, len(section_path) + 1):
        title = section_titles_by_path.get(tuple(section_path[:prefix_length]))
        if title:
            titles.append(title)
    return titles


def _extract_reference_items(markdown: str) -> list[str]:
    items: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if LIST_ITEM_RE.match(line):
            item = LIST_ITEM_RE.sub("", line).strip()
            if _reference_item_is_summary_header(item) or _reference_item_is_editorial_summary(item):
                continue
            items.append(item)
    return items


def _item_is_covered(
    *,
    normalized_item: str,
    item_tokens: Counter[str],
    item_concepts: set[str],
    auto_corpus: str,
    auto_tokens: Counter[str],
    auto_concepts: set[str],
) -> bool:
    if item_concepts:
        return item_concepts.issubset(auto_concepts)
    if normalized_item in auto_corpus:
        return True
    if not item_tokens:
        return False

    matched = 0
    weighted_total = 0.0
    weighted_matched = 0.0
    for term, count in item_tokens.items():
        weight = _term_weight(term) * count
        weighted_total += weight
        if auto_tokens.get(term, 0):
            matched += 1
            weighted_matched += weight

    return matched >= max(1, min(3, len(item_tokens) // 2)) and (
        weighted_matched / max(0.1, weighted_total)
    ) >= 0.6


def _reference_item_is_summary_header(item: str) -> bool:
    normalized = _normalize_reference_item_text(item)
    if len(normalized) < 6:
        return False
    return normalized.endswith(":") or normalized.endswith("：")


def _reference_item_is_editorial_summary(item: str) -> bool:
    normalized = _normalize_reference_item_text(item)
    if not normalized:
        return False
    editorial_markers = (
        "这轮问题的真正难点不是",
        "真正难点不是",
        "关键不是",
    )
    return any(marker in normalized for marker in editorial_markers)


def _normalize_reference_item_text(item: str) -> str:
    normalized = normalize_space(item)
    normalized = INLINE_MARKDOWN_RE.sub(" ", normalized)
    normalized = REFERENCE_EVIDENCE_RE.sub("", normalized)
    return normalize_space(normalized).lower()


def _extract_reference_concepts(text: str) -> set[str]:
    normalized = _normalize_reference_item_text(text)
    concepts: set[str] = set()
    if not normalized:
        return concepts

    for concept, aliases in REFERENCE_CONCEPT_ALIASES.items():
        for alias in aliases:
            if alias.lower() in normalized:
                concepts.add(concept)
                break
    return concepts


def _render_context_pack_markdown(
    *,
    query: str,
    task_type: str,
    task_profile: dict[str, object],
    warnings: list[str],
    chunks: list[RetrievedChunk],
) -> str:
    rendered_sections = _build_render_sections(chunks, task_type=task_type)
    lines = [
        "# Context Pack",
        "",
        f"Schema Version: `{CONTEXT_PACK_SCHEMA_VERSION}`",
        f"Task Type: `{task_type}`",
        f"Task Intent: {task_profile.get('intent')}",
        "",
        "Query:",
        "",
        query.strip(),
        "",
        f"Selected Documents: {len({chunk.document_version_id for chunk in chunks})}",
        f"Selected Chunks: {len(chunks)}",
        "",
        "## Agent Use",
        "",
    ]
    agent_use = [str(item) for item in (task_profile.get("agent_use") or [])]
    lines.extend(f"- {item}" for item in agent_use)
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- `{warning}`" for warning in warnings)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
        "## Summary",
        "",
        ]
    )

    summary_lines = _render_summary_lines(rendered_sections)
    lines.extend(summary_lines if summary_lines else ["- No evidence selected.", ""])

    for section_label, evidence_items in rendered_sections:
        lines.extend([f"## {section_label}", ""])
        for evidence_number, chunk in evidence_items:
            lines.extend(_render_evidence_block(chunk=chunk, evidence_number=evidence_number))

    lines.extend(["## Evidence Appendix", ""])
    appendix_lines = _render_evidence_appendix_lines(rendered_sections)
    lines.extend(appendix_lines if appendix_lines else ["- None", ""])

    return "\n".join(lines).strip() + "\n"


def _build_context_pack_section_payloads(
    chunks: list[RetrievedChunk],
    *,
    task_type: str = DEFAULT_CONTEXT_PACK_TASK_TYPE,
    include_full_chunk: bool = True,
) -> list[dict[str, object]]:
    payload_sections: list[dict[str, object]] = []
    normalized_task_type = _normalize_context_pack_task_type(task_type)
    for section_label, evidence_items in _build_render_sections(
        chunks,
        task_type=normalized_task_type,
    ):
        items: list[dict[str, object]] = []
        for evidence_number, chunk in evidence_items:
            topic = _classify_chunk_topic(chunk)
            item_payload: dict[str, object] = {
                "evidence_number": evidence_number,
                "task_item_type": _task_item_type_for_topic(
                    task_type=normalized_task_type,
                    topic=topic,
                ),
                "summary": _summarize_chunk(chunk),
                "document_title": chunk.document_title,
                "document_version": chunk.document_version,
                "project": chunk.project,
                "supplier": chunk.supplier,
                "source_type": chunk.source_type,
                "source_path": chunk.source_path,
                "section_titles": list(chunk.section_titles),
                "section_path": list(chunk.section_path),
                "matched_clauses": list(chunk.matched_clauses),
                "score": round(chunk.score, 4),
                "retrieval_signals": list(chunk.retrieval_signals),
                "evidence_ids": list(chunk.evidence_ids),
                "quality_status": chunk.quality_status,
                "quality_score": chunk.quality_score,
                "allowed_for_context_pack": chunk.allowed_for_context_pack,
                "quality_gate_reasons": list(chunk.quality_gate_reasons),
                "warnings": list(chunk.warnings),
            }
            if include_full_chunk:
                item_payload["chunk"] = chunk.to_dict()
            items.append(item_payload)
        payload_sections.append(
            {
                "title": section_label,
                "items": items,
            }
        )
    return payload_sections


def _build_render_sections(
    chunks: list[RetrievedChunk],
    *,
    task_type: str = DEFAULT_CONTEXT_PACK_TASK_TYPE,
) -> list[tuple[str, list[tuple[int, RetrievedChunk]]]]:
    normalized_task_type = _normalize_context_pack_task_type(task_type)
    sections: list[tuple[str, list[tuple[int, RetrievedChunk]]]] = []
    current_label: str | None = None
    current_items: list[tuple[int, RetrievedChunk]] = []

    for index, chunk in enumerate(chunks, start=1):
        topic = _classify_chunk_topic(chunk)
        section_label = _section_label_for_topic(
            task_type=normalized_task_type,
            topic=topic,
        )
        if current_label is not None and section_label != current_label:
            sections.append((current_label, current_items))
            current_items = []
        current_label = section_label
        current_items.append((index, chunk))

    if current_label is not None:
        sections.append((current_label, current_items))
    return sections


def _section_label_for_topic(*, task_type: str, topic: str) -> str:
    labels = TASK_TOPIC_SECTION_LABELS.get(task_type, TOPIC_SECTION_LABELS)
    return labels.get(topic, labels.get("other", TOPIC_SECTION_LABELS["other"]))


def _task_item_type_for_topic(*, task_type: str, topic: str) -> str:
    item_types = TASK_TOPIC_ITEM_TYPES.get(task_type, {})
    return item_types.get(topic, item_types.get("other", "supporting_evidence"))


def _classify_chunk_topic(chunk: RetrievedChunk) -> str:
    topic_scores = _compute_topic_scores(
        document_title=chunk.document_title,
        section_titles=chunk.section_titles,
        chunk_text=chunk.text,
    )
    if not topic_scores:
        return "other"

    ranked_topics: list[tuple[float, int, str]] = []
    for topic, base_score in topic_scores.items():
        combined_score = (
            base_score
            + _topic_section_hint_bonus(topic, chunk.section_titles)
            + _topic_focus_bonus(topic, chunk.document_title, chunk.section_titles, chunk.text)
        )
        ranked_topics.append(
            (
                combined_score,
                RENDER_TOPIC_ORDER.index(topic) if topic in RENDER_TOPIC_ORDER else len(RENDER_TOPIC_ORDER),
                topic,
            )
        )

    ranked_topics.sort(key=lambda item: (-item[0], item[1], item[2]))
    return ranked_topics[0][2]


def _render_summary_lines(
    rendered_sections: list[tuple[str, list[tuple[int, RetrievedChunk]]]],
) -> list[str]:
    lines: list[str] = []
    for section_label, evidence_items in rendered_sections:
        if not evidence_items:
            continue
        evidence_numbers = [number for number, _ in evidence_items]
        primary_chunk = evidence_items[0][1]
        summary_text = _summarize_chunk(primary_chunk)
        lines.append(
            f"- {section_label}: {summary_text} {_format_evidence_refs(evidence_numbers)}".rstrip()
        )
    lines.append("")
    return lines


def _summarize_chunk(chunk: RetrievedChunk, *, max_chars: int = 180) -> str:
    raw_lines = [normalize_space(line) for line in chunk.text.splitlines() if normalize_space(line)]
    if not raw_lines:
        return "No summary available."

    cleaned_lines: list[str] = []
    for line in raw_lines:
        cleaned = LIST_ITEM_RE.sub("", line).strip()
        if cleaned:
            cleaned_lines.append(cleaned)

    if not cleaned_lines:
        cleaned_lines = raw_lines

    summary = "; ".join(cleaned_lines[:3])
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 3].rstrip() + "..."


def _format_evidence_refs(evidence_numbers: list[int]) -> str:
    if not evidence_numbers:
        return ""
    if len(evidence_numbers) == 1:
        return f"[Evidence {evidence_numbers[0]}]"
    refs = ", ".join(str(number) for number in evidence_numbers[:4])
    if len(evidence_numbers) > 4:
        refs = f"{refs}, ..."
    return f"[Evidence {refs}]"


def _render_evidence_block(*, chunk: RetrievedChunk, evidence_number: int) -> list[str]:
    lines = [
        f"### Evidence {evidence_number}",
        f"Source: `{chunk.document_title}`",
        f"Score: `{chunk.score:.2f}`",
        f"Quality: `{chunk.quality_status}`",
    ]
    if chunk.retrieval_signals:
        lines.append(f"Retrieval Signals: `{', '.join(chunk.retrieval_signals)}`")
    if chunk.quality_score is not None:
        lines.append(f"Quality Score: `{chunk.quality_score:.2f}`")
    if not chunk.allowed_for_context_pack or chunk.quality_gate_reasons:
        gate = ", ".join(chunk.quality_gate_reasons) if chunk.quality_gate_reasons else "blocked"
        lines.append(f"Quality Gate: `{gate}`")
    if chunk.warnings:
        lines.append(f"Warnings: `{'; '.join(chunk.warnings[:3])}`")
    if chunk.matched_clauses:
        lines.append(f"Matched Clauses: `{'; '.join(chunk.matched_clauses)}`")
    if chunk.source_path:
        lines.append(f"Path: `{chunk.source_path}`")
    if chunk.section_path:
        lines.append(f"Section Path: `{'.'.join(chunk.section_path)}`")
    if chunk.section_titles:
        lines.append(f"Section Titles: `{' > '.join(chunk.section_titles)}`")
    if chunk.evidence_ids:
        lines.append(f"Evidence IDs: `{', '.join(chunk.evidence_ids)}`")
    if chunk.page_start is not None or chunk.page_end is not None:
        if chunk.page_start == chunk.page_end:
            page_text = f"{chunk.page_start}"
        else:
            page_text = f"{chunk.page_start}..{chunk.page_end}"
        lines.append(f"Pages: `{page_text}`")
    lines.extend(
        [
            "",
            "```text",
            chunk.text,
            "```",
            "",
        ]
    )
    return lines


def _render_evidence_appendix_lines(
    rendered_sections: list[tuple[str, list[tuple[int, RetrievedChunk]]]],
) -> list[str]:
    lines: list[str] = []
    for section_label, evidence_items in rendered_sections:
        for evidence_number, chunk in evidence_items:
            location_parts = [f"Evidence {evidence_number}: `{chunk.document_title}`"]
            if chunk.section_titles:
                location_parts.append(f"`{' > '.join(chunk.section_titles)}`")
            location_parts.append(f"section `{'.'.join(chunk.section_path)}`" if chunk.section_path else "section `unknown`")
            lines.append(f"- {' | '.join(location_parts)}")
    lines.append("")
    return lines


def _render_gap_report_markdown(
    *,
    reference_markdown_path: Path,
    covered: list[str],
    missing: list[str],
) -> str:
    lines = [
        "# Context Pack Gap Report",
        "",
        f"Reference: `{reference_markdown_path}`",
        "",
        f"Covered Items: {len(covered)}",
        f"Missing Items: {len(missing)}",
        "",
        "## Covered",
        "",
    ]
    if covered:
        lines.extend(f"- {item}" for item in covered)
    else:
        lines.append("- None")

    lines.extend(["", "## Missing", ""])
    if missing:
        lines.extend(f"- {item}" for item in missing)
    else:
        lines.append("- None")

    return "\n".join(lines).strip() + "\n"
