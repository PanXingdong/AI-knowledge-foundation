from pathlib import Path

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.retrieval import build_context_pack_for_processed_dir


def test_inventory_query_promotes_overview_section(tmp_path: Path):
    processed_root = tmp_path / "processed"

    registers = tmp_path / "registers.md"
    registers.write_text(
        "# Register Details\n\n"
        "The control register bit fields configure clock dividers and reset lines. "
        "Each register holds configuration values for the peripheral block.",
        encoding="utf-8",
    )
    overview = tmp_path / "overview.md"
    overview.write_text(
        "# Architecture Overview\n\n"
        "The platform components include the application processor, the safety island, "
        "the audio DSP, and the video subsystem. These modules form the overall architecture.",
        encoding="utf-8",
    )

    for source, title in ((registers, "Register Manual"), (overview, "Overview Manual")):
        ingest_file(
            file_path=source,
            out_dir=processed_root,
            title=title,
            source_type="manual",
            owner="qa",
            project="demo",
            supplier="demo",
            document_version="v1",
        )

    result = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="这个平台包含哪些组件，整体架构是怎样的",
        task_type="general_query",
        top_k=4,
        per_document_limit=4,
    )

    assert result.selected_chunks
    titles = [" ".join(chunk.section_titles) for chunk in result.selected_chunks]
    # The overview/architecture section should rank ahead of register details.
    overview_index = next((i for i, t in enumerate(titles) if "Overview" in t), None)
    detail_index = next((i for i, t in enumerate(titles) if "Register" in t), None)
    assert overview_index is not None
    if detail_index is not None:
        assert overview_index < detail_index
