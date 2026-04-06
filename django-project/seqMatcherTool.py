from difflib import SequenceMatcher
import numpy as np
from pathlib import Path
import argparse
import json
from sacrebleu.metrics import BLEU
from pprint import pprint
from utils import utils, config, StopWords


BASE_DIR = Path(__file__).resolve().parent


def _pos_weight(pos_tag):
    tag = (pos_tag or "").lower()
    if tag not in config.POS_WEIGHTS:
        raise KeyError(f"Unknown POS tag '{tag}' not found in config.POS_WEIGHTS.")
    return config.POS_WEIGHTS[tag]


def _parse_pos(pos_value):
    if pos_value is None:
        raise ValueError("POS value cannot be None.")
    if isinstance(pos_value, (list, tuple)):
        return [str(x) for x in pos_value]
    if isinstance(pos_value, str) and pos_value.strip():
        try:
            parsed = json.loads(pos_value)
        except json.JSONDecodeError as exc:
            raise ValueError("POS must be stored as a JSON array string.") from exc
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
        raise ValueError("POS JSON must decode to an array.")
    raise TypeError(
        "Unsupported POS payload type. Expected JSON array string or list/tuple."
    )


def _dynamic_bleu_weights(max_order, reference_pos):
    if reference_pos is None:
        raise ValueError(
            "reference_pos is required. Compute POS once during initialization and pass it to f1()."
        )
    pos_tags = _parse_pos(reference_pos)
    if not pos_tags:
        raise ValueError(
            "reference_pos is empty. POS must be precomputed in initialization stage."
        )

    token_weights = [_pos_weight(tag) for tag in pos_tags] or [1.0]
    avg_weight = float(sum(token_weights) / len(token_weights))
    order_scores = [
        (avg_weight**n) / np.sqrt(float(n)) for n in range(1, max_order + 1)
    ]
    total = float(sum(order_scores))
    return [float(x / total) for x in order_scores]


def f1(reference, candidate, wheights=None, max_order=2, reference_pos=None):
    if wheights is None:
        wheights = _dynamic_bleu_weights(
            max_order=max_order,
            reference_pos=reference_pos,
        )
    if len(wheights) != max_order:
        raise ValueError(f"Length of weights must match max_order ({max_order}).")

    reference_list = reference if isinstance(reference, list) else [reference]
    candidate_list = candidate if isinstance(candidate, list) else [candidate]

    bleu_obj = BLEU(max_ngram_order=max_order)
    bleu_obj.weights = wheights
    bleu_results = bleu_obj.corpus_score(candidate_list, [reference_list])

    P = bleu_results.score / 100
    R = _rouge_l(reference_list[0], candidate_list[0])
    beta = 1.9

    denom = (beta**2 * P + R) or 1e-12
    f1_score = (1 + beta**2) * (P * R) / denom
    return {"bleu": P, "rougeL": R, "f1": f1_score, "weights": wheights}


def _ensure_pos_coverage(indices, pos_tags, side, item_id):
    if not indices:
        return
    min_idx = min(int(v) for v in indices)
    max_idx = max(int(v) for v in indices)
    if min_idx < 0 or max_idx >= len(pos_tags):
        raise IndexError(
            f"{side} POS index out of range at ID:{item_id}. "
            f"index-range=[{min_idx},{max_idx}] pos-len={len(pos_tags)}"
        )


def _lcs_length(a_tokens, b_tokens):
    n = len(a_tokens)
    m = len(b_tokens)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        ai = a_tokens[i - 1]
        for j in range(1, m + 1):
            if ai == b_tokens[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = (
                    dp[i - 1][j] if dp[i - 1][j] >= dp[i][j - 1] else dp[i][j - 1]
                )
    return dp[n][m]


def _rouge_l(reference, candidate):
    ref_tokens = str(reference).split()
    cand_tokens = str(candidate).split()
    if not ref_tokens or not cand_tokens:
        return 0.0
    lcs = _lcs_length(ref_tokens, cand_tokens)
    recall = lcs / len(ref_tokens)
    precision = lcs / len(cand_tokens)
    beta = 1.2
    denom = recall + (beta**2) * precision
    if denom == 0:
        return 0.0
    return ((1 + beta**2) * recall * precision) / denom


def _stopword_factor(token, stop_words, stop_word_weight=0.25):
    return float(stop_word_weight) if token in stop_words else 1.0


def _short_candidate_bonus(reference, candidate, percentage):
    ref_len = max(1, len(str(reference).split()))
    cand_len = max(1, len(str(candidate).split()))
    len_sim = min(ref_len, cand_len) / max(ref_len, cand_len)
    shortness = max(0.0, 1.0 - (cand_len / 6.0))

    # Reward only short candidates that already show strong overlap signal.
    if shortness > 0.0 and len_sim >= 0.6 and percentage >= 0.65:
        return 0.30 * shortness * len_sim
    return 0.0


def diff_to_matrix(ref, cand):
    vec1_ids = []
    vec1_lens = []
    vec2_ids = []
    vec2_lens = []
    minus = ["replace", "delete", "insert"]
    plus = "equal"

    for list_list in SequenceMatcher(None, ref, cand).get_grouped_opcodes():
        for list_e in list_list:
            list_m = list(list_e)
            if (
                (list_m[2] - list_m[1]) < 3
                and (list_m[4] - list_m[3]) < 3
                and ref[list_m[1] : list_m[1] + list_m[2]] not in ref.strip().split()
                and cand[list_m[3] : list_m[3] + (list_m[4])]
                not in cand.strip().split()
            ):
                continue
            if list_m[0] == plus:
                list_m[0] = 1
            elif list_m[0] in minus:
                list_m[0] = -1
            elif list_m != []:
                raise ValueError(f"Unexpected tag: {list_m[0]}")
            try:
                _1_ids, _1_lens = utils.char_idx_to_token_idx(
                    ref, [e for e in range(list_m[1], list_m[2] + 1)]
                )
                _2_ids, _2_lens = utils.char_idx_to_token_idx(
                    cand, [e for e in range(list_m[3], list_m[4] + 1)]
                )
                vec1_ids += _1_ids
                vec1_lens += [l * list_m[0] for l in _1_lens]
                vec2_ids += _2_ids
                vec2_lens += [l * list_m[0] for l in _2_lens]
            except IndexError:
                pass

    if vec1_ids == []:
        return (None,) * 4
    return vec1_ids, vec1_lens, vec2_ids, vec2_lens


def main():
    # { accept/reject : { id : [results] }}
    judgement: dict[str, dict[int, list]] = {"accept": {}, "reject": {}}
    parser = argparse.ArgumentParser(description="Sequence matcher tool")
    parser.add_argument("-db", "--db-path", default=str(BASE_DIR / "Data"))
    parser.add_argument("--table", default="hadiths")
    parser.add_argument("--text-col", default="Arabic_Matn")
    parser.add_argument("--normalized-col", default="normalized")
    parser.add_argument("--id-col", default="Hadith_number")
    parser.add_argument(
        "-txt",
        "--hadith-txt",
        default=str(
            BASE_DIR / "Data" / "Sahihah" / "sahihah_hadith_extracted_in_sittah.txt"
        ),
    )
    # Provisorisch
    parser.add_argument(
        "--current-db",
        default=str(BASE_DIR / "Data" / "Hadith" / "Bukhari.db"),
    )
    args = parser.parse_args()

    config.db_path = args.db_path
    config.table = args.table
    config.text_col = args.text_col
    config.normalized_col = args.normalized_col
    config.id_col = args.id_col
    config.hadith_txt = args.hadith_txt

    db_txt = utils.get_txt_from_db(current_db=args.current_db, config=config)
    cand_txt, cand_meta = utils.get_cand_txt()
    corpus_docs = [val["normalized"] for val in cand_meta.values()] + [
        row[2] for row in db_txt if row and len(row) > 2 and row[2]
    ]
    stop_words_info = StopWords.stop_words(corpus=corpus_docs)
    stop_words = set(stop_words_info.get("stop_words") or [])
    stop_word_weight = float(stop_words_info.get("stop_word_weight", 0.25))
    # print("Stop words:", stop_words_info)

    for i, (key, val) in enumerate(cand_meta.items()):
        ref_norm = " ".join(utils.normalize(db_txt[i][2]))
        ref_tokens = ref_norm.split()
        cand_tokens = val["normalized"].split()
        ref_pos = _parse_pos(db_txt[i][3])
        cand_pos = _parse_pos(val["pos"])
        vec1_ids, vec1_lens, vec2_ids, vec2_lens = diff_to_matrix(
            val["normalized"], ref_norm
        )
        try:
            if vec1_ids is None:
                # print(f"ID:{i+1} 100.00 % Übereinstimmung")
                continue
        except ValueError:
            pass

        _ensure_pos_coverage(vec1_ids, cand_pos, side="candidate", item_id=i + 1)
        _ensure_pos_coverage(vec2_ids, ref_pos, side="reference", item_id=i + 1)

        pos_matrix_1 = np.array(
            [
                _pos_weight(cand_pos[int(v)])
                * _stopword_factor(cand_tokens[int(v)], stop_words, stop_word_weight)
                for v in vec1_ids
            ],
            dtype=np.float64,
        )
        pos_matrix_2 = np.array(
            [
                _pos_weight(ref_pos[int(v)])
                * _stopword_factor(ref_tokens[int(v)], stop_words, stop_word_weight)
                for v in vec2_ids
            ],
            dtype=np.float64,
        )

        power_v1 = np.array(vec1_lens, dtype=np.float64) * pos_matrix_1
        power_v2 = np.array(vec2_lens, dtype=np.float64) * pos_matrix_2

        pos = np.where(power_v1 > 0, power_v1, 0)
        pos = np.append(pos, np.where(power_v2 > 0, power_v2, 0))
        neg = np.where(power_v1 < 0, power_v1, 0)
        neg = np.append(neg, np.where(power_v2 < 0, power_v2, 0))

        percentage = (np.sum(pos) / (np.sum(pos) + (np.sum(neg) * (-1)))) * 0.9
        f1_result = f1(
            reference=val["normalized"],
            candidate=ref_norm,
            reference_pos=val["pos"],
        )
        f1_result["f1"] *= 1.1
        smaller = min(percentage, f1_result["f1"])
        greater = max(percentage, f1_result["f1"])
        final_score = ((greater - smaller) / 2) + smaller
        final_score = min(
            1.0,
            final_score
            + _short_candidate_bonus(
                reference=val["normalized"],
                candidate=ref_norm,
                percentage=percentage,
            ),
        )
        # print(
        #     f'bleu={f1_result["bleu"]:.2f}',
        #     f'rougeL={f1_result["rougeL"]:.2f}',
        #     f'f1={f1_result["f1"]:.2f}',
        # )
        # print(f"percentage={percentage:.2f}")
        # print(f"ID:{i+1} {final_score*100:.2f}", "% Übereinstimmung")

        if final_score >= 0.5:
            judgement["accept"][i + 1] = [
                f'bleu={f1_result["bleu"]:.2f}',
                f'rougeL={f1_result["rougeL"]:.2f}',
                f'f1={f1_result["f1"]:.2f}',
                f"percentage={percentage:.2f}",
                f"ID:{i+1} {final_score*100:.2f}",
                "% Übereinstimmung",
            ]
        else:
            judgement["reject"][i + 1] = [
                f'bleu={f1_result["bleu"]:.2f}',
                f'rougeL={f1_result["rougeL"]:.2f}',
                f'f1={f1_result["f1"]:.2f}',
                f"percentage={percentage:.2f}",
                f"ID:{i+1} {final_score*100:.2f}",
                "% Übereinstimmung",
            ]
    print(json.dumps(judgement))


if __name__ == "__main__":
    main()
