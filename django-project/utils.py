from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import arabic_reshaper
import numpy as np
import regex
from bidi.algorithm import get_display
from camel_tools.disambig.mle import MLEDisambiguator
from camel_tools.tagger.default import DefaultTagger
from sklearn.feature_extraction.text import TfidfVectorizer

BASE_DIR = Path(__file__).resolve().parent


@dataclass
class Config:
    db_path: str = str(BASE_DIR / "Data" / "Hadith")
    dbs: tuple[str, ...] = (
        "Bukhari.db",
        "Muslim.db",
        "AbuDaud.db",
        "Tirmizi.db",
        "Nesai.db",
        "IbnMaja.db",
    )
    table: str = "hadiths"
    id_col: str = "Hadith_number"
    text_col: str = "Arabic_Matn"
    normalized_col: str = "normalized"
    pos_col: str = "pos"
    hadith_txt: str = str(
        BASE_DIR / "Data" / "Sahihah" / "sahihah_hadith_extracted_in_sittah.txt"
    )
    pre_defined_stop_words: str = "path/to/pre"
    POS_WEIGHTS: dict[str, float] = field(
        default_factory=lambda: {
            "noun": 1.5,
            "noun_prop": 1.6,
            "noun_quant": 1.2,
            "verb": 1.3,
            "verb_pseudo": 0.9,
            "adj": 1.1,
            "adv": 0.9,
            "adv_rel": 0.7,
            "adv_interrog": 0.7,
            "interj": 0.6,
            "pron": 0.2,
            "pron_dem": 0.3,
            "pron_rel": 0.3,
            "prep": 0.2,
            "conj": 0.2,
            "conj_sub": 0.2,
            "part": 0.2,
            "part_verb": 0.2,
            "part_neg": 0.25,
            "part_focus": 0.25,
            "part_interrog": 0.25,
            "part_voc": 0.15,
            "abbrev": 0.4,
        }
    )


config = Config()

cand_txt: dict[str, list[int]] = defaultdict(list)
cand_meta: dict[str, dict[str, Any]] = {}


def _ensure_cached_columns(conn: sqlite3.Connection, cfg: Config) -> None:
    cur = conn.cursor()
    cols = {row[1] for row in cur.execute(f"PRAGMA table_info({cfg.table})").fetchall()}
    if cfg.normalized_col not in cols:
        cur.execute(f"ALTER TABLE {cfg.table} ADD COLUMN {cfg.normalized_col} TEXT")
    if cfg.pos_col not in cols:
        cur.execute(f"ALTER TABLE {cfg.table} ADD COLUMN {cfg.pos_col} TEXT")
    conn.commit()


def _backfill_cache_columns(
    conn: sqlite3.Connection,
    cfg: Config,
    *,
    norm_fn,
    tag_pos_tokens_fn,
) -> None:
    def _is_json_pos_array(value: str) -> bool:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return False
        return isinstance(parsed, list)

    cur = conn.cursor()
    rows = cur.execute(
        f"""
        SELECT rowid, {cfg.text_col}, {cfg.normalized_col}, {cfg.pos_col}
        FROM {cfg.table}
        """
    ).fetchall()

    for rowid, raw_text, normalized_cached, pos_cached in rows:
        text = raw_text or ""
        normalized_value = normalized_cached
        if not normalized_value:
            normalized_value = norm_fn(text)
            cur.execute(
                f"""
                UPDATE {cfg.table}
                SET {cfg.normalized_col}=?
                WHERE rowid=?
                """,
                (normalized_value, rowid),
            )
        if not pos_cached or not _is_json_pos_array(pos_cached):
            pos_tags = tag_pos_tokens_fn(normalized_value.split())
            cur.execute(
                f"""
                UPDATE {cfg.table}
                SET {cfg.pos_col}=?
                WHERE rowid=?
                """,
                (json.dumps(pos_tags, ensure_ascii=False), rowid),
            )
    conn.commit()


class Utils:
    _mled: Optional[MLEDisambiguator] = None
    _tagger: Optional[DefaultTagger] = None
    RX_PREFIX_STANDALONE = regex.compile(
        r"(?<!\S)(و|ف|ب|ك|ل|س)\s+(?=\S)", regex.UNICODE
    )
    TAG_RE = re.compile(r"<[^>]+>")
    ARABIC_DIACRITICS = regex.compile(
        r"[\p{M}\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]+"
    )
    TATWEEL = "\u0640"
    NON_ARABIC = regex.compile(r"[^\p{Arabic} ]+")
    MULTI_SPACE = regex.compile(r"\s+")

    @staticmethod
    def normalize_arabic(text: str) -> str:
        if not text:
            return ""
        text = unicodedata.normalize("NFKD", text)
        text = Utils.ARABIC_DIACRITICS.sub("", text)
        text = text.replace(Utils.TATWEEL, "")
        text = text.translate(
            str.maketrans(
                {
                    "آ": "ا",
                    "ٱ": "ا",
                    "ى": "ي",
                    "ئ": "ي",
                    "ؤ": "و",
                    "ة": "ه",
                    "ء": "",
                    "گ": "ك",
                    "ڤ": "ف",
                    "پ": "ب",
                    "چ": "ج",
                }
            )
        )
        text = Utils.NON_ARABIC.sub(" ", text)
        text = Utils.MULTI_SPACE.sub(" ", text).strip()
        text = Utils.RX_PREFIX_STANDALONE.sub(r"\1", text)
        return unicodedata.normalize("NFKC", text)

    @staticmethod
    def normalize(text: str | None) -> list[str]:
        text = text or ""
        text = Utils.TAG_RE.sub(" ", text)
        text = " ".join(text.split())
        text = Utils.normalize_arabic(text)
        return text.split(" ") if text else []

    @staticmethod
    def norm(text: str | None) -> str:
        return " ".join(Utils.normalize(text))

    @staticmethod
    def ar(text: str) -> str:
        return get_display(arabic_reshaper.reshape(text))

    @classmethod
    def _get_pos_tagger(utils_class) -> DefaultTagger:
        if utils_class._tagger is None:
            utils_class._mled = MLEDisambiguator.pretrained()
            utils_class._tagger = DefaultTagger(utils_class._mled, "pos")
        return utils_class._tagger

    @classmethod
    def tag_pos_tokens(utils_class, tokens: list[str]) -> list[str]:
        if not tokens:
            return []
        tagger = utils_class._get_pos_tagger()
        return list(tagger.tag(tokens))

    @classmethod
    def tag_pos_text(utils_class, text: str) -> list[str]:
        return utils_class.tag_pos_tokens(Utils.norm(text).split())

    @staticmethod
    def get_txt_from_db(current_db: str, config: Config = config):
        conn = sqlite3.connect(config.db_path + f"/{current_db}")
        try:
            _ensure_cached_columns(conn, cfg=config)
            _backfill_cache_columns(
                conn,
                cfg=config,
                norm_fn=Utils.norm,
                tag_pos_tokens_fn=Utils.tag_pos_tokens,
            )
        finally:
            conn.close()

        conn = sqlite3.connect(config.db_path + f"/{current_db}")
        try:
            cur = conn.cursor()
            rows = cur.execute(
                f"""
                SELECT
                    {config.text_col},
                    {config.id_col},
                    {config.normalized_col},
                    {config.pos_col}
                FROM {config.table}
                """
            ).fetchall()
            return rows
        finally:
            conn.close()

    @staticmethod
    def get_cand_txt():
        global cand_txt
        global cand_meta
        cand_txt = defaultdict(list)

        with open(config.hadith_txt, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            cand_txt[line].append(i)

        cand_meta = {}
        for line in cand_txt.keys():
            normalized_value = Utils.norm(line)
            cand_meta[line] = {
                "normalized": normalized_value,
                "pos": Utils.tag_pos_tokens(normalized_value.split()),
            }
        return cand_txt, cand_meta

    @staticmethod
    def char_idx_to_token_idx(tokens: str, char_idx: list[int]):
        indexes: list[int] = []
        lengths: list[int] = []
        for idx in char_idx:
            pos = 0
            for i, token in enumerate(tokens.split()):
                pos += len(token) + 1
                if idx < pos:
                    indexes.append(i)
                    lengths.append(len(token))
                    break
        return tuple(indexes), tuple(lengths)


utils = Utils()


def _dynamic_max_df(corpus: Iterable[str]) -> float:
    docs = [utils.norm(doc).split() for doc in corpus if str(doc).strip()]
    if not docs:
        return 1.0
    doc_count = len(docs)
    df_counter = Counter()
    for tokens in docs:
        df_counter.update(set(tokens))
    if not df_counter:
        return 1.0
    ratios = np.array([count / float(doc_count) for count in df_counter.values()])
    p95 = float(np.percentile(ratios, 95))
    return min(0.99, max(0.01, p95))


def vec(corpus, stop_words=None, max_df=None, return_vectorizer=False):
    if max_df is None:
        max_df = _dynamic_max_df(corpus)
    fitted_vec = TfidfVectorizer(
        preprocessor=utils.norm, stop_words=stop_words, max_df=max_df
    )
    tfidf_matrix = fitted_vec.fit_transform(corpus)
    if return_vectorizer:
        return tfidf_matrix, fitted_vec
    return tfidf_matrix


class StopWords:
    pos_wheights = config.POS_WEIGHTS

    @staticmethod
    def stop_words(corpus: Optional[Iterable[str]] = None):
        docs = [str(doc) for doc in (corpus if corpus is not None else cand_meta.keys())]
        docs = [doc for doc in docs if doc.strip()]
        if not docs:
            raise ValueError("No documents available to compute stop words.")

        tfidf_matrix, fitted_vec = vec(
            docs,
            stop_words=None,
            max_df=_dynamic_max_df(docs),
            return_vectorizer=True,
        )
        vocab_indices = list(fitted_vec.vocabulary_.values())
        ratios = np.array(
            [(tfidf_matrix[:, idx] > 0).sum() / len(docs) for idx in vocab_indices]
        )
        p95 = np.percentile(ratios, 95)
        words = list(fitted_vec.vocabulary_.keys())

        def words_above(threshold):
            return [words[i] for i, r in enumerate(ratios) if r > threshold]

        tags = Utils.tag_pos_tokens(words_above(p95))
        tag_count = Counter(tags)
        return {
            "hint": "p95 ist die dynamische Schwelle fuer sehr haeufige Woerter; "
            "words_above_p95 zeigt potenzielles Rauschen; "
            "tag_count zeigt die POS-Verteilung dieser haeufigen Woerter zur Plausibilisierung.",
            "p95": float(p95),
            "words_above_p95": words_above(p95),
            "stop_words": words_above(p95),
            "stop_word_weight": 0.25,
            "tag_count": dict(tag_count),
        }
