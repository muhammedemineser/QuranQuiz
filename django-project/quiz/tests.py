import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import SimpleTestCase

import build_distractor_cache
from quiz import quran_db


class BuildDistractorCacheTests(SimpleTestCase):
    def test_build_seqmatcher_distractor_map_reranks_shortlist(self):
        rows = [
            (1, "alpha beta"),
            (2, "alpha gamma"),
            (3, "beta gamma"),
            (4, "delta epsilon"),
        ]

        def normalize_fn(text):
            return text.strip().lower()

        def score_fn(reference, candidate):
            ref_tokens = set(reference.split())
            cand_tokens = set(candidate.split())
            common = len(ref_tokens & cand_tokens)
            if common == 0:
                return 0.0
            return common / max(len(ref_tokens), len(cand_tokens))

        distractor_map, reranked_total = build_distractor_cache.build_seqmatcher_distractor_map(
            rows,
            top_k=2,
            fetch_k=3,
            normalize_fn=normalize_fn,
            score_fn=score_fn,
        )

        self.assertEqual(set(distractor_map.keys()), {1, 2, 3, 4})
        self.assertNotIn(1, distractor_map[1])
        self.assertEqual(len(distractor_map[1]), 2)
        self.assertGreater(reranked_total, 0)

    def test_build_seqmatcher_distractor_map_excludes_identical_normalized_text(self):
        rows = [
            (1, "foo bar"),
            (2, "foo bar"),
            (3, "foo baz"),
        ]
        distractor_map, _ = build_distractor_cache.build_seqmatcher_distractor_map(
            rows,
            top_k=2,
            fetch_k=3,
            normalize_fn=lambda text: text.strip().lower(),
            score_fn=lambda reference, candidate: 1.0,
        )
        self.assertNotIn(2, distractor_map[1])

    def test_build_cache_payload_shapes_output(self):
        rows = [(1, "foo bar"), (2, "foo baz"), (3, "bar baz")]

        payload = build_distractor_cache.build_cache_payload(
            rows,
            top_k=2,
            fetch_k=3,
            normalize_fn=lambda text: text,
            score_fn=lambda reference, candidate: float(len(set(reference.split()) & set(candidate.split()))),
        )

        self.assertIn("meta", payload)
        self.assertIn("distractors", payload)
        self.assertEqual(payload["meta"]["top_k"], 2)
        self.assertEqual(payload["meta"]["fetch_k"], 3)
        self.assertEqual(payload["meta"]["entries"], 3)
        self.assertIn("1", payload["distractors"])
        self.assertLessEqual(len(payload["distractors"]["1"]), 2)


class QuranDbCacheTests(SimpleTestCase):
    def test_cached_distractor_ids_prefers_precomputed_cache(self):
        with TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "distractor_cache.json"
            cache_path.write_text(
                json.dumps({"distractors": {"100": [201, 202, 203]}}),
                encoding="utf-8",
            )

            with mock.patch.object(quran_db, "PRECOMPUTED_DISTRACTOR_CACHE_PATH", cache_path):
                quran_db._load_precomputed_distractor_cache.cache_clear()
                quran_db._cached_distractor_ids.cache_clear()
                result = quran_db._cached_distractor_ids(100)

            self.assertEqual(result, (201, 202, 203))

    def test_get_distractors_excludes_duplicate_option_texts(self):
        fake_cache = {100: (201, 202, 203)}
        verses = {
            100: {quran_db.VERSE_TEXT_AR: "same text"},
            201: {quran_db.VERSE_TEXT_AR: "same text"},
            202: {quran_db.VERSE_TEXT_AR: "unique one"},
            203: {quran_db.VERSE_TEXT_AR: "unique two"},
        }

        with mock.patch.object(quran_db, "_cached_distractor_ids", return_value=fake_cache[100]):
            with mock.patch.object(quran_db, "get_verse_by_index", side_effect=lambda idx: verses.get(idx)):
                result = quran_db.get_distractors(100, n=3)

        texts = [row[quran_db.VERSE_TEXT_AR] for row in result]
        self.assertEqual(texts, ["unique one", "unique two"])
