from __future__ import annotations

from pathlib import Path

from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.quality_baseline import build_quality_baseline
from agent_knowledge_hub.release_manifest import (
    ReleaseManifest,
    create_candidate_release,
    finalize_release,
    validate_bound_release,
)
from agent_knowledge_hub.utils import write_json
from agent_knowledge_hub.vector_index import build_vector_index


def build_release_bundle(
    processed_dir: Path | str,
    releases_dir: Path | str,
) -> ReleaseManifest:
    processed_root = Path(processed_dir)
    releases_root = Path(releases_dir)
    candidate = create_candidate_release(processed_root, releases_root)
    if candidate.status == "ready":
        validate_bound_release(candidate)
        return candidate

    release_dir = candidate.manifest_path.parent
    fts_path = release_dir / "indexes" / "chunks.fts.sqlite"
    vector_path = release_dir / "indexes" / "chunks.vector.json"
    baseline_path = release_dir / "quality-baseline.json"

    build_fts_index(
        processed_dir=processed_root,
        index_path=fts_path,
        release_manifest_path=candidate.manifest_path,
    )
    build_vector_index(
        processed_dir=processed_root,
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
