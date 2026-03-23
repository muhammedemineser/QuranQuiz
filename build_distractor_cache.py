#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from quiz.db_config import VERSES_TABLE, VERSE_INDEX, VERSE_TEXT_AR

PROJECT_ROOT = Path(__file__).resolve().parent
SEARCH_ENGINE_SCRIPT = PROJECT_ROOT / "search-engine" / "arabic_db_search.py"
DEFAULT_DB_PATH = PROJECT_ROOT / "quran.db"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "quiz" / ".cache" / "distractor_cache.json"
DEFAULT_SEARCH_OUTPUT_PATH = PROJECT_ROOT / "search-engine" / ".cache" / "quran_distractor_matches.json"
DEFAULT_SEARCH_CACHE_DIR = PROJECT_ROOT / "search-engine" / ".cache" / "arabic-meili"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Precompute QuranQuiz distractors by running arabic_db_search.py once "
            "over the complete quran.db and writing a local cache file for the app."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to quran.db.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Path to the app-readable distractor cache JSON.",
    )
    parser.add_argument(
        "--search-output",
        default=str(DEFAULT_SEARCH_OUTPUT_PATH),
        help="Path to the raw db-vs-db search output JSON.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_SEARCH_CACHE_DIR),
        help="Shared cache directory for search-engine preprocessing artifacts.",
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
        help="How many search hits to request before filtering self-matches.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size passed through to arabic_db_search.py.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable or "python3",
        help="Python executable used to invoke arabic_db_search.py.",
    )
    parser.add_argument(
        "--meili-url",
        default="http://127.0.0.1:7700",
        help="URL of the temporary/local Meilisearch instance used for warmup.",
    )
    parser.add_argument(
        "--meili-key",
        default=None,
        help="Optional Meilisearch API key. Defaults to arabic_db_search.py's built-in search key.",
    )
    parser.add_argument(
        "--keep-search-output",
        action="store_true",
        help="Keep the intermediate raw search output JSON after the app cache has been built.",
    )
    return parser


def run_search(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db)
    search_output = Path(args.search_output)
    search_output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        args.python,
        str(SEARCH_ENGINE_SCRIPT),
        "--cand",
        str(db_path),
        "--cand-table",
        VERSES_TABLE,
        "--cand-col",
        VERSE_TEXT_AR,
        "--cand-id-col",
        VERSE_INDEX,
        "--ref",
        str(db_path),
        "--ref-table",
        VERSES_TABLE,
        "--ref-col",
        VERSE_TEXT_AR,
        "--ref-id-col",
        VERSE_INDEX,
        "--top-k",
        str(args.fetch_k),
        "--batch-size",
        str(args.batch_size),
        "--cache-dir",
        str(args.cache_dir),
        "--output",
        str(search_output),
        "--meili-url",
        args.meili_url,
    ]
    if args.meili_key:
        command.extend(["--meili-key", args.meili_key])

    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "search run failed")

    return json.loads(search_output.read_text(encoding="utf-8"))


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


def build_f1_fallback_map(rows: list[tuple[int, str]], top_k: int) -> dict[int, list[int]]:
    token_counters: dict[int, Counter[str]] = {}
    token_totals: dict[int, int] = {}
    postings: dict[str, list[tuple[int, int]]] = defaultdict(list)

    for verse_id, text in rows:
        counts = Counter(text.split())
        token_counters[verse_id] = counts
        token_totals[verse_id] = sum(counts.values())
        for token, count in counts.items():
            postings[token].append((verse_id, count))

    fallback_map: dict[int, list[int]] = {}
    for verse_id, counts in token_counters.items():
        common_by_candidate: dict[int, int] = defaultdict(int)
        for token, own_count in counts.items():
            for other_id, other_count in postings[token]:
                if other_id == verse_id:
                    continue
                common_by_candidate[other_id] += min(own_count, other_count)

        scored: list[tuple[float, int]] = []
        own_total = token_totals[verse_id]
        for other_id, common in common_by_candidate.items():
            if common <= 0:
                continue
            score = (2.0 * common) / (own_total + token_totals[other_id])
            if score > 0.0:
                scored.append((score, other_id))

        scored.sort(key=lambda item: (-item[0], item[1]))
        fallback_map[verse_id] = [other_id for _, other_id in scored[:top_k]]

    return fallback_map


def build_cache_payload(
    search_payload: dict[str, Any],
    top_k: int,
    fallback_map: dict[int, list[int]],
) -> dict[str, Any]:
    distractors: dict[str, list[int]] = {}
    fallback_used = 0
    for result in search_payload.get("results", []):
        candidate = result.get("candidate", {})
        source_id = candidate.get("source_id")
        normalized_text = candidate.get("normalized_text")
        if source_id is None:
            continue
        source_id = int(source_id)

        chosen_hits: list[int] = []
        seen: set[int] = set()
        for match_group in result.get("matches", []):
            for hit in match_group.get("hits", []):
                hit_source_id = hit.get("source_id")
                if hit_source_id is None:
                    continue
                hit_source_id = int(hit_source_id)
                if hit_source_id == int(source_id):
                    continue
                if hit.get("normalized_text") == normalized_text:
                    continue
                if hit_source_id in seen:
                    continue
                seen.add(hit_source_id)
                chosen_hits.append(hit_source_id)
                if len(chosen_hits) >= top_k:
                    break
            if len(chosen_hits) >= top_k:
                break

        fallback_applied = False
        if len(chosen_hits) < top_k:
            for fallback_id in fallback_map.get(source_id, []):
                if fallback_id == source_id or fallback_id in seen:
                    continue
                seen.add(fallback_id)
                chosen_hits.append(fallback_id)
                fallback_applied = True
                if len(chosen_hits) >= top_k:
                    break

        if fallback_applied:
            fallback_used += 1

        distractors[str(source_id)] = chosen_hits[:top_k]

    return {
        "meta": {
            "source_db": search_payload.get("run", {}).get("reference_rows", {}),
            "top_k": top_k,
            "entries": len(distractors),
            "fallback_used": fallback_used,
        },
        "distractors": distractors,
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        search_payload = run_search(args)
        verse_rows = load_verse_rows(Path(args.db))
        fallback_map = build_f1_fallback_map(verse_rows, top_k=args.top_k)
        cache_payload = build_cache_payload(
            search_payload,
            top_k=args.top_k,
            fallback_map=fallback_map,
        )

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(cache_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if not args.keep_search_output:
            search_output = Path(args.search_output)
            if search_output.exists():
                search_output.unlink()

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
