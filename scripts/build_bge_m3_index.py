from __future__ import annotations

import argparse
import time
from pathlib import Path

from agent_knowledge_hub.vector_index import build_bge_m3_vector_index_resumable


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a resumable BGE-M3 dense vector index.")
    parser.add_argument("--processed-dir", default="_qnx_processed")
    parser.add_argument("--index-path", default="_qnx_bge_m3_index.npz")
    parser.add_argument("--model-path", default="models/bge-m3")
    parser.add_argument("--work-dir", default="_qnx_bge_m3_index.parts")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=512)
    args = parser.parse_args()

    started = time.time()
    last_report = started

    def progress(done: int, total: int, skipped: bool) -> None:
        nonlocal last_report
        now = time.time()
        if skipped and now - last_report < 15 and done < total:
            return
        elapsed = now - started
        rate = done / elapsed if elapsed > 0 else 0.0
        remaining = (total - done) / rate if rate > 0 else 0.0
        status = "skip" if skipped else "done"
        print(
            f"[{status}] {done}/{total} chunks | "
            f"elapsed={elapsed/60:.1f}m | eta={remaining/60:.1f}m | rate={rate:.2f}/s",
            flush=True,
        )
        last_report = now

    summary = build_bge_m3_vector_index_resumable(
        processed_dir=Path(args.processed_dir),
        index_path=Path(args.index_path),
        model_path=Path(args.model_path),
        batch_size=args.batch_size,
        max_length=args.max_length,
        work_dir=Path(args.work_dir),
        progress_callback=progress,
    )
    print(summary.to_dict(), flush=True)
    print(f"finished in {(time.time() - started) / 60:.1f}m", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
