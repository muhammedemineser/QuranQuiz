#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import regex
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = SCRIPT_DIR / ".cache" / "arabic-meili"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "arabic_matches.json"
DEFAULT_QURAN_DB_PATH = SCRIPT_DIR.parent.parent / "QuranQuizz" / "quran.db"
DEFAULT_MEILI_SEARCH_KEY = "R-7tY1HRppmDgdXvbH3c8ZXVbckFOVd68D8aHgTX6Mk"


DEFAULT_CONFIG: dict[str, Any] = {
    "meili_settings": {
        "rankingRules": [
            "words",
            "exactness",
            "attribute",
            "proximity",
            "typo",
            "sort",
        ],
        "searchableAttributes": [
            "exact_text",
            "normalized_text",
            "lemma_text",
            "stem_text",
            "edge_ngrams",
            "char_ngrams",
            "root_text",
        ],
        "displayedAttributes": [
            "doc_id",
            "source_db",
            "source_table",
            "source_id",
            "raw_text",
            "exact_text",
            "normalized_text",
            "lemma_text",
            "stem_text",
            "root_text",
            "pos",
        ],
        "filterableAttributes": ["source_db", "source_table"],
        "sortableAttributes": ["token_count"],
        "typoTolerance": {
            "enabled": True,
            "disableOnAttributes": [
                "exact_text",
                "normalized_text",
                "lemma_text",
                "stem_text",
            ],
            "minWordSizeForTypos": {"oneTypo": 6, "twoTypos": 12},
        },
        "prefixSearch": "indexingTime",
    },
    "ngram": {
        "edge_min": 2,
        "edge_max": 5,
        "char_min": 3,
        "char_max": 5,
    },
    "search_variants": [
        {
            "name": "exact",
            "query_field": "normalized_text",
            "attributes": ["exact_text", "normalized_text"],
            "weight": 1.0,
        },
        {
            "name": "lemma",
            "query_field": "lemma_text",
            "attributes": ["lemma_text"],
            "weight": 0.8,
        },
        {
            "name": "stem",
            "query_field": "stem_text",
            "attributes": ["stem_text"],
            "weight": 0.65,
        },
        {
            "name": "edge",
            "query_field": "edge_query",
            "attributes": ["edge_ngrams"],
            "weight": 0.35,
        },
        {
            "name": "char",
            "query_field": "char_query",
            "attributes": ["char_ngrams"],
            "weight": 0.25,
        },
    ],
    "pos_weights": {
        "noun": 1.8,
        "noun_prop": 2.0,
        "noun_quant": 1.5,
        "verb": 1.6,
        "adj": 1.4,
        "adv": 1.0,
        "adv_rel": 0.7,
        "adv_interrog": 0.7,
        "part_neg": 1.2,
        "interj": 0.5,
        "verb_pseudo": 0.4,
        "part_focus": 0.4,
        "part_interrog": 0.3,
        "abbrev": 0.6,
        "pron": 0.1,
        "pron_dem": 0.2,
        "pron_rel": 0.2,
        "conj_sub": 0.2,
        "part_verb": 0.1,
        "part_voc": 0.1,
        "prep": 0.1,
        "conj": 0.1,
        "part": 0.1,
    },
    "rerank": {
        "exact_bonus": 5.0,
        "lemma_bonus": 2.0,
        "stem_bonus": 1.0,
        "pos_match_multiplier": 0.5,
    },
}

CACHE_VERSION = 3
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class DbSpec:
    path: str
    table: str
    col: str
    id_col: str = "rowid"
    label: str | None = None


@dataclass
class SearchVariant:
    name: str
    query_field: str
    attributes: list[str]
    weight: float


@dataclass
class PreparedText:
    raw_text: str
    normalized_text: str
    raw_tokens: list[str]
    normalized_tokens: list[str]
    lemmas: list[str]
    stems: list[str]
    roots: list[str]
    pos: list[str]
    edge_ngrams: list[str]
    char_ngrams: list[str]

    @property
    def exact_text(self) -> str:
        return self.normalized_text

    @property
    def lemma_text(self) -> str:
        return " ".join(self.lemmas)

    @property
    def stem_text(self) -> str:
        return " ".join(self.stems)

    @property
    def root_text(self) -> str:
        return " ".join(self.roots)

    @property
    def edge_query(self) -> str:
        return " ".join(self.edge_ngrams)

    @property
    def char_query(self) -> str:
        return " ".join(self.char_ngrams)

    def as_cache_dict(self) -> dict[str, Any]:
        return {
            "cache_version": CACHE_VERSION,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "raw_tokens": self.raw_tokens,
            "normalized_tokens": self.normalized_tokens,
            "lemmas": self.lemmas,
            "stems": self.stems,
            "roots": self.roots,
            "pos": self.pos,
            "edge_ngrams": self.edge_ngrams,
            "char_ngrams": self.char_ngrams,
        }

    @classmethod
    def from_cache_dict(cls, payload: dict[str, Any]) -> "PreparedText":
        return cls(
            raw_text=str(payload["raw_text"]),
            normalized_text=str(payload["normalized_text"]),
            raw_tokens=[str(value) for value in payload["raw_tokens"]],
            normalized_tokens=[str(value) for value in payload["normalized_tokens"]],
            lemmas=[str(value) for value in payload["lemmas"]],
            stems=[str(value) for value in payload["stems"]],
            roots=[str(value) for value in payload["roots"]],
            pos=[str(value) for value in payload["pos"]],
            edge_ngrams=[str(value) for value in payload["edge_ngrams"]],
            char_ngrams=[str(value) for value in payload["char_ngrams"]],
        )


class ArabicNormalizer:
    RX_PREFIX_STANDALONE = regex.compile(
        r"(?<!\S)(و|ف|ب|ك|ل|س)\s+(?=\S)", regex.UNICODE
    )
    TAG_RE = re.compile(r"<[^>]+>")
    ARABIC_DIACRITICS = regex.compile(
        r"[\p{M}\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]+"
    )
    TATWEEL = "\u0640"
    NON_ARABIC = regex.compile(r"[^\p{Arabic} ]+")
    NON_ARABIC_TOKEN = regex.compile(r"[^\p{Arabic}]+")
    MULTI_SPACE = regex.compile(r"\s+")

    @staticmethod
    def normalize_arabic(text: str) -> str:
        if not text:
            return ""
        text = unicodedata.normalize("NFKD", text)
        text = ArabicNormalizer.ARABIC_DIACRITICS.sub("", text)
        text = text.replace(ArabicNormalizer.TATWEEL, "")
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
        text = ArabicNormalizer.NON_ARABIC.sub(" ", text)
        text = ArabicNormalizer.MULTI_SPACE.sub(" ", text).strip()
        text = ArabicNormalizer.RX_PREFIX_STANDALONE.sub(r"\1", text)
        return unicodedata.normalize("NFKC", text)

    @staticmethod
    def normalize(text: str | None) -> list[str]:
        text = text or ""
        text = ArabicNormalizer.TAG_RE.sub(" ", text)
        text = " ".join(text.split())
        text = ArabicNormalizer.normalize_arabic(text)
        return text.split(" ") if text else []

    @staticmethod
    def norm(text: str | None) -> str:
        return " ".join(ArabicNormalizer.normalize(text))

    @staticmethod
    def preserve_raw_arabic_token(token: str) -> str:
        if not token:
            return ""
        token = unicodedata.normalize("NFC", token)
        token = ArabicNormalizer.NON_ARABIC_TOKEN.sub("", token)
        return token.strip()


class JsonCache:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {}
        self._dirty = False

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self._dirty = True

    def flush(self) -> None:
        if not self._dirty:
            return
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._dirty = False


class RunCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.prepared_cache = JsonCache(cache_dir / "prepared_cache.json")
        self.index_cache = JsonCache(cache_dir / "index_cache.json")

    def flush(self) -> None:
        self.prepared_cache.flush()
        self.index_cache.flush()

    @staticmethod
    def _hash_payload(payload: Any) -> str:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha1(serialized.encode("utf-8")).hexdigest()

    def dataset_signature(
        self,
        spec: DbSpec,
        rows: list[dict[str, str]],
        limit: int | None,
    ) -> str:
        payload = {
            "cache_version": CACHE_VERSION,
            "path": str(Path(spec.path).resolve()),
            "table": spec.table,
            "col": spec.col,
            "id_col": spec.id_col,
            "limit": limit,
            "rows": rows,
        }
        return self._hash_payload(payload)

    def config_signature(self, config: dict[str, Any]) -> str:
        return self._hash_payload({"cache_version": CACHE_VERSION, "config": config})

    def get_prepared(self, key: str) -> list[PreparedText] | None:
        payload = self.prepared_cache.get(key)
        if payload is None:
            return None
        return [PreparedText.from_cache_dict(item) for item in payload]

    def set_prepared(self, key: str, prepared_docs: list[PreparedText]) -> None:
        self.prepared_cache.set(
            key,
            [prepared.as_cache_dict() for prepared in prepared_docs],
        )

    def get_index_entry(self, key: str) -> dict[str, Any] | None:
        payload = self.index_cache.get(key)
        return payload if isinstance(payload, dict) else None

    def set_index_entry(self, key: str, payload: dict[str, Any]) -> None:
        self.index_cache.set(key, payload)


class CamelToolsCli:
    def __init__(self, cache_dir: Path, morphology_backoff: str = "NOAN_PROP"):
        self.token_cache = JsonCache(cache_dir / "tokenize_cache.json")
        self.morph_cache = JsonCache(cache_dir / "morph_cache.json")
        self.morphology_backoff = morphology_backoff

    def flush(self) -> None:
        self.token_cache.flush()
        self.morph_cache.flush()

    @staticmethod
    def _token_cache_key(text: str) -> str:
        return f"v{CACHE_VERSION}:{text}"

    @staticmethod
    def _morph_cache_key(token: str) -> str:
        return f"v{CACHE_VERSION}:{token}"

    @staticmethod
    def _prepare_tokenizer_input(text: str) -> str:
        return " ".join((text or "").split())

    def _run(self, args: list[str], payload: str) -> str:
        try:
            completed = subprocess.run(
                args,
                input=payload,
                text=True,
                capture_output=True,
                check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Required command not found: {args[0]}") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.stderr.strip() or exc.stdout.strip() or str(exc)) from exc
        return completed.stdout

    def tokenize(self, texts: list[str]) -> list[list[str]]:
        uncached = [
            text
            for text in texts
            if self.token_cache.get(self._token_cache_key(text)) is None
        ]
        if uncached:
            prepared_inputs = [self._prepare_tokenizer_input(text) for text in uncached]
            batch_inputs = [prepared or " " for prepared in prepared_inputs]
            output = self._run(["camel_word_tokenize"], "\n".join(batch_inputs))
            lines = output.splitlines()

            if len(lines) == len(uncached):
                for text, tokenized in zip(uncached, lines, strict=True):
                    raw_tokens: list[str] = []
                    for token in tokenized.split():
                        raw_token = ArabicNormalizer.preserve_raw_arabic_token(token)
                        if raw_token:
                            raw_tokens.append(raw_token)
                    self.token_cache.set(self._token_cache_key(text), raw_tokens)
            else:
                # Fallback for rare CLI edge cases: tokenize each text separately
                # instead of aborting the whole pipeline.
                for text, prepared in zip(uncached, prepared_inputs, strict=True):
                    if not prepared:
                        self.token_cache.set(self._token_cache_key(text), [])
                        continue
                    tokenized = self._run(["camel_word_tokenize"], prepared)
                    raw_tokens: list[str] = []
                    for token in tokenized.split():
                        raw_token = ArabicNormalizer.preserve_raw_arabic_token(token)
                        if raw_token:
                            raw_tokens.append(raw_token)
                    self.token_cache.set(self._token_cache_key(text), raw_tokens)
        return [self.token_cache.get(self._token_cache_key(text)) or [] for text in texts]

    def analyze_tokens(self, tokens: Iterable[str], batch_size: int = 256) -> dict[str, dict[str, str]]:
        unique_tokens = [token for token in dict.fromkeys(tokens) if token]
        missing = [
            token
            for token in unique_tokens
            if self.morph_cache.get(self._morph_cache_key(token)) is None
        ]
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            payload = "\n".join(batch)
            output = self._run(
                ["camel_morphology", "analyze", "-b", self.morphology_backoff],
                payload,
            )
            analyses = self._parse_morphology_output(output)
            for token in batch:
                best = analyses.get(token)
                if best is None:
                    best = {
                        "lemma": token,
                        "stem": token,
                        "root": "",
                        "pos": "",
                    }
                self.morph_cache.set(self._morph_cache_key(token), best)
        return {
            token: self.morph_cache.get(self._morph_cache_key(token))
            or {"lemma": token, "stem": token, "root": "", "pos": ""}
            for token in unique_tokens
        }

    @staticmethod
    def _parse_analysis_line(line: str) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for chunk in line.split():
            if ":" not in chunk:
                continue
            key, value = chunk.split(":", 1)
            parsed[key] = value
        return parsed

    @classmethod
    def _parse_morphology_output(cls, output: str) -> dict[str, dict[str, str]]:
        grouped: dict[str, list[dict[str, str]]] = {}
        current_word: str | None = None
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#WORD:"):
                current_word = line.split(":", 1)[1].strip()
                grouped.setdefault(current_word, [])
                continue
            if current_word is None:
                continue
            grouped[current_word].append(cls._parse_analysis_line(line))

        parsed: dict[str, dict[str, str]] = {}
        for word, analyses in grouped.items():
            if not analyses:
                continue
            best = max(
                analyses,
                key=lambda item: (
                    float(item.get("pos_lex_logprob", "-999")),
                    float(item.get("lex_logprob", "-999")),
                ),
            )
            lemma = ArabicNormalizer.norm(best.get("lex", word)) or word
            stem = ArabicNormalizer.norm(best.get("stem", lemma)) or lemma
            root = ArabicNormalizer.norm(best.get("root", "").replace(".", " "))
            parsed[word] = {
                "lemma": lemma,
                "stem": stem,
                "root": root,
                "pos": best.get("pos", ""),
            }
        return parsed


class ArabicTextPreprocessor:
    def __init__(self, camel_cli: CamelToolsCli, ngram_config: dict[str, int]):
        self.camel_cli = camel_cli
        self.ngram_config = ngram_config

    def prepare_many(self, texts: list[str]) -> list[PreparedText]:
        raw_token_lists = self.camel_cli.tokenize(texts)
        morphologies = self.camel_cli.analyze_tokens(
            token for tokens in raw_token_lists for token in tokens
        )
        prepared: list[PreparedText] = []
        for raw_text, raw_tokens in zip(texts, raw_token_lists, strict=True):
            normalized_tokens = [
                normalized_token
                for raw_token in raw_tokens
                for normalized_token in ArabicNormalizer.normalize(raw_token)
            ]
            lemmas = [morphologies[token]["lemma"] for token in raw_tokens]
            stems = [morphologies[token]["stem"] for token in raw_tokens]
            roots = [
                morphologies[token]["root"]
                for token in raw_tokens
                if morphologies[token]["root"]
            ]
            pos = [morphologies[token]["pos"] for token in raw_tokens]
            normalized_text = " ".join(normalized_tokens)
            prepared.append(
                PreparedText(
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    raw_tokens=raw_tokens,
                    normalized_tokens=normalized_tokens,
                    lemmas=lemmas,
                    stems=stems,
                    roots=roots,
                    pos=pos,
                    edge_ngrams=self._edge_ngrams(normalized_tokens),
                    char_ngrams=self._char_ngrams(normalized_tokens),
                )
            )
        return prepared

    def _edge_ngrams(self, tokens: Iterable[str]) -> list[str]:
        min_n = int(self.ngram_config["edge_min"])
        max_n = int(self.ngram_config["edge_max"])
        values: list[str] = []
        for token in tokens:
            token_len = len(token)
            if token_len < min_n:
                continue
            for size in range(min_n, min(max_n, token_len) + 1):
                values.append(token[:size])
        return list(dict.fromkeys(values))

    def _char_ngrams(self, tokens: Iterable[str]) -> list[str]:
        min_n = int(self.ngram_config["char_min"])
        max_n = int(self.ngram_config["char_max"])
        values: list[str] = []
        for token in tokens:
            token_len = len(token)
            if token_len < min_n:
                values.append(token)
                continue
            for size in range(min_n, min(max_n, token_len) + 1):
                for start in range(0, token_len - size + 1):
                    values.append(token[start : start + size])
        return list(dict.fromkeys(values))


def prepare_many_cached(
    run_cache: RunCache,
    cache_prefix: str,
    spec: DbSpec,
    rows: list[dict[str, str]],
    limit: int | None,
    preprocessor: ArabicTextPreprocessor,
) -> tuple[list[PreparedText], str, bool]:
    dataset_signature = run_cache.dataset_signature(spec, rows, limit)
    cache_key = f"{cache_prefix}:{dataset_signature}"
    cached = run_cache.get_prepared(cache_key)
    if cached is not None:
        return cached, dataset_signature, True
    prepared = preprocessor.prepare_many([row["raw_text"] for row in rows])
    run_cache.set_prepared(cache_key, prepared)
    return prepared, dataset_signature, False


class DynamicStopWords:
    def __init__(self, prepared_docs: list[PreparedText]):
        self.prepared_docs = prepared_docs

    def build(self) -> tuple[list[str], dict[str, Any]]:
        doc_tokens = [
            doc.normalized_tokens for doc in self.prepared_docs if doc.normalized_tokens
        ]
        if not doc_tokens:
            return [], {"p95": 1.0, "stop_words": [], "pos_count": {}}
        df_counter: Counter[str] = Counter()
        pos_map: dict[str, list[str]] = {}
        for doc in self.prepared_docs:
            for token in dict.fromkeys(doc.normalized_tokens):
                df_counter[token] += 1
            for token, pos in zip(doc.normalized_tokens, doc.pos, strict=False):
                if pos:
                    pos_map.setdefault(token, []).append(pos)
        ratios = np.array([count / float(len(doc_tokens)) for count in df_counter.values()])
        p95 = float(np.percentile(ratios, 95))
        stop_words = sorted(
            token for token, count in df_counter.items() if (count / float(len(doc_tokens))) > p95
        )
        pos_count = Counter()
        for token in stop_words:
            values = pos_map.get(token, [])
            if values:
                pos_count.update([Counter(values).most_common(1)[0][0]])
        report = {
            "p95": p95,
            "doc_count": len(doc_tokens),
            "stop_words": stop_words,
            "pos_count": dict(pos_count),
        }
        return stop_words, report


class MeiliClient:
    def __init__(self, base_url: str, api_key: str | None, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            timeout=self.timeout,
            **kwargs,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} failed: {response.status_code} {response.text}")
        return response

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health").json()

    def ensure_index(self, uid: str, primary_key: str) -> None:
        response = self.session.get(f"{self.base_url}/indexes/{uid}", timeout=self.timeout)
        if response.status_code == 404:
            task = self._request(
                "POST",
                "/indexes",
                json={"uid": uid, "primaryKey": primary_key},
            ).json()
            self.wait_for_task(int(task["taskUid"]))
            return
        if response.status_code >= 400:
            raise RuntimeError(f"Unable to inspect index {uid}: {response.text}")

    def delete_documents(self, uid: str) -> None:
        task = self._request("DELETE", f"/indexes/{uid}/documents").json()
        self.wait_for_task(int(task["taskUid"]))

    def update_settings(self, uid: str, settings: dict[str, Any]) -> None:
        task = self._request("PATCH", f"/indexes/{uid}/settings", json=settings).json()
        self.wait_for_task(int(task["taskUid"]))

    def add_documents(self, uid: str, documents: list[dict[str, Any]], primary_key: str) -> None:
        task = self._request(
            "POST",
            f"/indexes/{uid}/documents",
            params={"primaryKey": primary_key},
            json=documents,
        ).json()
        self.wait_for_task(int(task["taskUid"]))

    def search(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/indexes/{uid}/search", json=body).json()

    def wait_for_task(self, task_uid: int, timeout_s: int = 300) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            payload = self._request("GET", f"/tasks/{task_uid}").json()
            status = payload.get("status")
            if status == "succeeded":
                return payload
            if status == "failed":
                raise RuntimeError(f"Task {task_uid} failed: {json.dumps(payload, ensure_ascii=False)}")
            time.sleep(0.5)
        raise TimeoutError(f"Timed out waiting for task {task_uid}")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged[key] = deep_merge(base[key], value)
        else:
            merged[key] = value
    return merged


def safe_ident(name: str) -> str:
    if name == "rowid":
        return name
    if not IDENT_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name}")
    return name


def load_rows(spec: DbSpec, limit: int | None = None) -> list[dict[str, str]]:
    table = safe_ident(spec.table)
    col = safe_ident(spec.col)
    id_col = safe_ident(spec.id_col)
    query = (
        f"SELECT rowid AS rowid_value, {id_col} AS source_id, {col} AS raw_text "
        f"FROM {table} WHERE {col} IS NOT NULL AND TRIM({col}) != ''"
    )
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    conn = sqlite3.connect(spec.path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query).fetchall()
    finally:
        conn.close()
    output = []
    for row in rows:
        output.append(
            {
                "rowid": str(row["rowid_value"]),
                "source_id": "" if row["source_id"] is None else str(row["source_id"]),
                "raw_text": str(row["raw_text"]),
            }
        )
    return output


def build_index_uid(spec: DbSpec) -> str:
    stem = Path(spec.path).stem.lower()
    prefix = re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "db"
    digest = hashlib.sha1(f"{spec.path}|{spec.table}|{spec.col}".encode("utf-8")).hexdigest()[:8]
    return f"arabic_{prefix}_{digest}"


def build_document(
    spec: DbSpec,
    row: dict[str, str],
    prepared: PreparedText,
) -> dict[str, Any]:
    doc_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(spec.path).stem)
    return {
        "doc_id": f"{doc_prefix}_{row['rowid']}",
        "source_db": Path(spec.path).name,
        "source_table": spec.table,
        "source_id": row["source_id"] or row["rowid"],
        "raw_text": row["raw_text"],
        "exact_text": prepared.exact_text,
        "normalized_text": prepared.normalized_text,
        "lemma_text": prepared.lemma_text,
        "stem_text": prepared.stem_text,
        "root_text": prepared.root_text,
        "edge_ngrams": " ".join(prepared.edge_ngrams),
        "char_ngrams": " ".join(prepared.char_ngrams),
        "token_count": len(prepared.normalized_tokens),
        "pos": prepared.pos,
    }


def normalize_specs(
    paths: list[str],
    tables: list[str],
    cols: list[str],
    id_cols: list[str],
) -> list[DbSpec]:
    if not paths:
        return []

    def broadcast(values: list[str], default: str) -> list[str]:
        if not values:
            return [default] * len(paths)
        if len(values) == 1 and len(paths) > 1:
            return values * len(paths)
        if len(values) != len(paths):
            raise ValueError(
                "Repeated --ref arguments must either provide one shared value or exactly one value per --ref."
            )
        return values

    return [
        DbSpec(path=path, table=table, col=col, id_col=id_col)
        for path, table, col, id_col in zip(
            paths,
            broadcast(tables, "hadiths"),
            broadcast(cols, "Arabic_Matn"),
            broadcast(id_cols, "rowid"),
            strict=True,
        )
    ]


def build_settings(config: dict[str, Any], stop_words: list[str]) -> dict[str, Any]:
    settings = copy.deepcopy(config["meili_settings"])
    settings["stopWords"] = stop_words
    return settings


def build_variants(config: dict[str, Any]) -> list[SearchVariant]:
    return [SearchVariant(**variant) for variant in config["search_variants"]]


def _pos_weight(pos_tag: str, pos_weights: dict[str, float]) -> float:
    return float(pos_weights.get((pos_tag or "").lower(), 1.0))


def _normalize_pos_list(pos_value: Any) -> list[str]:
    if pos_value is None:
        return []
    if isinstance(pos_value, list):
        return [str(item) for item in pos_value]
    if isinstance(pos_value, tuple):
        return [str(item) for item in pos_value]
    return []


def _filter_tokens(tokens: Iterable[str], stop_words: set[str]) -> list[str]:
    return [token for token in tokens if token and token not in stop_words]


def _filtered_text_tokens(text: str | None, stop_words: set[str]) -> list[str]:
    return _filter_tokens((text or "").split(), stop_words)


def _filtered_text(text: str | None, stop_words: set[str]) -> str:
    return " ".join(_filtered_text_tokens(text, stop_words))


def _filter_pos_by_tokens(
    tokens: list[str],
    pos_tags: list[str],
    stop_words: set[str],
) -> list[str]:
    filtered: list[str] = []
    for token, pos_tag in zip(tokens, pos_tags, strict=False):
        if token and token not in stop_words and pos_tag:
            filtered.append(pos_tag)
    return filtered


def _weighted_pos_overlap(
    query_pos: list[str],
    hit_pos: list[str],
    pos_weights: dict[str, float],
) -> float:
    if not query_pos or not hit_pos:
        return 0.0
    query_counter = Counter((tag or "").lower() for tag in query_pos if tag)
    hit_counter = Counter((tag or "").lower() for tag in hit_pos if tag)
    if not query_counter or not hit_counter:
        return 0.0

    all_tags = set(query_counter) | set(hit_counter)
    overlap = sum(
        min(query_counter[tag], hit_counter[tag]) * _pos_weight(tag, pos_weights)
        for tag in all_tags
    )
    total = sum(
        max(query_counter[tag], hit_counter[tag]) * _pos_weight(tag, pos_weights)
        for tag in all_tags
    )
    if total <= 0.0:
        return 0.0
    return float(overlap / total)


def rerank_hits(
    raw_results: dict[str, dict[str, Any]],
    query_doc: PreparedText,
    stop_words: set[str],
    pos_weights: dict[str, float],
    rerank_config: dict[str, float],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    filtered_query_normalized = _filtered_text(query_doc.normalized_text, stop_words)
    filtered_query_lemma = _filtered_text(query_doc.lemma_text, stop_words)
    filtered_query_stem = _filtered_text(query_doc.stem_text, stop_words)
    filtered_query_pos = _filter_pos_by_tokens(
        query_doc.normalized_tokens,
        query_doc.pos,
        stop_words,
    )
    for payload in raw_results.values():
        hit = payload["hit"]
        score = payload["score"]
        filtered_hit_normalized = _filtered_text(hit.get("normalized_text"), stop_words)
        filtered_hit_lemma = _filtered_text(hit.get("lemma_text"), stop_words)
        filtered_hit_stem = _filtered_text(hit.get("stem_text"), stop_words)
        pos_similarity = _weighted_pos_overlap(
            filtered_query_pos,
            _filter_pos_by_tokens(
                _filtered_text_tokens(hit.get("normalized_text"), stop_words),
                _normalize_pos_list(hit.get("pos")),
                stop_words,
            ),
            pos_weights,
        )
        if filtered_hit_normalized and filtered_hit_normalized == filtered_query_normalized:
            score += float(rerank_config["exact_bonus"])
        if filtered_query_lemma and filtered_hit_lemma == filtered_query_lemma:
            score += float(rerank_config["lemma_bonus"])
        if filtered_query_stem and filtered_hit_stem == filtered_query_stem:
            score += float(rerank_config["stem_bonus"])
        score *= 1.0 + (pos_similarity * float(rerank_config["pos_match_multiplier"]))
        ranked.append(
            {
                "score": score,
                "pos_similarity": pos_similarity,
                "filtered_normalized_text": filtered_hit_normalized,
                "filtered_lemma_text": filtered_hit_lemma,
                "filtered_stem_text": filtered_hit_stem,
                "variant_scores": payload["variant_scores"],
                "doc_id": hit.get("doc_id"),
                "source_db": hit.get("source_db"),
                "source_table": hit.get("source_table"),
                "source_id": hit.get("source_id"),
                "raw_text": hit.get("raw_text"),
                "normalized_text": hit.get("normalized_text"),
                "lemma_text": hit.get("lemma_text"),
                "stem_text": hit.get("stem_text"),
            }
        )
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def search_index(
    client: MeiliClient,
    index_uid: str,
    query_doc: PreparedText,
    variants: list[SearchVariant],
    stop_words: set[str],
    pos_weights: dict[str, float],
    rerank_config: dict[str, float],
    top_k: int,
) -> list[dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    for variant in variants:
        query_text = getattr(query_doc, variant.query_field)
        if not query_text:
            continue
        response = client.search(
            index_uid,
            {
                "q": query_text,
                "limit": top_k,
                "showRankingScore": True,
                "attributesToSearchOn": variant.attributes,
            },
        )
        for rank, hit in enumerate(response.get("hits", []), start=1):
            base_score = float(hit.get("_rankingScore") or 0.0)
            if base_score <= 0.0:
                base_score = 1.0 / rank
            payload = combined.setdefault(
                hit["doc_id"],
                {"hit": hit, "score": 0.0, "variant_scores": {}},
            )
            contribution = base_score * variant.weight
            payload["score"] += contribution
            payload["variant_scores"][variant.name] = contribution
    return rerank_hits(combined, query_doc, stop_words, pos_weights, rerank_config)[:top_k]


def index_reference(
    spec: DbSpec,
    rows: list[dict[str, str]],
    prepared_docs: list[PreparedText],
    client: MeiliClient,
    config: dict[str, Any],
    batch_size: int,
    recreate: bool,
) -> tuple[str, dict[str, Any]]:
    index_uid = build_index_uid(spec)
    stop_words, stopword_report = DynamicStopWords(prepared_docs).build()
    settings = build_settings(config, stop_words)
    client.ensure_index(index_uid, primary_key="doc_id")
    if recreate:
        client.delete_documents(index_uid)
    client.update_settings(index_uid, settings)
    documents = [
        build_document(spec, row=row, prepared=prepared)
        for row, prepared in zip(rows, prepared_docs, strict=True)
    ]
    for start in range(0, len(documents), batch_size):
        client.add_documents(
            index_uid,
            documents[start : start + batch_size],
            primary_key="doc_id",
        )
    return index_uid, {"stopwords": stopword_report, "documents": len(documents)}


def ensure_reference_index(
    run_cache: RunCache,
    spec: DbSpec,
    rows: list[dict[str, str]],
    prepared_docs: list[PreparedText],
    dataset_signature: str,
    config_signature: str,
    client: MeiliClient,
    config: dict[str, Any],
    batch_size: int,
    keep_existing: bool,
) -> tuple[str, dict[str, Any]]:
    index_uid = build_index_uid(spec)
    stop_words, stopword_report = DynamicStopWords(prepared_docs).build()
    settings = build_settings(config, stop_words)
    cache_key = f"{index_uid}:{dataset_signature}:{config_signature}"
    cached_entry = run_cache.get_index_entry(cache_key)

    client.ensure_index(index_uid, primary_key="doc_id")
    if cached_entry is not None and not keep_existing:
        return index_uid, {
            "stopwords": cached_entry["stopwords"],
            "documents": cached_entry["documents"],
            "cache_hit": True,
        }

    if not keep_existing:
        client.delete_documents(index_uid)
    client.update_settings(index_uid, settings)
    documents = [
        build_document(spec, row=row, prepared=prepared)
        for row, prepared in zip(rows, prepared_docs, strict=True)
    ]
    for start in range(0, len(documents), batch_size):
        client.add_documents(
            index_uid,
            documents[start : start + batch_size],
            primary_key="doc_id",
        )

    cache_payload = {
        "index_uid": index_uid,
        "documents": len(documents),
        "stopwords": stopword_report,
        "dataset_signature": dataset_signature,
        "config_signature": config_signature,
    }
    run_cache.set_index_entry(cache_key, cache_payload)
    return index_uid, {
        "stopwords": stopword_report,
        "documents": len(documents),
        "cache_hit": False,
    }


def run_pipeline(args: argparse.Namespace) -> int:
    config = DEFAULT_CONFIG
    if args.config:
        user_config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        config = deep_merge(DEFAULT_CONFIG, user_config)

    cand = DbSpec(
        path=args.cand,
        table=args.cand_table,
        col=args.cand_col,
        id_col=args.cand_id_col,
    )
    refs = normalize_specs(args.ref, args.ref_table, args.ref_col, args.ref_id_col)
    if not refs:
        raise ValueError("At least one --ref database is required.")

    cache_dir = Path(args.cache_dir)
    camel_cli = CamelToolsCli(cache_dir=cache_dir)
    run_cache = RunCache(cache_dir=cache_dir)
    preprocessor = ArabicTextPreprocessor(camel_cli=camel_cli, ngram_config=config["ngram"])
    variants = build_variants(config)
    config_signature = run_cache.config_signature(config)

    try:
        cand_rows = load_rows(cand, limit=args.cand_limit)
        ref_rows_by_spec = {ref.path + ref.table + ref.col: load_rows(ref, limit=args.ref_limit) for ref in refs}
        cand_prepared, cand_signature, cand_cache_hit = prepare_many_cached(
            run_cache=run_cache,
            cache_prefix="cand",
            spec=cand,
            rows=cand_rows,
            limit=args.cand_limit,
            preprocessor=preprocessor,
        )
        ref_prepared_by_key: dict[str, list[PreparedText]] = {}
        ref_signature_by_key: dict[str, str] = {}
        ref_prepare_cache_hits: dict[str, bool] = {}
        for ref in refs:
            key = ref.path + ref.table + ref.col
            prepared_docs, dataset_signature, cache_hit = prepare_many_cached(
                run_cache=run_cache,
                cache_prefix="ref",
                spec=ref,
                rows=ref_rows_by_spec[key],
                limit=args.ref_limit,
                preprocessor=preprocessor,
            )
            ref_prepared_by_key[key] = prepared_docs
            ref_signature_by_key[key] = dataset_signature
            ref_prepare_cache_hits[key] = cache_hit
        camel_cli.flush()
        run_cache.flush()

        debug_payload = {
            "candidate_rows": len(cand_rows),
            "candidate_prepare_cache_hit": cand_cache_hit,
            "reference_rows": {
                Path(ref.path).name: len(ref_rows_by_spec[ref.path + ref.table + ref.col]) for ref in refs
            },
            "reference_prepare_cache_hits": {
                Path(ref.path).name: ref_prepare_cache_hits[ref.path + ref.table + ref.col]
                for ref in refs
            },
        }
        print(json.dumps(debug_payload, ensure_ascii=False, indent=2))

        index_reports: dict[str, Any] = {}
        index_uids: dict[str, str] = {}
        if not args.dry_run:
            client = MeiliClient(args.meili_url, args.meili_key)
            client.health()
            for ref in refs:
                key = ref.path + ref.table + ref.col
                index_uid, report = ensure_reference_index(
                    run_cache=run_cache,
                    spec=ref,
                    rows=ref_rows_by_spec[key],
                    prepared_docs=ref_prepared_by_key[key],
                    dataset_signature=ref_signature_by_key[key],
                    config_signature=config_signature,
                    client=client,
                    config=config,
                    batch_size=args.batch_size,
                    keep_existing=args.keep_existing,
                )
                index_reports[index_uid] = report
                index_uids[key] = index_uid
                print(json.dumps({"indexed": index_uid, **report}, ensure_ascii=False, indent=2))
            run_cache.flush()

            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            results: list[dict[str, Any]] = []
            for row, prepared in zip(cand_rows, cand_prepared, strict=True):
                result_entry = {
                    "candidate": {
                        "db": Path(cand.path).name,
                        "table": cand.table,
                        "source_id": row["source_id"] or row["rowid"],
                        "raw_text": row["raw_text"],
                        "normalized_text": prepared.normalized_text,
                        "lemma_text": prepared.lemma_text,
                        "stem_text": prepared.stem_text,
                    },
                    "matches": [],
                }
                for ref in refs:
                    key = ref.path + ref.table + ref.col
                    result_entry["matches"].append(
                        {
                            "ref_db": Path(ref.path).name,
                            "index_uid": index_uids[key],
                            "hits": search_index(
                                client,
                                index_uid=index_uids[key],
                                query_doc=prepared,
                                variants=variants,
                                stop_words=set(index_reports[index_uids[key]]["stopwords"]["stop_words"]),
                                pos_weights=config["pos_weights"],
                                rerank_config=config["rerank"],
                                top_k=args.top_k,
                            ),
                        }
                    )
                results.append(result_entry)

            output_payload = {
                "run": debug_payload,
                "indexes": [
                    {"index_uid": index_uid, **report}
                    for index_uid, report in index_reports.items()
                ],
                "results": results,
            }
            output_path.write_text(
                json.dumps(output_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(json.dumps({"written": str(output_path)}, ensure_ascii=False, indent=2))
        else:
            samples = []
            for row, prepared in list(zip(cand_rows, cand_prepared, strict=True))[: min(3, len(cand_rows))]:
                samples.append(
                    {
                        "source_id": row["source_id"] or row["rowid"],
                        "normalized_text": prepared.normalized_text,
                        "lemma_text": prepared.lemma_text,
                        "stem_text": prepared.stem_text,
                        "edge_ngrams": prepared.edge_ngrams[:12],
                        "char_ngrams": prepared.char_ngrams[:12],
                    }
                )
            print(json.dumps({"dry_run_preview": samples}, ensure_ascii=False, indent=2))
    finally:
        camel_cli.flush()
        run_cache.flush()

    return 0


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.single is not None:
        return

    missing = []
    if not args.cand:
        missing.append("--cand")
    if not args.cand_table:
        missing.append("--cand-table")
    if not args.cand_col:
        missing.append("--cand-col")
    if missing:
        parser.error("Missing required arguments for DB-vs-DB mode: " + ", ".join(missing))
    if not args.ref:
        parser.error("At least one --ref database is required in DB-vs-DB mode.")


def run_single_query(args: argparse.Namespace) -> int:
    config = DEFAULT_CONFIG
    if args.config:
        user_config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        config = deep_merge(DEFAULT_CONFIG, user_config)

    ref = DbSpec(
        path=args.single_ref,
        table=args.single_table,
        col=args.single_col,
        id_col=args.single_id_col,
    )
    cache_dir = Path(args.cache_dir)
    camel_cli = CamelToolsCli(cache_dir=cache_dir)
    run_cache = RunCache(cache_dir=cache_dir)
    preprocessor = ArabicTextPreprocessor(camel_cli=camel_cli, ngram_config=config["ngram"])
    variants = build_variants(config)
    config_signature = run_cache.config_signature(config)

    try:
        ref_rows = load_rows(ref, limit=args.ref_limit)
        ref_prepared, ref_signature, ref_cache_hit = prepare_many_cached(
            run_cache=run_cache,
            cache_prefix="ref",
            spec=ref,
            rows=ref_rows,
            limit=args.ref_limit,
            preprocessor=preprocessor,
        )
        query_doc = preprocessor.prepare_many([args.single])[0]
        camel_cli.flush()
        run_cache.flush()

        client = MeiliClient(args.meili_url, args.meili_key)
        client.health()
        index_uid, index_report = ensure_reference_index(
            run_cache=run_cache,
            spec=ref,
            rows=ref_rows,
            prepared_docs=ref_prepared,
            dataset_signature=ref_signature,
            config_signature=config_signature,
            client=client,
            config=config,
            batch_size=args.batch_size,
            keep_existing=args.keep_existing,
        )
        run_cache.flush()

        fetch_k = max(args.top_k * 10, 25)
        stop_words = set(index_report["stopwords"]["stop_words"])
        hits = search_index(
            client,
            index_uid=index_uid,
            query_doc=query_doc,
            variants=variants,
            stop_words=stop_words,
            pos_weights=config["pos_weights"],
            rerank_config=config["rerank"],
            top_k=fetch_k,
        )
        excluded_source_id = None if args.exclude_source_id is None else str(args.exclude_source_id)
        filtered_query_normalized = _filtered_text(query_doc.normalized_text, stop_words)
        filtered_hits: list[dict[str, Any]] = []
        for hit in hits:
            if excluded_source_id is not None and str(hit.get("source_id")) == excluded_source_id:
                continue
            if hit.get("normalized_text") == query_doc.normalized_text:
                continue
            if hit.get("filtered_normalized_text") == filtered_query_normalized:
                continue
            filtered_hits.append(hit)
            if len(filtered_hits) >= args.top_k:
                break

        print(
            json.dumps(
                {
                    "query": {
                        "raw_text": args.single,
                        "normalized_text": query_doc.normalized_text,
                    },
                    "reference": {
                        "db": Path(ref.path).name,
                        "table": ref.table,
                        "col": ref.col,
                        "id_col": ref.id_col,
                        "rows": len(ref_rows),
                        "prepare_cache_hit": ref_cache_hit,
                        "index_uid": index_uid,
                        "index_report": index_report,
                    },
                    "matches": filtered_hits,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        camel_cli.flush()
        run_cache.flush()

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Index Arabic reference corpora in a local Meilisearch instance and search "
            "every row from a candidate SQLite DB against one or more reference DBs, "
            "or run a single raw-text lookup against quran.db."
        )
    )
    parser.add_argument(
        "--single",
        default=None,
        help="Search one raw Arabic text directly against the reference DB.",
    )
    parser.add_argument("--cand", required=False, help="Path to the candidate SQLite DB.")
    parser.add_argument("--cand-table", required=False, help="Candidate table name.")
    parser.add_argument("--cand-col", required=False, help="Candidate text column.")
    parser.add_argument(
        "--cand-id-col",
        default="rowid",
        help="Candidate ID column. Defaults to rowid.",
    )
    parser.add_argument("--ref", action="append", default=[], help="Reference SQLite DB path.")
    parser.add_argument(
        "--ref-table",
        action="append",
        default=[],
        help="Reference table name. Repeat once per --ref or pass one shared value.",
    )
    parser.add_argument(
        "--ref-col",
        action="append",
        default=[],
        help="Reference text column. Repeat once per --ref or pass one shared value.",
    )
    parser.add_argument(
        "--ref-id-col",
        action="append",
        default=[],
        help="Reference ID column. Repeat once per --ref or pass one shared value.",
    )
    parser.add_argument(
        "--meili-url",
        default="http://127.0.0.1:7700",
        help="Local Meilisearch URL.",
    )
    parser.add_argument(
        "--meili-key",
        default=DEFAULT_MEILI_SEARCH_KEY,
        help="Optional Meilisearch API key for search requests.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional JSON config to override ranking rules, fields, and n-gram settings.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help="Directory for CAMeL tokenizer and morphology caches.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Pretty-printed JSON output path for db-vs-db search results.",
    )
    parser.add_argument(
        "--single-ref",
        default=str(DEFAULT_QURAN_DB_PATH),
        help="Reference SQLite DB path for --single mode. Defaults to QuranQuizz/quran.db.",
    )
    parser.add_argument(
        "--single-table",
        default="ayah_metadata_new",
        help="Reference table name for --single mode.",
    )
    parser.add_argument(
        "--single-col",
        default="ayah_text",
        help="Reference text column for --single mode.",
    )
    parser.add_argument(
        "--single-id-col",
        default="id",
        help="Reference ID column for --single mode.",
    )
    parser.add_argument(
        "--exclude-source-id",
        type=str,
        default=None,
        help="Optional source_id to exclude from --single results.",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Number of matches per reference DB.")
    parser.add_argument("--batch-size", type=int, default=500, help="Meilisearch indexing batch size.")
    parser.add_argument("--cand-limit", type=int, default=None, help="Optional candidate row limit.")
    parser.add_argument("--ref-limit", type=int, default=None, help="Optional reference row limit per DB.")
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not clear existing Meilisearch documents before reindexing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only preprocess DB content and print previews without touching Meilisearch.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_args(parser, args)
        if args.single:
            return run_single_query(args)
        return run_pipeline(args)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
