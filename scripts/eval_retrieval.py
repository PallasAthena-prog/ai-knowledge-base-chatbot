"""Measure retrieval quality on the sample documents.

For every question in eval/questions.jsonl it checks whether a passage containing the expected
text is retrieved, and reports hit@1, hit@3 and the mean reciprocal rank (MRR).

Usage:
    python scripts/eval_retrieval.py                  # hybrid search, as configured in .env
    python scripts/eval_retrieval.py --keyword-only   # BM25 only, to compare

It builds a temporary knowledge base from samples/, so your own data is never touched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings, load_dotenv  # noqa: E402
from app.service import KnowledgeBase  # noqa: E402
from app.textproc import collapse_ws  # noqa: E402


def load_questions(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def first_hit(sources, expect: str) -> int | None:
    for rank, source in enumerate(sources, start=1):
        if expect in collapse_ws(source.text):
            return rank
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keyword-only", action="store_true", help="switch off semantic search")
    parser.add_argument("--top-k", type=int, default=5, help="passages to retrieve per question (default 5)")
    parser.add_argument("--questions", type=Path, default=ROOT / "eval" / "questions.jsonl")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    questions = load_questions(args.questions)
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, DATA_DIR=tmp, LLM_BASE_URL="")
        env.setdefault("EMBEDDING_CACHE_DIR", str(ROOT / "data" / "models"))
        if args.keyword_only:
            env["EMBEDDINGS"] = "off"
        kb = KnowledgeBase.create(Settings.from_env(env))
        kb.load_samples()
        print(f"Search mode: {kb.retriever.mode}, {kb.store.stats()['chunks']} passages, top {args.top_k}\n")

        hits1 = hits3 = 0
        reciprocal = 0.0
        for item in questions:
            sources = kb.retriever.search(item["question"], top_k=args.top_k)
            rank = first_hit(sources, item["expect"])
            if rank == 1:
                hits1 += 1
            if rank and rank <= 3:
                hits3 += 1
            reciprocal += 1 / rank if rank else 0.0
            mark = f"#{rank}" if rank else "miss"
            print(f"{mark:>5}  {item['question']}")

    n = len(questions)
    print(f"\nhit@1 {hits1 / n:.0%}   hit@3 {hits3 / n:.0%}   MRR {reciprocal / n:.2f}   ({n} questions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
