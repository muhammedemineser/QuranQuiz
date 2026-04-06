import json
import os
import sqlite3
from pathlib import Path
from functools import lru_cache
from .db_config import *

DB_PATH = Path(__file__).resolve().parent.parent / "quran.db"
DISTRACTOR_CACHE_SIZE = 16
PRECOMPUTED_DISTRACTOR_CACHE_PATH = Path(
    os.environ.get(
        "QURAN_DISTRACTOR_CACHE",
        Path(__file__).resolve().parent / ".cache" / "distractor_cache.json",
    )
)


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@lru_cache(maxsize=1)
def _load_precomputed_distractor_cache() -> dict[int, tuple[int, ...]]:
    if not PRECOMPUTED_DISTRACTOR_CACHE_PATH.exists():
        return {}

    payload = json.loads(PRECOMPUTED_DISTRACTOR_CACHE_PATH.read_text(encoding="utf-8"))
    entries = payload.get("distractors", {})
    return {
        int(source_id): tuple(int(value) for value in distractor_ids)
        for source_id, distractor_ids in entries.items()
    }


def get_chapters():
    with _conn() as conn:
        return conn.execute(
            f"""SELECT
                    {CHAPTER_NUMBER} AS chapter_number,
                    {CHAPTER_NAME} AS chapter_name
                FROM {CHAPTERS_TABLE}
                ORDER BY {CHAPTER_NUMBER}"""
        ).fetchall()


def get_verses(surah_number: int):
    with _conn() as conn:
        return conn.execute(
            f"""SELECT
                    {VERSE_NUMBER},
                    {VERSE_NUMBER} AS verse_number,
                    {VERSE_INDEX},
                    {VERSE_INDEX} AS verse_index,
                    {VERSE_TEXT_AR},
                    {VERSE_TEXT_AR} AS text_ar,
                    {VERSE_TEXT_EN},
                    {VERSE_TEXT_EN} AS text_en
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


@lru_cache(maxsize=2048)
def _cached_distractor_ids(correct_verse_index: int) -> tuple[int, ...]:
    precomputed = _load_precomputed_distractor_cache().get(correct_verse_index)
    if precomputed:
        return precomputed[:DISTRACTOR_CACHE_SIZE]
    return ()


def get_distractors(correct_verse_index: int, n: int = 3):
    """Return n distractor verses using precomputed cache per verse ID."""
    verse_ids = _cached_distractor_ids(correct_verse_index)[:n]
    return [
        verse
        for verse_id in verse_ids
        if (verse := get_verse_by_index(verse_id)) is not None
    ]
