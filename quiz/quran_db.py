import json
import os
import sqlite3
import math
import subprocess
from pathlib import Path
from collections import Counter
from functools import lru_cache
from .db_config import *

DB_PATH = Path(__file__).resolve().parent.parent / "quran.db"
SEARCH_ENGINE_SCRIPT = (
    Path(__file__).resolve().parents[2] / "classify" / "search-engine" / "arabic_db_search.py"
)
SEARCH_ENGINE_PYTHON = os.environ.get("QURAN_SEARCH_PYTHON", "python3")
DISTRACTOR_CACHE_SIZE = 16


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_chapters():
    with _conn() as conn:
        return conn.execute(
            f"SELECT {CHAPTER_NUMBER}, {CHAPTER_NAME} FROM {CHAPTERS_TABLE} ORDER BY {CHAPTER_NUMBER}"
        ).fetchall()


def get_verses(surah_number: int):
    with _conn() as conn:
        return conn.execute(
            f"""SELECT {VERSE_NUMBER}, {VERSE_INDEX}, {VERSE_TEXT_AR}, {VERSE_TEXT_EN}
                FROM {VERSES_TABLE}
                WHERE {VERSE_SURAH_NUMBER} = ?
                ORDER BY {VERSE_NUMBER}""",
            (surah_number,),
        ).fetchall()


def get_verse_by_index(verse_index: int):
    with _conn() as conn:
        return conn.execute(
            f"""SELECT {VERSE_SURAH_NUMBER}, {VERSE_NUMBER}, {VERSE_INDEX}, {VERSE_TEXT_AR}, {VERSE_TEXT_EN}
                FROM {VERSES_TABLE} WHERE {VERSE_INDEX} = ?""",
            (verse_index,),
        ).fetchone()


def _f1_score(ref: str, hyp: str) -> float:
    ref_counts = Counter(ref.split())
    hyp_counts = Counter(hyp.split())
    common = sum((ref_counts & hyp_counts).values())
    if common == 0:
        return 0.0
    precision = common / sum(hyp_counts.values())
    recall = common / sum(ref_counts.values())
    return 2 * precision * recall / (precision + recall)


def _search_distractor_ids(correct_verse_index: int, target_text: str) -> list[int]:
    completed = subprocess.run(
        [
            SEARCH_ENGINE_PYTHON,
            str(SEARCH_ENGINE_SCRIPT),
            "--single",
            target_text,
            "--top-k",
            str(DISTRACTOR_CACHE_SIZE),
            "--exclude-source-id",
            str(correct_verse_index),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    ranked_hits = sorted(
        payload.get("matches", []),
        key=lambda hit: float(hit.get("score") or 0.0),
        reverse=True,
    )
    distractor_ids = []
    seen = set()
    for hit in ranked_hits:
        source_id = int(hit.get("source_id"))
        if source_id in seen:
            continue
        seen.add(source_id)
        distractor_ids.append(source_id)
        if len(distractor_ids) >= DISTRACTOR_CACHE_SIZE:
            break
    return distractor_ids


def _fallback_distractor_ids(correct_verse_index: int, target_text: str) -> list[int]:
    with _conn() as conn:
        candidates = conn.execute(
            f"""SELECT {VERSE_INDEX}, {VERSE_TEXT_AR}
                FROM {VERSES_TABLE}
                WHERE {VERSE_INDEX} != ?
                AND {VERSE_TEXT_AR} IS NOT NULL
                AND TRIM({VERSE_TEXT_AR}) != ''""",
            (correct_verse_index,),
        ).fetchall()

    scored = sorted(
        candidates,
        key=lambda r: _f1_score(target_text, r[VERSE_TEXT_AR]),
        reverse=True,
    )
    return [int(r[VERSE_INDEX]) for r in scored[:DISTRACTOR_CACHE_SIZE]]


@lru_cache(maxsize=2048)
def _cached_distractor_ids(correct_verse_index: int) -> tuple[int, ...]:
    target = get_verse_by_index(correct_verse_index)
    if not target:
        return ()
    target_text = target[VERSE_TEXT_AR]

    try:
        distractor_ids = _search_distractor_ids(correct_verse_index, target_text)
        if distractor_ids:
            return tuple(distractor_ids)
    except (subprocess.SubprocessError, json.JSONDecodeError, ValueError, TypeError):
        pass
    return tuple(_fallback_distractor_ids(correct_verse_index, target_text))


def get_distractors(correct_verse_index: int, n: int = 3):
    """Return n distractor verses using cached search-engine results per verse ID."""
    verse_ids = _cached_distractor_ids(correct_verse_index)[:n]
    return [verse for verse_id in verse_ids if (verse := get_verse_by_index(verse_id)) is not None]
