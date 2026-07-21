from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_knowledge_hub.dependencies import (
    check_runtime_dependencies,
    write_runtime_dependency_report_bundle,
)
from agent_knowledge_hub.contract import (
    validate_processed_dir,
    write_processed_contract_summary_bundle,
)
from agent_knowledge_hub.eval_setup import (
    build_eval_run_status,
    check_eval_business_readiness,
    prepare_eval_execution_pack,
    prepare_eval_review_pack,
    prepare_eval_run,
    record_eval_output,
    record_eval_review_decision,
    score_eval_run,
)
from agent_knowledge_hub.incremental import ingest_manifest_incremental
from agent_knowledge_hub.inventory import (
    build_document_inventory,
    write_document_inventory_bundle,
)
from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.layer2_run import run_layer2_acceptance
from agent_knowledge_hub.pipeline import ingest_file, ingest_manifest
from agent_knowledge_hub.quality import (
    build_parse_quality_summary,
    write_parse_quality_summary_bundle,
)
from agent_knowledge_hub.release_manifest import (
    activate_release,
    load_release_manifest,
)
from agent_knowledge_hub.release_pipeline import build_release_bundle
from agent_knowledge_hub.retrieval import (
    build_context_pack_for_processed_dir,
    compare_context_pack_against_reference,
    load_context_pack_result,
    trace_evidence_in_processed_dir,
    write_context_pack_bundle,
    write_gap_report_bundle,
)
from agent_knowledge_hub.vector_index import build_vector_index


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "file":
            result = ingest_file(
                file_path=args.file_path,
                out_dir=args.out_dir,
                title=args.title,
                source_type=args.source_type,
                owner=args.owner,
                project=args.project,
                supplier=args.supplier,
                document_version=args.document_version,
                sample_id=args.sample_id,
                max_chunk_chars=args.max_chunk_chars,
                max_tokens=args.max_tokens,
                overlap_chars=args.overlap_chars,
            )
            payload = result.to_summary_dict()
        elif args.command == "manifest":
            if args.incremental:
                summary = ingest_manifest_incremental(
                    manifest_path=args.manifest_path,
                    out_dir=args.out_dir,
                    project_root=args.project_root,
                    max_chunk_chars=args.max_chunk_chars,
                    max_tokens=args.max_tokens,
                    overlap_chars=args.overlap_chars,
                    fail_fast=args.fail_fast,
                )
            else:
                summary = ingest_manifest(
                    manifest_path=args.manifest_path,
                    out_dir=args.out_dir,
                    project_root=args.project_root,
                    max_chunk_chars=args.max_chunk_chars,
                    max_tokens=args.max_tokens,
                    overlap_chars=args.overlap_chars,
                    fail_fast=args.fail_fast,
                )
            payload = summary.to_dict()
        elif args.command == "inventory":
            inventory = build_document_inventory(
                root_dirs=args.root_dir,
                max_files=args.max_files,
                max_file_mb=args.max_file_mb,
                owner=args.owner,
                project=args.project,
                document_version=args.document_version,
                include_keywords=args.include_keyword,
                exclude_keywords=args.exclude_keyword,
                dedupe_content_hash=not args.allow_duplicate_hash,
            )
            if args.output_dir:
                bundle_paths = write_document_inventory_bundle(
                    output_dir=args.output_dir,
                    inventory=inventory,
                    sample_size=args.sample_size,
                )
                payload = {
                    **inventory.to_dict(),
                    **{key: str(value) for key, value in bundle_paths.items()},
                }
            else:
                _emit_text(inventory.markdown)
                return 0
        elif args.command == "context-pack":
            query = _resolve_query_text(args.query, args.query_file)
            result = build_context_pack_for_processed_dir(
                processed_dir=args.processed_dir,
                query=query,
                task_type=args.task_type,
                top_k=args.top_k,
                per_document_limit=args.per_document_limit,
                metadata_filters=_build_metadata_filters_from_args(args),
                fts_index_path=args.fts_index_path,
                vector_index_path=args.vector_index_path,
                token_budget=args.token_budget,
                release_manifest_path=args.release_manifest_path,
            )
            if args.output_dir:
                bundle_paths = write_context_pack_bundle(
                    output_dir=args.output_dir,
                    result=result,
                )
                payload = {
                    **result.to_summary_dict(output_dir=args.output_dir),
                    **{key: str(value) for key, value in bundle_paths.items()},
                }
            elif args.output_path:
                args.output_path.parent.mkdir(parents=True, exist_ok=True)
                args.output_path.write_text(result.markdown, encoding="utf-8")
                payload = result.to_summary_dict(output_dir=args.output_path.parent)
            else:
                _emit_text(result.markdown)
                return 0
        elif args.command == "gap-report":
            auto_result = load_context_pack_result(args.auto_context_pack_json)
            report = compare_context_pack_against_reference(
                auto_result=auto_result,
                reference_markdown_path=args.reference_markdown,
            )
            if args.output_dir:
                bundle_paths = write_gap_report_bundle(
                    output_dir=args.output_dir,
                    report=report,
                )
                payload = {
                    **report.to_dict(),
                    **{key: str(value) for key, value in bundle_paths.items()},
                }
            else:
                _emit_text(report.markdown)
                return 0
        elif args.command == "trace":
            result = trace_evidence_in_processed_dir(
                processed_dir=args.processed_dir,
                evidence_id=args.evidence_id,
                release_manifest_path=args.release_manifest_path,
            )
            payload = result.to_dict()
            if args.output_path:
                args.output_path.parent.mkdir(parents=True, exist_ok=True)
                args.output_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        elif args.command == "parse-quality-summary":
            summary = build_parse_quality_summary(args.processed_dir)
            if args.output_dir:
                bundle_paths = write_parse_quality_summary_bundle(
                    output_dir=args.output_dir,
                    summary=summary,
                )
                payload = {
                    **summary.to_dict(),
                    **{key: str(value) for key, value in bundle_paths.items()},
                }
            else:
                _emit_text(summary.markdown)
                return 0
        elif args.command == "build-fts-index":
            summary = build_fts_index(
                processed_dir=args.processed_dir,
                index_path=args.index_path,
            )
            payload = summary.to_dict()
        elif args.command == "build-vector-index":
            summary = build_vector_index(
                processed_dir=args.processed_dir,
                index_path=args.index_path,
            )
            payload = summary.to_dict()
        elif args.command == "build-release":
            release = build_release_bundle(
                processed_dir=args.processed_dir,
                releases_dir=args.releases_dir,
            )
            payload = {
                **release.to_dict(),
                "manifest_path": str(release.manifest_path),
            }
        elif args.command == "activate-release":
            activate_release(args.manifest_path, args.active_pointer)
            release = load_release_manifest(args.manifest_path)
            payload = {
                "release_id": release.release_id,
                "status": release.status,
                "manifest_path": str(release.manifest_path),
                "active_pointer": str(args.active_pointer.resolve()),
            }
        elif args.command == "layer2-run":
            summary = run_layer2_acceptance(
                processed_dir=args.processed_dir,
                output_dir=args.output_dir,
                query=_resolve_query_text(args.query, args.query_file),
                top_k=args.top_k,
                per_document_limit=args.per_document_limit,
            )
            payload = summary.to_dict()
            if args.require_ready and not summary.is_ready:
                _emit_json(payload)
                return 1
        elif args.command == "prepare-eval-run":
            summary = prepare_eval_run(
                eval_cases_path=args.eval_cases,
                processed_dir=args.processed_dir,
                output_dir=args.output_dir,
                run_id=args.run_id,
                agent=args.agent,
                model=args.model,
                top_k=args.top_k,
                per_document_limit=args.per_document_limit,
                fts_index_path=args.fts_index_path,
                vector_index_path=args.vector_index_path,
            )
            payload = summary.to_dict()
        elif args.command == "prepare-eval-execution-pack":
            summary = prepare_eval_execution_pack(
                eval_run_dir=args.eval_run_dir,
                eval_cases_path=args.eval_cases,
            )
            payload = summary.to_dict()
        elif args.command == "prepare-eval-review-pack":
            summary = prepare_eval_review_pack(
                eval_cases_path=args.eval_cases,
                eval_run_dir=args.eval_run_dir,
            )
            payload = summary.to_dict()
        elif args.command == "record-eval-output":
            output_text = _resolve_query_text(args.output_text, args.output_file)
            summary = record_eval_output(
                eval_run_dir=args.eval_run_dir,
                task_id=args.task_id,
                group=args.group,
                output_text=output_text,
                agent=args.agent,
                model=args.model,
                token_input=args.token_input,
                token_output=args.token_output,
                elapsed_minutes=args.elapsed_minutes,
                notes=args.notes,
                refresh_execution_pack=args.refresh_execution_pack,
                eval_cases_path=args.eval_cases,
            )
            payload = summary.to_dict()
        elif args.command == "record-eval-review-decision":
            summary = record_eval_review_decision(
                eval_run_dir=args.eval_run_dir,
                task_id=args.task_id,
                checker=args.checker,
                baseline_answer_correct=args.baseline_answer_correct,
                context_pack_answer_correct=args.context_pack_answer_correct,
                context_pack_retrieval_useful=args.context_pack_retrieval_useful,
                winner=args.winner,
                baseline_human_fix_count=args.baseline_human_fix_count,
                context_pack_human_fix_count=args.context_pack_human_fix_count,
                notes=args.notes,
                eval_cases_path=args.eval_cases,
            )
            payload = summary.to_dict()
        elif args.command == "score-eval-run":
            summary = score_eval_run(
                eval_cases_path=args.eval_cases,
                eval_run_dir=args.eval_run_dir,
                require_business_evidence=args.require_business_evidence,
            )
            payload = summary.to_dict()
        elif args.command == "check-eval-business-readiness":
            summary = check_eval_business_readiness(
                eval_cases_path=args.eval_cases,
                eval_run_dir=args.eval_run_dir,
            )
            payload = summary.to_dict()
            if args.require_ready and not summary.business_evidence_ready:
                raise ValueError(
                    "Eval run is not ready as business evidence: "
                    + ", ".join(summary.business_evidence_blockers)
                )
        elif args.command == "eval-run-status":
            summary = build_eval_run_status(
                eval_cases_path=args.eval_cases,
                eval_run_dir=args.eval_run_dir,
            )
            payload = summary.to_dict()
        elif args.command == "watch-repo":
            from agent_knowledge_hub.code_watcher import run_watch_service
            run_watch_service(
                watch_dir=args.watch_dir,
                out_dir=args.out_dir,
                project=args.project,
                owner=args.owner,
                fts_index_path=args.fts_index_path,
                vector_index_path=args.vector_index_path,
                exclude_dirs=set(args.exclude_dir) if args.exclude_dir else None,
                debounce_seconds=args.debounce_seconds,
                rebuild_indexes=not args.no_rebuild_indexes,
            )
            return 0
        elif args.command == "generate-code-manifest":
            from agent_knowledge_hub.code_manifest import (
                DEFAULT_EXCLUDE_DIRS,
                TARGET_EXTENSIONS,
                scan_repo,
                scan_repo_with_snapshot,
                write_csv,
                write_snapshot_bundle,
            )
            repo_dir = args.repo_dir.resolve()
            exclude_dirs = (
                frozenset[str]() if args.no_default_excludes else DEFAULT_EXCLUDE_DIRS
            ) | frozenset(args.exclude_dir or [])

            if args.snapshot_output:
                # Phase A 新路径：输出 RepositorySnapshot + files.jsonl
                snapshot, file_records = scan_repo_with_snapshot(
                    repo_dir, exclude_dirs, TARGET_EXTENSIONS
                )
                paths = write_snapshot_bundle(snapshot, file_records, args.snapshot_output)
                payload = {
                    "snapshot_id":   snapshot.snapshot_id,
                    "commit_sha":    snapshot.commit_sha,
                    "scanned_files": len(file_records),
                    "snapshot_json": str(paths["snapshot"]),
                    "files_jsonl":   str(paths["files"]),
                }
            else:
                # 旧路径：保持向后兼容，输出 CSV
                rows = scan_repo(repo_dir, exclude_dirs, TARGET_EXTENSIONS)
                write_csv(rows, args.output)
                payload = {"scanned_files": len(rows), "output": str(args.output)}
        elif args.command == "serve-mcp":
            import os as _os
            import sys as _sys
            import time as _time
            from agent_knowledge_hub.mcp_server import (
                create_mcp_server,
                create_mcp_server_with_repos,
            )
            from agent_knowledge_hub.retrieval import prewarm as _prewarm
            code_dir = args.code_processed_dir or (
                Path(_os.environ["CLUSTER_CODE_PROCESSED_DIR"])
                if "CLUSTER_CODE_PROCESSED_DIR" in _os.environ
                else None
            )
            docs_dir = args.docs_processed_dir or (
                Path(_os.environ["QNX_DOCS_PROCESSED_DIR"])
                if "QNX_DOCS_PROCESSED_DIR" in _os.environ
                else None
            )
            if code_dir or docs_dir:
                server = create_mcp_server_with_repos(
                    code_processed_dir=code_dir,
                    docs_processed_dir=docs_dir,
                    host=args.host,
                    port=args.port,
                    streamable_http_path=args.streamable_http_path,
                )
            else:
                server = create_mcp_server(
                    host=args.host,
                    port=args.port,
                    streamable_http_path=args.streamable_http_path,
                )
            # Pre-warm retrieval caches before the HTTP server starts.
            # Without this, the first MCP tool call loads ~44k chunks (~100s) and
            # exceeds client timeouts (e.g. Tongyi Lingma / Qoder).
            if _os.environ.get("KNOWLEDGE_HUB_SKIP_PREWARM", "") != "1":
                for _pw_dir in [code_dir, docs_dir]:
                    if _pw_dir:
                        print(f"[mcp-prewarm] prewarming {_pw_dir} ...", file=_sys.stderr, flush=True)
                        _t0 = _time.time()
                        try:
                            _prewarm(_pw_dir)
                        except Exception as _exc:
                            print(f"[mcp-prewarm] warning: prewarm failed for {_pw_dir}: {_exc}", file=_sys.stderr, flush=True)
                        print(f"[mcp-prewarm] done in {_time.time()-_t0:.1f}s", file=_sys.stderr, flush=True)
                print("[mcp-prewarm] caches ready — starting HTTP server", file=_sys.stderr, flush=True)
            server.run(transport=args.transport)
            return 0
        elif args.command == "dependency-check":
            report = check_runtime_dependencies()
            if args.output_dir:
                bundle_paths = write_runtime_dependency_report_bundle(
                    output_dir=args.output_dir,
                    report=report,
                )
                payload = {
                    **report.to_dict(),
                    **{key: str(value) for key, value in bundle_paths.items()},
                }
            else:
                _emit_text(report.markdown)
                return 0
        elif args.command == "validate-processed":
            summary = validate_processed_dir(args.processed_dir)
            if args.output_dir:
                bundle_paths = write_processed_contract_summary_bundle(
                    output_dir=args.output_dir,
                    summary=summary,
                )
                payload = {
                    **summary.to_dict(),
                    **{key: str(value) for key, value in bundle_paths.items()},
                }
            elif args.json:
                payload = summary.to_dict()
            else:
                _emit_text(summary.markdown)
                if args.require_valid and not summary.is_valid:
                    _emit_validation_errors(summary.errors)
                    return 1
                return 0
            if args.require_valid and not summary.is_valid:
                _emit_validation_errors(summary.errors)
                _emit_json(payload)
                return 1
        else:  # pragma: no cover - argparse prevents this branch
            parser.error(f"Unknown command: {args.command}")
            return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    _emit_json(payload)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-knowledge-hub-ingest",
        description="Ingest engineering documents into the canonical document model.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    file_parser = subparsers.add_parser("file", help="Ingest one document file.")
    file_parser.add_argument("--file-path", required=True, type=Path)
    _add_common_arguments(file_parser)
    file_parser.add_argument("--title")
    file_parser.add_argument("--source-type", default="unknown")
    file_parser.add_argument("--owner", default="unknown")
    file_parser.add_argument("--project", default="unknown")
    file_parser.add_argument("--supplier", default="unknown")
    file_parser.add_argument("--document-version", default="unknown")
    file_parser.add_argument("--sample-id")

    manifest_parser = subparsers.add_parser(
        "manifest", help="Ingest all usable files in a sample manifest CSV."
    )
    manifest_parser.add_argument("--manifest-path", required=True, type=Path)
    manifest_parser.add_argument("--project-root", type=Path)
    manifest_parser.add_argument("--fail-fast", action="store_true")
    manifest_parser.add_argument(
        "--incremental",
        action="store_true",
        help="Skip unchanged files based on content_hash and write ingest-run-summary.json.",
    )
    _add_common_arguments(manifest_parser)

    inventory_parser = subparsers.add_parser(
        "inventory",
        help="Discover local engineering documents and write an inventory plus sample manifest.",
    )
    inventory_parser.add_argument("--root-dir", required=True, action="append", type=Path)
    inventory_parser.add_argument("--output-dir", type=Path)
    inventory_parser.add_argument("--max-files", type=int, default=200)
    inventory_parser.add_argument("--max-file-mb", type=float, default=100.0)
    inventory_parser.add_argument("--sample-size", type=int)
    inventory_parser.add_argument("--owner", default="checker")
    inventory_parser.add_argument("--project", default="unknown")
    inventory_parser.add_argument("--document-version", default="unknown")
    inventory_parser.add_argument("--include-keyword", action="append")
    inventory_parser.add_argument("--exclude-keyword", action="append")
    inventory_parser.add_argument("--allow-duplicate-hash", action="store_true")

    context_pack_parser = subparsers.add_parser(
        "context-pack",
        help="Build a lexical Context Pack from processed chunks.",
    )
    context_pack_parser.add_argument("--processed-dir", required=True, type=Path)
    query_group = context_pack_parser.add_mutually_exclusive_group(required=True)
    query_group.add_argument("--query")
    query_group.add_argument("--query-file", type=Path)
    context_pack_parser.add_argument("--task-type", default="general_query")
    context_pack_parser.add_argument("--top-k", type=int, default=8)
    context_pack_parser.add_argument("--per-document-limit", type=int, default=2)
    context_pack_parser.add_argument(
        "--token-budget",
        type=int,
        default=None,
        help="Optional max estimated tokens for the rendered pack; trims lowest-priority chunks to fit.",
    )
    context_pack_parser.add_argument("--source-type", action="append")
    context_pack_parser.add_argument("--project-filter", action="append")
    context_pack_parser.add_argument("--supplier", action="append")
    context_pack_parser.add_argument("--document-version", action="append")
    context_pack_parser.add_argument("--fts-index-path", type=Path)
    context_pack_parser.add_argument("--vector-index-path", type=Path)
    context_pack_parser.add_argument("--release-manifest-path", type=Path)
    context_pack_parser.add_argument("--output-dir", type=Path)
    context_pack_parser.add_argument("--output-path", type=Path)

    gap_report_parser = subparsers.add_parser(
        "gap-report",
        help="Compare an auto Context Pack bundle against a reference markdown pack.",
    )
    gap_report_parser.add_argument("--auto-context-pack-json", required=True, type=Path)
    gap_report_parser.add_argument("--reference-markdown", required=True, type=Path)
    gap_report_parser.add_argument("--output-dir", type=Path)

    trace_parser = subparsers.add_parser(
        "trace",
        help="Trace one evidence id back to its source document text.",
    )
    trace_parser.add_argument("--processed-dir", required=True, type=Path)
    trace_parser.add_argument("--evidence-id", required=True)
    trace_parser.add_argument("--release-manifest-path", type=Path)
    trace_parser.add_argument("--output-path", type=Path)

    quality_parser = subparsers.add_parser(
        "parse-quality-summary",
        help="Summarize parse quality reports from processed canonical documents.",
    )
    quality_parser.add_argument("--processed-dir", required=True, type=Path)
    quality_parser.add_argument("--output-dir", type=Path)

    fts_parser = subparsers.add_parser(
        "build-fts-index",
        help="Build a persistent SQLite FTS5 index from processed chunks.",
    )
    fts_parser.add_argument("--processed-dir", required=True, type=Path)
    fts_parser.add_argument("--index-path", required=True, type=Path)

    vector_parser = subparsers.add_parser(
        "build-vector-index",
        help="Build a local JSON vector index from processed chunks.",
    )
    vector_parser.add_argument("--processed-dir", required=True, type=Path)
    vector_parser.add_argument("--index-path", required=True, type=Path)

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

    layer2_parser = subparsers.add_parser(
        "layer2-run",
        help="Run the full Layer2 acceptance loop over Layer1 processed outputs.",
    )
    layer2_parser.add_argument("--processed-dir", required=True, type=Path)
    layer2_parser.add_argument("--output-dir", required=True, type=Path)
    layer2_query_group = layer2_parser.add_mutually_exclusive_group(required=True)
    layer2_query_group.add_argument("--query")
    layer2_query_group.add_argument("--query-file", type=Path)
    layer2_parser.add_argument("--top-k", type=int, default=8)
    layer2_parser.add_argument("--per-document-limit", type=int, default=2)
    layer2_parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Return non-zero when validation, retrieval, or evidence trace is not ready.",
    )

    eval_parser = subparsers.add_parser(
        "prepare-eval-run",
        help="Generate paired raw-file vs Context Pack prompts and scoring placeholders.",
    )
    eval_parser.add_argument("--eval-cases", required=True, type=Path)
    eval_parser.add_argument("--processed-dir", required=True, type=Path)
    eval_parser.add_argument("--output-dir", required=True, type=Path)
    eval_parser.add_argument("--run-id", default="eval-run-001")
    eval_parser.add_argument("--agent", default="待填写")
    eval_parser.add_argument("--model", default="待填写")
    eval_parser.add_argument("--top-k", type=int, default=8)
    eval_parser.add_argument("--per-document-limit", type=int, default=2)
    eval_parser.add_argument("--fts-index-path", type=Path)
    eval_parser.add_argument("--vector-index-path", type=Path)

    eval_execution_parser = subparsers.add_parser(
        "prepare-eval-execution-pack",
        help="Generate a real-Agent execution guide from a prepared eval run.",
    )
    eval_execution_parser.add_argument("--eval-run-dir", required=True, type=Path)
    eval_execution_parser.add_argument("--eval-cases", type=Path)

    eval_review_parser = subparsers.add_parser(
        "prepare-eval-review-pack",
        help="Generate a checker-facing review pack from a prepared eval run.",
    )
    eval_review_parser.add_argument("--eval-cases", required=True, type=Path)
    eval_review_parser.add_argument("--eval-run-dir", required=True, type=Path)

    record_eval_parser = subparsers.add_parser(
        "record-eval-output",
        help="Write one raw Agent output and update the matching eval run-log row.",
    )
    record_eval_parser.add_argument("--eval-run-dir", required=True, type=Path)
    record_eval_parser.add_argument("--task-id", required=True)
    record_eval_parser.add_argument("--group", required=True, choices=["baseline", "context_pack"])
    output_group = record_eval_parser.add_mutually_exclusive_group(required=True)
    output_group.add_argument("--output-text")
    output_group.add_argument("--output-file", type=Path)
    record_eval_parser.add_argument("--agent", required=True)
    record_eval_parser.add_argument("--model", required=True)
    record_eval_parser.add_argument("--token-input")
    record_eval_parser.add_argument("--token-output")
    record_eval_parser.add_argument("--elapsed-minutes")
    record_eval_parser.add_argument("--notes")
    record_eval_parser.add_argument("--eval-cases", type=Path)
    record_eval_parser.add_argument(
        "--refresh-execution-pack",
        action="store_true",
        help="Regenerate real-agent-execution-plan.json and real-agent-execution-guide.md after recording.",
    )

    review_decision_parser = subparsers.add_parser(
        "record-eval-review-decision",
        help="Record a checker decision for one baseline vs Context Pack eval task.",
    )
    review_decision_parser.add_argument("--eval-run-dir", required=True, type=Path)
    review_decision_parser.add_argument("--task-id", required=True)
    review_decision_parser.add_argument("--checker", required=True)
    review_decision_parser.add_argument(
        "--baseline-answer-correct",
        required=True,
        choices=["yes", "partial", "no", "missing_output", "not_reviewed"],
    )
    review_decision_parser.add_argument(
        "--context-pack-answer-correct",
        required=True,
        choices=["yes", "partial", "no", "missing_output", "not_reviewed"],
    )
    review_decision_parser.add_argument(
        "--context-pack-retrieval-useful",
        required=True,
        choices=["yes", "partial", "no", "not_applicable"],
    )
    review_decision_parser.add_argument(
        "--winner",
        required=True,
        choices=["baseline", "context_pack", "tie", "none"],
    )
    review_decision_parser.add_argument("--baseline-human-fix-count", required=True)
    review_decision_parser.add_argument("--context-pack-human-fix-count", required=True)
    review_decision_parser.add_argument("--notes", default="")
    review_decision_parser.add_argument(
        "--eval-cases",
        type=Path,
        help="Refresh eval-review-pack.json/md after recording the decision.",
    )

    score_eval_parser = subparsers.add_parser(
        "score-eval-run",
        help="Score raw Agent outputs from a prepared baseline vs Context Pack eval run.",
    )
    score_eval_parser.add_argument("--eval-cases", required=True, type=Path)
    score_eval_parser.add_argument("--eval-run-dir", required=True, type=Path)
    score_eval_parser.add_argument(
        "--require-business-evidence",
        action="store_true",
        help="Fail if outputs are simulated, missing, unscored, or not paired baseline/context_pack evidence.",
    )

    readiness_parser = subparsers.add_parser(
        "check-eval-business-readiness",
        help="Check whether a scored and manually reviewed A/B eval run is usable as business evidence.",
    )
    readiness_parser.add_argument("--eval-cases", required=True, type=Path)
    readiness_parser.add_argument("--eval-run-dir", required=True, type=Path)
    readiness_parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Return a non-zero exit code if the eval run is not ready as business evidence.",
    )

    status_parser = subparsers.add_parser(
        "eval-run-status",
        help="Summarize current eval run outputs, scoring, review, and readiness state.",
    )
    status_parser.add_argument("--eval-cases", required=True, type=Path)
    status_parser.add_argument("--eval-run-dir", required=True, type=Path)

    dependency_parser = subparsers.add_parser(
        "dependency-check",
        help="Check local parser/OCR dependencies before ingesting documents.",
    )
    dependency_parser.add_argument("--output-dir", type=Path)

    watch_parser = subparsers.add_parser(
        "watch-repo",
        help="监听代码仓目录，文件变更后自动增量入库并重建检索索引。",
    )
    watch_parser.add_argument(
        "--watch-dir", required=True, type=Path,
        help="要监听的代码仓根目录（如 ClusterHMI）。",
    )
    watch_parser.add_argument(
        "--out-dir", required=True, type=Path,
        help="知识库产物输出目录（processed/）。",
    )
    watch_parser.add_argument("--project", default="ClusterHMI")
    watch_parser.add_argument("--owner", default="PATAC")
    watch_parser.add_argument("--fts-index-path", type=Path)
    watch_parser.add_argument("--vector-index-path", type=Path)
    watch_parser.add_argument(
        "--exclude-dir", action="append", default=[],
        help="排除的目录名（可多次指定）。默认排除 KanziEngine/someip/ClusterHMIPrebuilts。",
    )
    watch_parser.add_argument(
        "--debounce-seconds", type=float, default=3.0,
        help="防抖等待时间（秒），连续变更会被合并处理，默认 3 秒。",
    )
    watch_parser.add_argument(
        "--no-rebuild-indexes", action="store_true",
        help="入库后不自动重建检索索引。",
    )

    manifest_gen_parser = subparsers.add_parser(
        "generate-code-manifest",
        help="扫描代码仓目录，生成知识库接入清单 CSV。",
    )
    manifest_gen_parser.add_argument(
        "--repo-dir", required=True, type=Path,
        help="代码仓根目录（如 ClusterHMI）。",
    )
    manifest_gen_parser.add_argument(
        "--output", required=True, type=Path,
        help="输出 CSV 路径。",
    )
    manifest_gen_parser.add_argument(
        "--exclude-dir", action="append", default=[],
        help="排除的目录名（可多次指定）。",
    )
    manifest_gen_parser.add_argument(
        "--no-default-excludes", action="store_true",
        help="不使用默认排除列表。",
    )
    manifest_gen_parser.add_argument(
        "--snapshot-output", type=Path, default=None,
        metavar="DIR",
        help=(
            "（Phase A）若指定此目录，以 RepositorySnapshot + files.jsonl 格式输出，"
            "产物不含绝对路径。与 --output (CSV) 互斥，优先级高于 --output。"
        ),
    )

    contract_parser = subparsers.add_parser(
        "validate-processed",
        help="Validate processed Layer1 outputs against the Layer1 -> Layer2 contract.",
    )
    contract_parser.add_argument("--processed-dir", required=True, type=Path)
    contract_parser.add_argument("--output-dir", type=Path)
    contract_parser.add_argument("--json", action="store_true")
    contract_parser.add_argument(
        "--require-valid",
        action="store_true",
        help="Return a non-zero exit code when contract errors are found.",
    )

    mcp_parser = subparsers.add_parser(
        "serve-mcp",
        help="Run the MCP server for Claude Code / Claude Desktop integration.",
    )
    mcp_parser.add_argument(
        "--transport",
        default="streamable-http",
        choices=("stdio", "sse", "streamable-http"),
        help="MCP transport protocol (default: streamable-http).",
    )
    mcp_parser.add_argument("--host", default="127.0.0.1")
    mcp_parser.add_argument("--port", type=int, default=8788)
    mcp_parser.add_argument("--streamable-http-path", default="/mcp")
    mcp_parser.add_argument(
        "--code-processed-dir",
        type=Path,
        default=None,
        help=(
            "Path to the code repository processed/ dir. "
            "Activates search_code_repo and get_code_context_pack tools. "
            "Falls back to CLUSTER_CODE_PROCESSED_DIR env var if not set."
        ),
    )
    mcp_parser.add_argument(
        "--docs-processed-dir",
        type=Path,
        default=None,
        help=(
            "Path to the QNX documentation processed/ dir. "
            "Activates search_docs tool. "
            "Falls back to QNX_DOCS_PROCESSED_DIR env var if not set."
        ),
    )

    return parser


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--max-chunk-chars", type=int, default=1600)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--overlap-chars", type=int, default=160)


def _resolve_query_text(query: str | None, query_file: Path | None) -> str:
    if query is not None:
        return query
    if query_file is None:
        raise ValueError("Either query or query_file must be provided.")
    return query_file.read_text(encoding="utf-8-sig")


def _emit_text(text: str) -> None:
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.write(text.encode("ascii", errors="backslashreplace").decode("ascii"))
    if not text.endswith("\n"):
        sys.stdout.write("\n")


def _emit_json(payload: dict[str, object]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        fallback = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
        sys.stdout.write(fallback + "\n")


def _emit_validation_errors(errors: list[dict[str, object]]) -> None:
    for error in errors:
        print(
            f"VALIDATION ERROR [{error.get('code')}]: {error.get('message')} "
            f"({error.get('path')})",
            file=sys.stderr,
        )


def _build_metadata_filters_from_args(args: argparse.Namespace) -> dict[str, list[str]]:
    filters: dict[str, list[str]] = {}
    if getattr(args, "source_type", None):
        filters["source_type"] = list(args.source_type)
    if getattr(args, "project_filter", None):
        filters["project"] = list(args.project_filter)
    if getattr(args, "supplier", None):
        filters["supplier"] = list(args.supplier)
    if getattr(args, "document_version", None):
        filters["document_version"] = list(args.document_version)
    return filters


if __name__ == "__main__":
    raise SystemExit(main())
