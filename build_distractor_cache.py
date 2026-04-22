#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from quiz.db_config import VERSES_TABLE, VERSE_INDEX, VERSE_TEXT_AR

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "quran.db"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "quiz" / "cache" / "distractor_cache.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Precompute QuranQuiz distractors once using seqMatcherTool/utils and "
            "write a local cache file used directly by the app."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to quran.db.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Path to the app-readable distractor cache JSON.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=16,
        help="How many distractors to keep per verse for the app cache.",
    )
    parser.add_argument(
        "--fetch-k",
        type=int,
        default=32,
        help="How many overlap-ranked refs to rerank via seqMatcher per candidate verse.",
    )
    return parser


def load_verse_rows(db_path: Path) -> list[tuple[int, str]]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            f"""
            SELECT {VERSE_INDEX}, {VERSE_TEXT_AR}
            FROM {VERSES_TABLE}
            WHERE {VERSE_TEXT_AR} IS NOT NULL
              AND TRIM({VERSE_TEXT_AR}) != ''
            ORDER BY {VERSE_INDEX}
            """
        )
        return [(int(row[0]), str(row[1])) for row in cursor.fetchall()]
    finally:
        conn.close()


def _get_seqmatcher_runtime():
    from seqMatcherTool import f1
    from utils import utils

    def normalize(text: str) -> str:
        return utils.norm(text)

    def score(reference: str, candidate: str) -> float:
        result = f1(reference=reference, candidate=candidate, wheights=[0.7, 0.3], max_order=2)
        return float(result["f1"])

    return normalize, score


def build_seqmatcher_distractor_map(
    rows: list[tuple[int, str]],
    *,
    top_k: int,
    fetch_k: int,
    normalize_fn=None,
    score_fn=None,
) -> tuple[dict[int, list[int]], int]:
    if normalize_fn is None or score_fn is None:
        normalize_fn, score_fn = _get_seqmatcher_runtime()

    normalized_rows: list[tuple[int, str]] = []
    for verse_id, text in rows:
        normalized = normalize_fn(text or "")
        if normalized:
            normalized_rows.append((int(verse_id), normalized))

    if not normalized_rows:
        return {}, 0

    token_counters: dict[int, Counter[str]] = {}
    token_totals: dict[int, int] = {}
    postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
    normalized_by_id: dict[int, str] = {}

    for verse_id, normalized_text in normalized_rows:
        counts = Counter(normalized_text.split())
        token_counters[verse_id] = counts
        token_totals[verse_id] = sum(counts.values())
        normalized_by_id[verse_id] = normalized_text
        for token, count in counts.items():
            postings[token].append((verse_id, count))

    all_ids = [verse_id for verse_id, _ in normalized_rows]
    distractor_map: dict[int, list[int]] = {}
    reranked_total = 0

    for verse_id, counts in token_counters.items():
        common_by_candidate: dict[int, int] = defaultdict(int)
        for token, own_count in counts.items():
            for other_id, other_count in postings[token]:
                if other_id == verse_id:
                    continue
                common_by_candidate[other_id] += min(own_count, other_count)

        overlap_scored: list[tuple[float, int]] = []
        own_total = token_totals[verse_id]
        for other_id, common in common_by_candidate.items():
            if common <= 0:
                continue
            score = (2.0 * common) / (own_total + token_totals[other_id])
            if score > 0.0:
                overlap_scored.append((score, other_id))

        overlap_scored.sort(key=lambda item: (-item[0], item[1]))
        shortlist = [other_id for _, other_id in overlap_scored[: max(top_k, fetch_k)]]
        if len(shortlist) < top_k:
            for other_id in all_ids:
                if other_id == verse_id or other_id in shortlist:
                    continue
                shortlist.append(other_id)
                if len(shortlist) >= top_k:
                    break

        reranked: list[tuple[float, int]] = []
        reference = normalized_by_id[verse_id]
        seen_texts: set[str] = set()
        for other_id in shortlist:
            candidate = normalized_by_id.get(other_id)
            if not candidate:
                continue
            if candidate == reference:
                continue
            if candidate in seen_texts:
                continue
            seen_texts.add(candidate)
            score = score_fn(reference, candidate)
            reranked.append((float(score), int(other_id)))

        reranked_total += len(reranked)
        reranked.sort(key=lambda item: (-item[0], item[1]))
        distractor_map[verse_id] = [other_id for _, other_id in reranked[:top_k]]

    return distractor_map, reranked_total


def build_cache_payload(
    rows: list[tuple[int, str]],
    top_k: int,
    fetch_k: int,
    normalize_fn=None,
    score_fn=None,
) -> dict[str, Any]:
    distractor_map, reranked_total = build_seqmatcher_distractor_map(
        rows=rows,
        top_k=top_k,
        fetch_k=fetch_k,
        normalize_fn=normalize_fn,
        score_fn=score_fn,
    )
    distractors: dict[str, list[int]] = {}
    for source_id, hits in distractor_map.items():
        distractors[str(int(source_id))] = [int(hit) for hit in hits[:top_k]]

    return {
        "meta": {
            "source_db": {"path": str(DEFAULT_DB_PATH.name), "rows": len(rows)},
            "top_k": top_k,
            "entries": len(distractors),
            "fetch_k": fetch_k,
            "algorithm": "seqMatcherTool.f1 + utils.norm",
            "reranked_pairs": reranked_total,
        },
        "distractors": distractors,
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        verse_rows = load_verse_rows(Path(args.db))
        cache_payload = build_cache_payload(
            verse_rows,
            top_k=args.top_k,
            fetch_k=args.fetch_k,
        )

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(cache_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(
            json.dumps(
                {
                    "written": str(output_path),
                    "entries": cache_payload["meta"]["entries"],
                    "top_k": cache_payload["meta"]["top_k"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
