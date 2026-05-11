import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tokenizer.omop_measurement_tokenizer import OMOPMeasurementTokenizer, OMOPMeasurementTokenizerConfig


def _base_df(rows):
    df = pd.DataFrame(rows)
    for col in [
        "person_id",
        "visit_occurrence_id",
        "measurement_datetime",
        "measurement_date",
        "measurement_concept_id",
        "unit_concept_id",
        "value_as_number",
    ]:
        if col not in df.columns:
            df[col] = None
    return df[
        [
            "person_id",
            "visit_occurrence_id",
            "measurement_datetime",
            "measurement_date",
            "measurement_concept_id",
            "unit_concept_id",
            "value_as_number",
        ]
    ]


class TestOMOPMeasurementTokenizer(unittest.TestCase):
    def test_normal_bin_and_outliers_and_missing(self):
        train = _base_df(
            [
                {"person_id": 1, "measurement_concept_id": 10, "unit_concept_id": 1, "value_as_number": v}
                for v in [70, 80, 90, 100, 110, 120, 130] * 10
            ]
        )
        cfg = OMOPMeasurementTokenizerConfig(num_bins=10, std_threshold=2.0, min_samples_per_concept=30)
        tok = OMOPMeasurementTokenizer(cfg).fit(train)

        self.assertEqual(tok.tokenize_single(10, 100, 1).split("_")[-2], "BIN")
        self.assertTrue(tok.tokenize_single(10, 0, 1).endswith("LOW_OUTLIER"))
        self.assertTrue(tok.tokenize_single(10, 10000, 1).endswith("HIGH_OUTLIER"))
        self.assertTrue(tok.tokenize_single(10, None, 1).endswith("MISSING"))

    def test_zero_std_maps_to_bin0(self):
        train = _base_df(
            [{"person_id": 1, "measurement_concept_id": 20, "unit_concept_id": 1, "value_as_number": 5.0}]
            * 40
        )
        tok = OMOPMeasurementTokenizer(OMOPMeasurementTokenizerConfig(min_samples_per_concept=30)).fit(train)
        self.assertTrue(tok.tokenize_single(20, 5.0, 1).endswith("BIN_0"))
        self.assertTrue(tok.tokenize_single(20, 999.0, 1).endswith("BIN_0"))

    def test_selection_min_count_only(self):
        train = _base_df(
            [{"person_id": 1, "measurement_concept_id": 1, "unit_concept_id": 1, "value_as_number": 1.0}] * 29
            + [{"person_id": 1, "measurement_concept_id": 2, "unit_concept_id": 1, "value_as_number": 2.0}] * 30
        )
        tok = OMOPMeasurementTokenizer(OMOPMeasurementTokenizerConfig(min_samples_per_concept=30)).fit(train)
        self.assertEqual(tok.get_selected_concepts(), [2])

    def test_selection_allowlist(self):
        train = _base_df(
            [{"person_id": 1, "measurement_concept_id": 1, "unit_concept_id": 1, "value_as_number": 1.0}] * 50
            + [{"person_id": 1, "measurement_concept_id": 2, "unit_concept_id": 1, "value_as_number": 2.0}] * 50
        )
        cfg = OMOPMeasurementTokenizerConfig(
            selection_strategy="allowlist",
            selected_measurement_concept_ids=[2],
            min_samples_per_concept=30,
        )
        tok = OMOPMeasurementTokenizer(cfg).fit(train)
        self.assertEqual(tok.get_selected_concepts(), [2])

    def test_selection_top_k_frequency(self):
        train = _base_df(
            [{"person_id": 1, "measurement_concept_id": 1, "unit_concept_id": 1, "value_as_number": 1.0}] * 100
            + [{"person_id": 1, "measurement_concept_id": 2, "unit_concept_id": 1, "value_as_number": 2.0}] * 80
            + [{"person_id": 1, "measurement_concept_id": 3, "unit_concept_id": 1, "value_as_number": 3.0}] * 60
        )
        cfg = OMOPMeasurementTokenizerConfig(
            selection_strategy="top_k_frequency",
            max_measurement_concepts=2,
            min_samples_per_concept=30,
        )
        tok = OMOPMeasurementTokenizer(cfg).fit(train)
        self.assertEqual(tok.get_selected_concepts(), [1, 2])

    def test_unselected_concept_transform_skip(self):
        train = _base_df(
            [{"person_id": 1, "measurement_concept_id": 10, "unit_concept_id": 1, "value_as_number": 1.0}] * 40
        )
        tok = OMOPMeasurementTokenizer(OMOPMeasurementTokenizerConfig(handle_unselected="skip")).fit(train)
        df = _base_df(
            [
                {"person_id": 1, "measurement_concept_id": 999, "unit_concept_id": 1, "value_as_number": 1.0},
                {"person_id": 1, "measurement_concept_id": 10, "unit_concept_id": 1, "value_as_number": 1.0},
            ]
        )
        out = tok.transform(df)
        self.assertEqual(out.shape[0], 1)
        self.assertEqual(out["measurement_concept_id"].iloc[0], 10)

    def test_unit_aware_tokenization(self):
        train = _base_df(
            [{"person_id": 1, "measurement_concept_id": 10, "unit_concept_id": 1, "value_as_number": 1.0}] * 40
            + [{"person_id": 1, "measurement_concept_id": 10, "unit_concept_id": 2, "value_as_number": 1.0}] * 40
        )
        tok = OMOPMeasurementTokenizer(OMOPMeasurementTokenizerConfig(unit_aware=True, min_samples_per_concept=30)).fit(
            train
        )
        t1 = tok.tokenize_single(10, 1.0, unit_concept_id=1)
        t2 = tok.tokenize_single(10, 1.0, unit_concept_id=2)
        self.assertNotEqual(t1, t2)
        self.assertIn("UNIT_1", t1)
        self.assertIn("UNIT_2", t2)

    def test_save_load_consistency_and_deterministic_vocab(self):
        train = _base_df(
            [{"person_id": 1, "measurement_concept_id": 10, "unit_concept_id": 1, "value_as_number": v} for v in range(40)]
        )
        tok = OMOPMeasurementTokenizer(OMOPMeasurementTokenizerConfig(min_samples_per_concept=30)).fit(train)
        vocab_before = tok.get_vocab()

        with tempfile.TemporaryDirectory() as td:
            path = f"{td}/tok.json"
            tok.save(path)
            tok2 = OMOPMeasurementTokenizer.load(path)
            self.assertEqual(tok2.get_vocab(), vocab_before)
            self.assertEqual(tok2.tokenize_single(10, 1.0, 1), tok.tokenize_single(10, 1.0, 1))

            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertIn("token_to_id", payload)

    def test_transform_does_not_recompute_stats(self):
        train = _base_df(
            [{"person_id": 1, "measurement_concept_id": 10, "unit_concept_id": 1, "value_as_number": v} for v in range(40)]
        )
        tok = OMOPMeasurementTokenizer(OMOPMeasurementTokenizerConfig(min_samples_per_concept=30)).fit(train)
        state_before = json.dumps(tok._to_state_dict(), sort_keys=True)
        _ = tok.transform(train)
        state_after = json.dumps(tok._to_state_dict(), sort_keys=True)
        self.assertEqual(state_before, state_after)


if __name__ == "__main__":
    unittest.main()
